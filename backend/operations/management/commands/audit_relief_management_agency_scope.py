from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection
from django.utils import timezone


_ODPEM_CODES = {"OFFICE_OF_DISASTER_P"}


def _normalize_token(value: object) -> str:
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text


def _is_odpem_tenant_code(value: object) -> bool:
    normalized = _normalize_token(value)
    return bool(normalized) and (normalized in _ODPEM_CODES or normalized.startswith("ODPEM"))


@dataclass(frozen=True)
class AgencyScopeAuditRow:
    agency_id: int
    agency_name: str
    agency_type: str | None
    agency_status_code: str | None
    warehouse_id: int | None
    warehouse_name: str | None
    warehouse_status_code: str | None
    tenant_id: int | None
    tenant_code: str | None
    tenant_name: str | None
    tenant_type: str | None
    resolution_status: str
    resolution_reason: str

    @property
    def is_ready_for_request_creation(self) -> bool:
        return self.resolution_status == "READY_NON_ODPEM"


class Command(BaseCommand):
    help = (
        "Audit active agency scope resolution for Relief Management request creation. "
        "Shows which agencies resolve to non-ODPEM tenants and exports remediation-ready JSON when requested."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--json-out",
            type=str,
            default=None,
            help="Optional path to write the full audit payload as JSON.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Maximum number of non-ready agencies to print to stdout. Defaults to 20.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        json_out = options.get("json_out")
        limit = max(int(options.get("limit") or 20), 0)

        rows = self._fetch_rows()
        summary = self._build_summary(rows)
        payload = {
            "generated_at": timezone.now().isoformat(),
            "summary": summary,
            "agencies": [asdict(row) for row in rows],
        }

        self.stdout.write("Relief Management agency scope audit:")
        self.stdout.write(f"- active agencies: {summary['active_agencies']}")
        self.stdout.write(f"- ready non-ODPEM agencies: {summary['ready_non_odpem_agencies']}")
        self.stdout.write(f"- ODPEM-owned agencies: {summary['odpem_owned_agencies']}")
        self.stdout.write(f"- unresolved agencies: {summary['unresolved_agencies']}")

        non_ready_rows = [row for row in rows if not row.is_ready_for_request_creation]
        if non_ready_rows and limit:
            self.stdout.write("Non-ready agencies:")
            for row in non_ready_rows[:limit]:
                warehouse_fragment = f"warehouse={row.warehouse_id}" if row.warehouse_id is not None else "warehouse=none"
                tenant_fragment = f"tenant={row.tenant_code or row.tenant_id}" if row.tenant_id is not None else "tenant=none"
                self.stdout.write(
                    f"  - agency_id={row.agency_id} name={row.agency_name!r} "
                    f"status={row.resolution_status} {warehouse_fragment} {tenant_fragment} "
                    f"reason={row.resolution_reason}"
                )
            if len(non_ready_rows) > limit:
                self.stdout.write(f"  - ... {len(non_ready_rows) - limit} additional non-ready agencies omitted")

        if json_out:
            target = Path(str(json_out)).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Wrote JSON audit to {target.resolve()}"))

        if summary["ready_non_odpem_agencies"] == 0:
            raise CommandError(
                "No non-ODPEM beneficiary agencies are ready for live Relief Management request creation."
            )

    def _fetch_rows(self) -> list[AgencyScopeAuditRow]:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        a.agency_id,
                        COALESCE(a.agency_name, '') AS agency_name,
                        NULLIF(TRIM(COALESCE(a.agency_type, '')), '') AS agency_type,
                        NULLIF(TRIM(COALESCE(a.status_code, '')), '') AS agency_status_code,
                        a.warehouse_id,
                        NULLIF(TRIM(COALESCE(w.warehouse_name, '')), '') AS warehouse_name,
                        NULLIF(TRIM(COALESCE(w.status_code, '')), '') AS warehouse_status_code,
                        t.tenant_id,
                        NULLIF(TRIM(COALESCE(t.tenant_code, '')), '') AS tenant_code,
                        NULLIF(TRIM(COALESCE(t.tenant_name, '')), '') AS tenant_name,
                        NULLIF(TRIM(COALESCE(t.tenant_type, '')), '') AS tenant_type
                    FROM agency a
                    LEFT JOIN warehouse w ON w.warehouse_id = a.warehouse_id
                    LEFT JOIN tenant t ON t.tenant_id = w.tenant_id
                    WHERE COALESCE(a.status_code, 'A') = 'A'
                    ORDER BY UPPER(COALESCE(a.agency_name, '')), a.agency_id
                    """
                )
                raw_rows = cursor.fetchall()
        except DatabaseError as exc:
            raise CommandError("Unable to audit agency scope readiness from agency/warehouse/tenant tables.") from exc

        return [
            AgencyScopeAuditRow(
                agency_id=int(row[0]),
                agency_name=str(row[1] or "").strip() or f"Agency {int(row[0])}",
                agency_type=str(row[2] or "").strip() or None,
                agency_status_code=str(row[3] or "").strip() or None,
                warehouse_id=int(row[4]) if row[4] is not None else None,
                warehouse_name=str(row[5] or "").strip() or None,
                warehouse_status_code=str(row[6] or "").strip() or None,
                tenant_id=int(row[7]) if row[7] is not None else None,
                tenant_code=str(row[8] or "").strip() or None,
                tenant_name=str(row[9] or "").strip() or None,
                tenant_type=str(row[10] or "").strip() or None,
                resolution_status=self._resolution_status(
                    warehouse_id=row[4],
                    warehouse_status_code=row[6],
                    tenant_id=row[7],
                    tenant_code=row[8],
                ),
                resolution_reason=self._resolution_reason(
                    warehouse_id=row[4],
                    warehouse_status_code=row[6],
                    tenant_id=row[7],
                    tenant_code=row[8],
                ),
            )
            for row in raw_rows
        ]

    def _resolution_status(
        self,
        *,
        warehouse_id: object,
        warehouse_status_code: object,
        tenant_id: object,
        tenant_code: object,
    ) -> str:
        if warehouse_id is None:
            return "UNRESOLVED_NO_WAREHOUSE"
        warehouse_status = str(warehouse_status_code or "").strip().upper()
        if warehouse_status and warehouse_status != "A":
            return "UNRESOLVED_INACTIVE_WAREHOUSE"
        if tenant_id is None:
            return "UNRESOLVED_NO_TENANT"
        if _is_odpem_tenant_code(tenant_code):
            return "ODPEM_ONLY"
        return "READY_NON_ODPEM"

    def _resolution_reason(
        self,
        *,
        warehouse_id: object,
        warehouse_status_code: object,
        tenant_id: object,
        tenant_code: object,
    ) -> str:
        if warehouse_id is None:
            return "Agency is not linked to a warehouse."
        warehouse_status = str(warehouse_status_code or "").strip().upper()
        if warehouse_status and warehouse_status != "A":
            return "Agency points to an inactive warehouse."
        if tenant_id is None:
            return "Agency warehouse does not resolve to a tenant owner."
        if _is_odpem_tenant_code(tenant_code):
            return "Agency resolves only to an ODPEM-owned tenant."
        return "Agency resolves to a non-ODPEM tenant and is ready."

    def _build_summary(self, rows: list[AgencyScopeAuditRow]) -> dict[str, int]:
        return {
            "active_agencies": len(rows),
            "ready_non_odpem_agencies": sum(1 for row in rows if row.resolution_status == "READY_NON_ODPEM"),
            "odpem_owned_agencies": sum(1 for row in rows if row.resolution_status == "ODPEM_ONLY"),
            "unresolved_agencies": sum(1 for row in rows if row.resolution_status.startswith("UNRESOLVED_")),
        }
