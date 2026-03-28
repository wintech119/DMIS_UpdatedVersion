from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection

from masterdata.services.data_access import TABLE_REGISTRY, create_record
from masterdata.services.operational_masters import validate_operational_master_payload
from masterdata.services.validation import validate_record
from operations.relief_test_data import (
    default_frontend_test_agency_name,
    default_frontend_test_warehouse_name,
)


class Command(BaseCommand):
    help = (
        "Seed temporary non-ODPEM warehouse and agency master data so Relief Management "
        "frontend request creation can run against live backend contracts. Dry-run by default."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--tenant-id", type=int, default=None, help="Existing target tenant ID.")
        parser.add_argument("--tenant-code", type=str, default="JRC", help="Existing target tenant code. Defaults to JRC.")
        parser.add_argument("--custodian-id", type=int, default=1, help="Existing custodian ID to own the warehouse. Defaults to 1.")
        parser.add_argument("--parish-code", type=str, default="01", help="Parish code for the temporary warehouse and agency. Defaults to 01.")
        parser.add_argument("--actor", type=str, default="SYSTEM", help="Actor user ID for audit columns.")
        parser.add_argument(
            "--warehouse-name",
            type=str,
            default=None,
            help="Optional explicit warehouse name. Defaults to 'S07 TEST MAIN HUB - <TENANT_CODE>'.",
        )
        parser.add_argument(
            "--agency-name",
            type=str,
            default=None,
            help="Optional explicit agency name. Defaults to 'S07 TEST DISTRIBUTOR AGENCY - <TENANT_CODE>'.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist changes. Without this flag, the command only previews the plan.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        actor_id = str(options.get("actor") or "SYSTEM").strip() or "SYSTEM"
        apply_changes = bool(options.get("apply"))
        parish_code = str(options.get("parish_code") or "01").strip() or "01"
        custodian_id = int(options.get("custodian_id") or 1)

        tenant = self._resolve_tenant(options.get("tenant_id"), options.get("tenant_code"))
        self._resolve_custodian(custodian_id)

        warehouse_name = str(options.get("warehouse_name") or "").strip() or default_frontend_test_warehouse_name(
            tenant["tenant_code"]
        )
        agency_name = str(options.get("agency_name") or "").strip() or default_frontend_test_agency_name(
            tenant["tenant_code"]
        )

        existing_warehouse = self._fetch_warehouse_by_name(warehouse_name)
        if existing_warehouse is not None:
            self._validate_existing_warehouse(existing_warehouse, target_tenant_id=tenant["tenant_id"])

        warehouse_payload = {
            "warehouse_name": warehouse_name,
            "warehouse_type": "MAIN-HUB",
            "address1_text": f"{tenant['tenant_name']} RELIEF TEST ADDRESS",
            "address2_text": "TEMPORARY FRONTEND TEST DATA",
            "parish_code": parish_code,
            "contact_name": "SPRINT SEVEN LEAD",
            "phone_no": "+1 (876) 555-0107",
            "email_text": "s07warehouse@test.gov.jm",
            "custodian_id": custodian_id,
            "min_stock_threshold": 0,
            "status_code": "A",
            "tenant_id": tenant["tenant_id"],
        }
        if existing_warehouse is None:
            self._validate_create_payload("warehouses", warehouse_payload)

        warehouse_id = int(existing_warehouse["warehouse_id"]) if existing_warehouse is not None else None

        existing_agency = self._fetch_agency_by_name(agency_name)
        if existing_agency is not None:
            if warehouse_id is None:
                raise CommandError(
                    "Agency already exists but the matching warehouse was not found; cannot verify ownership safely."
                )
            self._validate_existing_agency(existing_agency, expected_warehouse_id=warehouse_id)

        self.stdout.write("Relief Management frontend test-data seed:")
        self.stdout.write(f"- target tenant: {tenant['tenant_id']} ({tenant['tenant_code']}) {tenant['tenant_name']}")
        self.stdout.write(f"- parish code: {parish_code}")
        self.stdout.write(f"- custodian id: {custodian_id}")
        self.stdout.write(f"- warehouse: {warehouse_name} ({'reuse' if existing_warehouse else 'create'})")
        self.stdout.write(f"- agency: {agency_name} ({'reuse' if existing_agency else 'create'})")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry-run only. Re-run with --apply to persist changes."))
            return

        if existing_warehouse is None:
            warehouse_id, warnings = create_record("warehouses", warehouse_payload, actor_id)
            if warehouse_id is None:
                raise CommandError(
                    "Unable to create the temporary warehouse."
                    + (f" warnings={warnings}" if warnings else "")
                )
            self.stdout.write(self.style.SUCCESS(f"Created warehouse {warehouse_id}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Reused warehouse {warehouse_id}"))

        agency_payload = {
            "agency_name": agency_name,
            "agency_type": "DISTRIBUTOR",
            "address1_text": f"{tenant['tenant_name']} RELIEF TEST ADDRESS",
            "address2_text": "TEMPORARY FRONTEND TEST DATA",
            "parish_code": parish_code,
            "contact_name": "AGENCY TEST USER",
            "phone_no": "+1 (876) 555-0108",
            "email_text": "s07agency@test.gov.jm",
            "warehouse_id": warehouse_id,
            "status_code": "A",
        }
        if existing_agency is None:
            self._validate_create_payload("agencies", agency_payload)
            agency_id, warnings = create_record("agencies", agency_payload, actor_id)
            if agency_id is None:
                raise CommandError(
                    "Unable to create the temporary agency."
                    + (f" warnings={warnings}" if warnings else "")
                )
            self.stdout.write(self.style.SUCCESS(f"Created agency {agency_id}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Reused agency {existing_agency['agency_id']}"))

        self.stdout.write(
            self.style.SUCCESS(
                "Temporary Relief Management frontend test data is ready. Run the agency audit and readiness check next."
            )
        )

    def _validate_create_payload(self, table_key: str, payload: dict[str, Any]) -> None:
        cfg = TABLE_REGISTRY[table_key]
        errors = validate_record(cfg, payload)
        operational_errors, _warnings = validate_operational_master_payload(table_key, payload, is_update=False)
        merged_errors = {**errors, **operational_errors}
        if merged_errors:
            rendered = ", ".join(f"{field}={message}" for field, message in sorted(merged_errors.items()))
            raise CommandError(f"{table_key} payload validation failed: {rendered}")

    def _resolve_tenant(self, tenant_id: Any, tenant_code: Any) -> dict[str, Any]:
        parsed_tenant_id = int(tenant_id) if tenant_id not in (None, "") else None
        normalized_code = str(tenant_code or "").strip().upper()
        try:
            with connection.cursor() as cursor:
                if parsed_tenant_id is not None:
                    cursor.execute(
                        """
                        SELECT tenant_id, tenant_code, tenant_name, tenant_type
                        FROM tenant
                        WHERE tenant_id = %s AND COALESCE(status_code, 'A') = 'A'
                        LIMIT 1
                        """,
                        [parsed_tenant_id],
                    )
                    row = cursor.fetchone()
                else:
                    cursor.execute(
                        """
                        SELECT tenant_id, tenant_code, tenant_name, tenant_type
                        FROM tenant
                        WHERE UPPER(COALESCE(tenant_code, '')) = %s AND COALESCE(status_code, 'A') = 'A'
                        LIMIT 1
                        """,
                        [normalized_code],
                    )
                    row = cursor.fetchone()
        except DatabaseError as exc:
            raise CommandError("Unable to resolve the target tenant.") from exc

        if not row:
            raise CommandError("Target tenant does not exist or is inactive.")
        resolved_code = str(row[1] or "").strip()
        if self._is_odpem_tenant_code(resolved_code):
            raise CommandError("Frontend test data must target a non-ODPEM tenant.")
        return {
            "tenant_id": int(row[0]),
            "tenant_code": resolved_code,
            "tenant_name": str(row[2] or "").strip(),
            "tenant_type": str(row[3] or "").strip(),
        }

    def _resolve_custodian(self, custodian_id: int) -> None:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT custodian_id
                    FROM custodian
                    WHERE custodian_id = %s
                    LIMIT 1
                    """,
                    [custodian_id],
                )
                row = cursor.fetchone()
        except DatabaseError as exc:
            raise CommandError("Unable to resolve the target custodian.") from exc
        if not row:
            raise CommandError(f"Custodian {custodian_id} does not exist.")

    def _fetch_warehouse_by_name(self, warehouse_name: str) -> dict[str, Any] | None:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT warehouse_id, warehouse_name, tenant_id, status_code, warehouse_type
                    FROM warehouse
                    WHERE UPPER(COALESCE(warehouse_name, '')) = %s
                    LIMIT 1
                    """,
                    [warehouse_name.upper()],
                )
                row = cursor.fetchone()
        except DatabaseError as exc:
            raise CommandError("Unable to inspect existing warehouse state.") from exc
        if not row:
            return None
        return {
            "warehouse_id": int(row[0]),
            "warehouse_name": str(row[1] or "").strip(),
            "tenant_id": int(row[2]) if row[2] is not None else None,
            "status_code": str(row[3] or "").strip(),
            "warehouse_type": str(row[4] or "").strip(),
        }

    def _fetch_agency_by_name(self, agency_name: str) -> dict[str, Any] | None:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT agency_id, agency_name, warehouse_id, status_code, agency_type
                    FROM agency
                    WHERE UPPER(COALESCE(agency_name, '')) = %s
                    LIMIT 1
                    """,
                    [agency_name.upper()],
                )
                row = cursor.fetchone()
        except DatabaseError as exc:
            raise CommandError("Unable to inspect existing agency state.") from exc
        if not row:
            return None
        return {
            "agency_id": int(row[0]),
            "agency_name": str(row[1] or "").strip(),
            "warehouse_id": int(row[2]) if row[2] is not None else None,
            "status_code": str(row[3] or "").strip(),
            "agency_type": str(row[4] or "").strip(),
        }

    def _validate_existing_warehouse(self, record: dict[str, Any], *, target_tenant_id: int) -> None:
        if record["tenant_id"] != target_tenant_id:
            raise CommandError(
                f"Warehouse {record['warehouse_name']!r} already exists under tenant {record['tenant_id']}, not {target_tenant_id}."
            )
        if str(record["status_code"] or "").upper() != "A":
            raise CommandError(f"Warehouse {record['warehouse_name']!r} already exists but is not active.")
        if str(record["warehouse_type"] or "").upper() != "MAIN-HUB":
            raise CommandError(f"Warehouse {record['warehouse_name']!r} already exists but is not a MAIN-HUB.")

    def _validate_existing_agency(self, record: dict[str, Any], *, expected_warehouse_id: int) -> None:
        if record["warehouse_id"] != expected_warehouse_id:
            raise CommandError(
                f"Agency {record['agency_name']!r} already exists on warehouse {record['warehouse_id']}, not {expected_warehouse_id}."
            )
        if str(record["status_code"] or "").upper() != "A":
            raise CommandError(f"Agency {record['agency_name']!r} already exists but is not active.")
        if str(record["agency_type"] or "").upper() != "DISTRIBUTOR":
            raise CommandError(f"Agency {record['agency_name']!r} already exists but is not a DISTRIBUTOR.")

    def _is_odpem_tenant_code(self, value: object) -> bool:
        normalized = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
        while "__" in normalized:
            normalized = normalized.replace("__", "_")
        return bool(normalized) and (normalized.startswith("ODPEM") or normalized == "OFFICE_OF_DISASTER_P")
