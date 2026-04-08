from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence
import logging
import os
import re

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.db.models import F
from django.utils import timezone

from replenishment.legacy_models import Item
from replenishment.models import NeedsList, NeedsListItem
from replenishment.services import approval as approval_service
from replenishment.services import data_access

logger = logging.getLogger(__name__)

_CRITICALITY_RANK = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}
_ALLOCATION_OVERRIDE_SUPERVISOR_ROLES = (
    set(approval_service.LOGISTICS_MANAGER_APPROVER_ROLES)
    | set(approval_service.SENIOR_DIRECTOR_APPROVER_ROLES)
    | set(approval_service.DIRECTOR_PEOD_APPROVER_ROLES)
)

STATUS_APPROVED = 2
STATUS_SUBMITTED = 3
STATUS_PART_FILLED = 5
STATUS_FILLED = 7
_INT_ID_SEQUENCE_TABLE = "legacy_int_id_sequence"


class AllocationDispatchError(Exception):
    code = "allocation_dispatch_error"

    def __init__(self, message: str, code: str | None = None):
        self.message = message
        if code:
            self.code = code
        super().__init__(message)


class OptimisticLockError(AllocationDispatchError):
    code = "optimistic_lock_mismatch"


class ReservationError(AllocationDispatchError):
    code = "reservation_error"


class OverrideApprovalError(AllocationDispatchError):
    code = "override_approval_error"


class DispatchError(AllocationDispatchError):
    code = "dispatch_error"


@dataclass(frozen=True)
class LegacyWorkflowContext:
    needs_list_id: int
    reliefrqst_id: int | None = None
    reliefpkg_id: int | None = None
    agency_id: int | None = None
    destination_warehouse_id: int | None = None
    event_id: int | None = None
    submitted_by: str | None = None
    needs_list_no: str | None = None
    transport_mode: str | None = None
    urgency_ind: str | None = None
    request_notes: str | None = None
    package_comments: str | None = None


@dataclass(frozen=True)
class AllocationSelection:
    item_id: int
    quantity: Decimal
    inventory_id: int | None = None
    batch_id: int | None = None
    source_type: str = "ON_HAND"
    source_record_id: int | None = None
    uom_code: str | None = None
    needs_list_item_id: int | None = None
    override_reason_code: str | None = None
    override_note: str | None = None


def _schema_name() -> str:
    configured = os.getenv("DMIS_DB_SCHEMA")
    if configured is not None:
        configured = configured.strip()
        if not configured:
            return "public"
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", configured):
            return configured
        raise ValueError(
            f"Invalid DMIS_DB_SCHEMA value {configured!r}. Expected a SQL identifier such as 'public'."
        )
    return "public"


def _qualified_table(table_name: str) -> str:
    if connection.vendor == "postgresql":
        schema = connection.ops.quote_name(_schema_name())
        return f"{schema}.{connection.ops.quote_name(table_name)}"
    return connection.ops.quote_name(table_name)


def _fetch_rows(sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(sql, list(params or []))
        columns = [col[0] for col in cursor.description or []]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _execute(sql: str, params: Sequence[Any] | None = None) -> int:
    with connection.cursor() as cursor:
        cursor.execute(sql, list(params or []))
        return cursor.rowcount


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None or value == "":
        return default
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _quantize_qty(value: Any) -> Decimal:
    return _decimal(value).quantize(Decimal("0.0001"))


def _request_completion_status(reliefrqst_id: int) -> int:
    rows = _fetch_rows(
        f"""
        SELECT request_qty, issue_qty
        FROM {_qualified_table("reliefrqst_item")}
        WHERE reliefrqst_id = %s
        """,
        [reliefrqst_id],
    )
    if rows and all(_quantize_qty(row["issue_qty"]) >= _quantize_qty(row["request_qty"]) for row in rows):
        return STATUS_FILLED
    return STATUS_PART_FILLED


def _as_iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _criticality_rank(value: Any) -> int:
    normalized = str(value or "NORMAL").strip().upper()
    return _CRITICALITY_RANK.get(normalized, _CRITICALITY_RANK["NORMAL"])


def _read_value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _load_needs_list(needs_list_id: int) -> NeedsList:
    try:
        return NeedsList.objects.get(needs_list_id=needs_list_id)
    except NeedsList.DoesNotExist as exc:
        raise AllocationDispatchError(
            f"Needs list {needs_list_id} not found.", code="needs_list_not_found"
        ) from exc


def _load_needs_list_items(needs_list_id: int) -> list[NeedsListItem]:
    return list(
        NeedsListItem.objects.filter(needs_list_id=needs_list_id).order_by("item_id")
    )


def _normalize_urgency_ind(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    if normalized not in {"C", "H", "M", "L"}:
        raise AllocationDispatchError(
            "urgency_ind is required and must be one of C, H, M, or L.",
            code="urgency_ind_invalid",
        )
    return normalized


def _next_int_id(table_name: str, column_name: str) -> int:
    qualified_table = _qualified_table(table_name)
    quoted_column = connection.ops.quote_name(column_name)
    if connection.vendor == "postgresql":
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                    [table_name, column_name],
                )
                cursor.execute(
                    f"SELECT COALESCE(MAX({quoted_column}), 0) + 1 AS next_id FROM {qualified_table}"
                )
                row = cursor.fetchone()
                return int(row[0]) if row else 1

    sequence_table = _qualified_table(_INT_ID_SEQUENCE_TABLE)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {sequence_table} (
                    table_name VARCHAR(128) NOT NULL,
                    column_name VARCHAR(128) NOT NULL,
                    last_value BIGINT NOT NULL,
                    PRIMARY KEY (table_name, column_name)
                )
                """
            )
            cursor.execute(
                f"SELECT COALESCE(MAX({quoted_column}), 0) AS current_max FROM {qualified_table}"
            )
            row = cursor.fetchone()
            current_max = int(row[0]) if row and row[0] is not None else 0

            cursor.execute(
                f"""
                UPDATE {sequence_table}
                SET last_value = CASE
                    WHEN last_value <= %s THEN %s
                    ELSE last_value + 1
                END
                WHERE table_name = %s
                  AND column_name = %s
                """,
                [current_max, current_max + 1, table_name, column_name],
            )
            if cursor.rowcount != 1:
                try:
                    with transaction.atomic():
                        cursor.execute(
                            f"""
                            INSERT INTO {sequence_table} (table_name, column_name, last_value)
                            VALUES (%s, %s, %s)
                            """,
                            [table_name, column_name, current_max + 1],
                        )
                    return current_max + 1
                except IntegrityError:
                    cursor.execute(
                        f"""
                        UPDATE {sequence_table}
                        SET last_value = CASE
                            WHEN last_value <= %s THEN %s
                            ELSE last_value + 1
                        END
                        WHERE table_name = %s
                          AND column_name = %s
                        """,
                        [current_max, current_max + 1, table_name, column_name],
                    )

            cursor.execute(
                f"""
                SELECT last_value
                FROM {sequence_table}
                WHERE table_name = %s
                  AND column_name = %s
                """,
                [table_name, column_name],
            )
            row = cursor.fetchone()
            return int(row[0]) if row and row[0] is not None else current_max + 1


def _tracking_no(prefix: str, numeric_id: int) -> str:
    return f"{prefix}{int(numeric_id):05d}"


def _upsert_request_items(
    *,
    reliefrqst_id: int,
    needs_list_items: Sequence[NeedsListItem],
    actor_user_id: str,
    urgency_ind: str,
) -> None:
    table_name = _qualified_table("reliefrqst_item")
    now = timezone.now()
    for needs_item in needs_list_items:
        request_qty = max(
            Decimal("0"),
            _quantize_qty(needs_item.required_qty) - _quantize_qty(needs_item.fulfilled_qty),
        )
        required_by_date = now.date() if urgency_ind in {"H", "C"} else None
        request_reason = None
        if urgency_ind == "H":
            request_reason = "AUTO-GENERATED HIGH URGENCY NEEDS LIST REQUEST"
        updated = _execute(
            f"""
            UPDATE {table_name}
            SET request_qty = %s,
                urgency_ind = %s,
                rqst_reason_desc = %s,
                required_by_date = %s,
                version_nbr = version_nbr + 1
            WHERE reliefrqst_id = %s
              AND item_id = %s
            """,
            [
                request_qty,
                urgency_ind,
                request_reason,
                required_by_date,
                reliefrqst_id,
                needs_item.item_id,
            ],
        )
        if updated:
            continue
        _execute(
            f"""
            INSERT INTO {table_name}
                (reliefrqst_id, item_id, request_qty, issue_qty, urgency_ind,
                 rqst_reason_desc, required_by_date, status_code, version_nbr)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                reliefrqst_id,
                needs_item.item_id,
                request_qty,
                Decimal("0"),
                urgency_ind,
                request_reason,
                required_by_date,
                "R",
                1,
            ],
        )


def _request_review_metadata(
    needs_list: NeedsList | Mapping[str, Any],
    *,
    actor_user_id: str,
) -> tuple[str, datetime]:
    review_by_id = str(_read_value(needs_list, "approved_by") or actor_user_id or "").strip()
    review_dtime = _read_value(needs_list, "approved_at") or timezone.now()
    return review_by_id or actor_user_id, review_dtime


def _ensure_legacy_request_package(
    context: LegacyWorkflowContext,
    *,
    needs_list: NeedsList,
    needs_list_items: Sequence[NeedsListItem],
    actor_user_id: str,
) -> tuple[Any, Any]:
    from replenishment.legacy_models import ReliefPkg, ReliefRqst

    if context.reliefrqst_id is not None and context.reliefpkg_id is not None:
        request = ReliefRqst.objects.select_for_update().get(reliefrqst_id=context.reliefrqst_id)
        package = ReliefPkg.objects.select_for_update().get(reliefpkg_id=context.reliefpkg_id)
        _upsert_request_items(
            reliefrqst_id=int(request.reliefrqst_id),
            needs_list_items=needs_list_items,
            actor_user_id=actor_user_id,
            urgency_ind=_normalize_urgency_ind(context.urgency_ind or request.urgency_ind),
        )
        return request, package

    if context.agency_id is None:
        raise AllocationDispatchError(
            "agency_id is required when committing the first formal allocation.",
            code="agency_id_required",
        )

    urgency_ind = _normalize_urgency_ind(context.urgency_ind)
    request_id = _next_int_id("reliefrqst", "reliefrqst_id")
    package_id = _next_int_id("reliefpkg", "reliefpkg_id")
    now = timezone.now()
    review_by_id, review_dtime = _request_review_metadata(
        needs_list,
        actor_user_id=actor_user_id,
    )
    request = ReliefRqst.objects.create(
        reliefrqst_id=request_id,
        agency_id=int(context.agency_id),
        request_date=now.date(),
        tracking_no=_tracking_no("RQ", request_id),
        eligible_event_id=int(context.event_id or needs_list.event_id),
        urgency_ind=urgency_ind,
        status_code=2,
        rqst_notes_text=context.request_notes,
        create_by_id=actor_user_id,
        create_dtime=now,
        review_by_id=review_by_id,
        review_dtime=review_dtime,
        version_nbr=1,
    )
    _upsert_request_items(
        reliefrqst_id=request_id,
        needs_list_items=needs_list_items,
        actor_user_id=actor_user_id,
        urgency_ind=urgency_ind,
    )
    package = ReliefPkg.objects.create(
        reliefpkg_id=package_id,
        agency_id=int(context.agency_id),
        tracking_no=_tracking_no("PK", package_id),
        eligible_event_id=int(context.event_id or needs_list.event_id),
        to_inventory_id=int(context.destination_warehouse_id or needs_list.warehouse_id),
        reliefrqst_id=request_id,
        start_date=now.date(),
        transport_mode=context.transport_mode,
        comments_text=context.package_comments,
        status_code="A",
        create_by_id=actor_user_id,
        create_dtime=now,
        update_by_id=actor_user_id,
        update_dtime=now,
        version_nbr=1,
    )
    return request, package


def _normalize_context(context: LegacyWorkflowContext | Mapping[str, Any]) -> LegacyWorkflowContext:
    if isinstance(context, LegacyWorkflowContext):
        return context
    return LegacyWorkflowContext(
        needs_list_id=int(context["needs_list_id"]),
        reliefrqst_id=(
            int(context["reliefrqst_id"]) if context.get("reliefrqst_id") not in (None, "") else None
        ),
        reliefpkg_id=(
            int(context["reliefpkg_id"]) if context.get("reliefpkg_id") not in (None, "") else None
        ),
        agency_id=(
            int(context["agency_id"]) if context.get("agency_id") not in (None, "") else None
        ),
        destination_warehouse_id=(
            int(context["destination_warehouse_id"])
            if context.get("destination_warehouse_id") not in (None, "")
            else None
        ),
        event_id=int(context["event_id"]) if context.get("event_id") not in (None, "") else None,
        submitted_by=context.get("submitted_by"),
        needs_list_no=context.get("needs_list_no"),
        transport_mode=context.get("transport_mode"),
        urgency_ind=(
            str(context.get("urgency_ind") or "").strip().upper() or None
        ),
        request_notes=(
            str(context.get("request_notes") or context.get("rqst_notes_text") or "").strip() or None
        ),
        package_comments=(
            str(context.get("package_comments") or context.get("comments_text") or "").strip() or None
        ),
    )


def _selection_from_mapping(value: Mapping[str, Any] | AllocationSelection) -> AllocationSelection:
    if isinstance(value, AllocationSelection):
        return value
    quantity = value.get("quantity", value.get("allocated_qty", value.get("item_qty")))
    source_type = str(value.get("source_type") or "ON_HAND").strip().upper() or "ON_HAND"
    return AllocationSelection(
        item_id=int(value["item_id"]),
        quantity=_quantize_qty(quantity),
        inventory_id=(
            int(value["inventory_id"])
            if value.get("inventory_id") not in (None, "")
            else None
        ),
        batch_id=int(value["batch_id"]) if value.get("batch_id") not in (None, "") else None,
        source_type=source_type,
        source_record_id=(
            int(value["source_record_id"])
            if value.get("source_record_id") not in (None, "")
            else None
        ),
        uom_code=value.get("uom_code"),
        needs_list_item_id=(
            int(value["needs_list_item_id"])
            if value.get("needs_list_item_id") not in (None, "")
            else None
        ),
        override_reason_code=value.get("override_reason_code"),
        override_note=value.get("override_note"),
    )


def _group_plan_rows(rows: Sequence[Mapping[str, Any] | AllocationSelection]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        selection = _selection_from_mapping(row)
        key = (
            selection.item_id,
            selection.inventory_id,
            selection.batch_id,
            selection.source_type,
            selection.source_record_id,
            selection.uom_code,
        )
        grouped.setdefault(
            key,
            {
                "item_id": selection.item_id,
                "inventory_id": selection.inventory_id,
                "batch_id": selection.batch_id,
                "source_type": selection.source_type,
                "source_record_id": selection.source_record_id,
                "uom_code": selection.uom_code,
                "quantity": Decimal("0"),
            },
        )
        grouped[key]["quantity"] = _quantize_qty(grouped[key]["quantity"]) + _quantize_qty(
            selection.quantity
        )
    return list(grouped.values())


def _build_batch_source_maps(
    warehouse_id: int, item_id: int
) -> tuple[dict[tuple[int, int, str], int], dict[tuple[int, int, int], int]]:
    donation_rows = _fetch_rows(
        f"""
        SELECT inventory_id, item_id, batch_no, MIN(donation_id) AS source_id
        FROM {_qualified_table("dnintake_item")}
        WHERE inventory_id = %s
          AND item_id = %s
          AND UPPER(COALESCE(status_code, '')) = 'V'
        GROUP BY inventory_id, item_id, batch_no
        """,
        [warehouse_id, item_id],
    )
    transfer_rows = _fetch_rows(
        f"""
        SELECT ti.inventory_id, ti.item_id, ti.batch_id, MIN(ti.transfer_id) AS source_id
        FROM {_qualified_table("transfer_item")} ti
        JOIN {_qualified_table("transfer")} t ON t.transfer_id = ti.transfer_id
        WHERE ti.inventory_id = %s
          AND ti.item_id = %s
          AND UPPER(COALESCE(t.status_code, '')) IN ('C', 'D', 'P', 'V')
        GROUP BY ti.inventory_id, ti.item_id, ti.batch_id
        """,
        [warehouse_id, item_id],
    )
    donation_map = {
        (int(row["inventory_id"]), int(row["item_id"]), str(row["batch_no"] or "")): int(
            row["source_id"]
        )
        for row in donation_rows
    }
    transfer_map = {
        (int(row["inventory_id"]), int(row["item_id"]), int(row["batch_id"])): int(row["source_id"])
        for row in transfer_rows
    }
    return donation_map, transfer_map


def _fetch_batch_candidates(
    warehouse_id: int,
    item_id: int,
    *,
    as_of_date: date | None = None,
) -> list[dict[str, Any]]:
    if as_of_date is None:
        as_of = timezone.now()
    else:
        as_of = datetime.combine(as_of_date, datetime.max.time())
        if timezone.is_naive(as_of):
            as_of = timezone.make_aware(as_of, timezone.get_current_timezone())
    active_status = str(getattr(settings, "NEEDS_INVENTORY_ACTIVE_STATUS", "A")).upper()
    rows = _fetch_rows(
        f"""
        SELECT
            ib.batch_id,
            ib.inventory_id,
            ib.item_id,
            ib.batch_no,
            ib.batch_date,
            ib.expiry_date,
            ib.usable_qty,
            ib.reserved_qty,
            ib.uom_code,
            ib.status_code,
            ib.update_dtime,
            i.can_expire_flag,
            i.issuance_order,
            i.item_code,
            i.item_name,
            w.warehouse_name
        FROM {_qualified_table("itembatch")} ib
        JOIN {_qualified_table("inventory")} inv
          ON inv.inventory_id = ib.inventory_id AND inv.item_id = ib.item_id
        JOIN {_qualified_table("item")} i
          ON i.item_id = ib.item_id
        JOIN {_qualified_table("warehouse")} w
          ON w.warehouse_id = ib.inventory_id
        WHERE ib.inventory_id = %s
          AND ib.item_id = %s
          AND UPPER(COALESCE(ib.status_code, '')) = %s
          AND UPPER(COALESCE(inv.status_code, '')) = %s
          AND ib.update_dtime <= %s
          AND inv.update_dtime <= %s
        """,
        [warehouse_id, item_id, active_status, active_status, as_of, as_of],
    )
    if not rows:
        return []

    donation_map, transfer_map = _build_batch_source_maps(warehouse_id, item_id)
    candidates: list[dict[str, Any]] = []
    for row in rows:
        available = _quantize_qty(row["usable_qty"]) - _quantize_qty(row["reserved_qty"])
        if available <= 0:
            continue
        batch_no = str(row.get("batch_no") or "")
        batch_id = int(row["batch_id"])
        inventory_id = int(row["inventory_id"])
        source_type = "ON_HAND"
        source_record_id = None
        if batch_no and (inventory_id, item_id, batch_no) in donation_map:
            source_type = "DONATION"
            source_record_id = donation_map[(inventory_id, item_id, batch_no)]
        elif (inventory_id, item_id, batch_id) in transfer_map:
            source_type = "TRANSFER"
            source_record_id = transfer_map[(inventory_id, item_id, batch_id)]

        candidates.append(
            {
                "batch_id": batch_id,
                "inventory_id": inventory_id,
                "item_id": int(row["item_id"]),
                "batch_no": batch_no or None,
                "batch_date": row.get("batch_date"),
                "expiry_date": row.get("expiry_date"),
                "usable_qty": _quantize_qty(row["usable_qty"]),
                "reserved_qty": _quantize_qty(row["reserved_qty"]),
                "available_qty": available,
                "uom_code": row.get("uom_code"),
                "source_type": source_type,
                "source_record_id": source_record_id,
                "warehouse_name": row.get("warehouse_name"),
                "can_expire_flag": bool(row.get("can_expire_flag")),
                "issuance_order": str(row.get("issuance_order") or "FIFO").upper(),
                "item_code": row.get("item_code"),
                "item_name": row.get("item_name"),
            }
        )
    return candidates


def sort_batch_candidates(
    item: Item | Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    *,
    as_of_date: date | None = None,
) -> list[dict[str, Any]]:
    can_expire = bool(_read_value(item, "can_expire_flag", False))
    issuance_order = str(_read_value(item, "issuance_order", "FIFO") or "FIFO").strip().upper()
    as_of = as_of_date or timezone.localdate()

    filtered: list[dict[str, Any]] = []
    for candidate in candidates:
        row = dict(candidate)
        available = _quantize_qty(row.get("available_qty"))
        if available <= 0:
            continue
        expiry_date = row.get("expiry_date")
        if can_expire and expiry_date and expiry_date < as_of:
            continue
        row["available_qty"] = available
        filtered.append(row)

    def _fifo_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            row.get("batch_date") or date.min,
            int(row.get("inventory_id") or 0),
            int(row.get("batch_id") or 0),
        )

    def _fefo_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            row.get("expiry_date") is None,
            row.get("expiry_date") or date.max,
            row.get("batch_date") or date.max,
            int(row.get("inventory_id") or 0),
            int(row.get("batch_id") or 0),
        )

    if can_expire and issuance_order == "FEFO":
        return sorted(filtered, key=_fefo_key)
    return sorted(filtered, key=_fifo_key)


def build_greedy_allocation_plan(
    candidates: Sequence[Mapping[str, Any]],
    requested_qty: Any,
) -> tuple[list[dict[str, Any]], Decimal]:
    remaining = _quantize_qty(requested_qty)
    plan: list[dict[str, Any]] = []
    if remaining <= 0:
        return plan, remaining

    for candidate in candidates:
        if remaining <= 0:
            break
        available = _quantize_qty(candidate.get("available_qty"))
        if available <= 0:
            continue
        allocated = min(available, remaining)
        if allocated <= 0:
            continue
        plan.append(
            {
                "item_id": int(candidate["item_id"]),
                "inventory_id": int(candidate["inventory_id"]),
                "batch_id": int(candidate["batch_id"]),
                "batch_no": candidate.get("batch_no"),
                "source_type": candidate.get("source_type") or "ON_HAND",
                "source_record_id": candidate.get("source_record_id"),
                "uom_code": candidate.get("uom_code"),
                "quantity": allocated,
            }
        )
        remaining -= allocated

    return plan, remaining


def detect_override_requirement(
    item: Item | Mapping[str, Any],
    selected_rows: Sequence[Mapping[str, Any] | AllocationSelection],
    candidates: Sequence[Mapping[str, Any]],
) -> tuple[bool, list[dict[str, Any]], list[str]]:
    normalized_selected = _group_plan_rows(selected_rows)
    selected_qty = sum((_quantize_qty(row["quantity"]) for row in normalized_selected), Decimal("0"))
    recommended, remaining = build_greedy_allocation_plan(candidates, selected_qty)
    compliance_markers: list[str] = []

    if remaining > 0:
        compliance_markers.append("insufficient_on_hand_stock")
        return True, recommended, compliance_markers

    if _group_plan_rows(recommended) != normalized_selected:
        compliance_markers.append("allocation_order_override")
        return True, recommended, compliance_markers

    if str(_read_value(item, "issuance_order", "FIFO") or "FIFO").upper() == "FEFO":
        compliance_markers.append("fefo")
    else:
        compliance_markers.append("fifo")
    return False, recommended, compliance_markers


def validate_override_approval(
    *,
    approver_user_id: str | None,
    approver_role_codes: Iterable[str] | None,
    submitter_user_id: str | None,
    needs_list_submitted_by: str | None,
) -> list[str]:
    if not approver_user_id:
        raise OverrideApprovalError(
            "Supervisor approval is required before override lines can reserve stock.",
            code="override_supervisor_missing",
        )

    approver = str(approver_user_id).strip()
    submitter = str(submitter_user_id or "").strip()
    needs_submitter = str(needs_list_submitted_by or "").strip()

    if approver and (approver == submitter or approver == needs_submitter):
        raise OverrideApprovalError(
            "No-self-approval policy prevents the submitter from approving their own override.",
            code="override_self_approval_blocked",
        )

    normalized_roles = {
        str(role).strip().upper().replace("-", "_").replace(" ", "_")
        for role in (approver_role_codes or [])
        if str(role).strip()
    }
    if not normalized_roles:
        raise OverrideApprovalError(
            "Approver role codes are required for supervisor override approval.",
            code="override_supervisor_roles_missing",
        )
    if not normalized_roles.intersection(_ALLOCATION_OVERRIDE_SUPERVISOR_ROLES):
        raise OverrideApprovalError(
            "Approver does not have an authorized supervisor role for allocation overrides.",
            code="override_supervisor_unauthorized",
        )

    return sorted(normalized_roles)


def _log_audit(
    *,
    needs_list_id: int,
    actor_user_id: str,
    action_type: str,
    needs_list_item_id: int | None = None,
    field_name: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
    reason_code: str | None = None,
    notes_text: str | None = None,
) -> None:
    from replenishment.models import NeedsListAudit

    NeedsListAudit.objects.create(
        needs_list_id=needs_list_id,
        needs_list_item_id=needs_list_item_id,
        action_type=action_type,
        field_name=field_name,
        old_value=None if old_value is None else str(old_value),
        new_value=None if new_value is None else str(new_value),
        reason_code=reason_code,
        notes_text=notes_text,
        actor_user_id=str(actor_user_id),
    )


def _load_package_rows(package_id: int) -> list[dict[str, Any]]:
    rows = _fetch_rows(
        f"""
        SELECT reliefpkg_id, fr_inventory_id, batch_id, item_id, item_qty, uom_code, reason_text, version_nbr
        FROM {_qualified_table("reliefpkg_item")}
        WHERE reliefpkg_id = %s
        ORDER BY item_id, fr_inventory_id, batch_id
        """,
        [package_id],
    )
    return rows


def _upsert_package_rows(
    *,
    package_id: int,
    plan_rows: Sequence[Mapping[str, Any]],
    actor_user_id: str,
    notes: str | None = None,
) -> None:
    _execute(
        f"DELETE FROM {_qualified_table('reliefpkg_item')} WHERE reliefpkg_id = %s",
        [package_id],
    )
    if not plan_rows:
        return
    now = timezone.now()
    for row in plan_rows:
        _execute(
            f"""
            INSERT INTO {_qualified_table("reliefpkg_item")}
                (reliefpkg_id, fr_inventory_id, batch_id, item_id, item_qty,
                 uom_code, reason_text, create_by_id, create_dtime, update_by_id,
                 update_dtime, version_nbr)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                package_id,
                row.get("inventory_id"),
                row.get("batch_id"),
                row["item_id"],
                row["quantity"],
                row.get("uom_code"),
                notes,
                actor_user_id,
                now,
                actor_user_id,
                now,
                1,
            ],
        )


def _current_package_status(package: Any) -> str:
    return str(_read_value(package, "status_code", "") or "").strip().upper()


def _package_plan_map(
    plan_rows: Sequence[Mapping[str, Any] | AllocationSelection],
) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in _group_plan_rows(plan_rows):
        grouped.setdefault(int(row["item_id"]), []).append(row)
    return grouped


def _apply_stock_delta_for_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    actor_user_id: str,
    delta_sign: int,
    update_needs_list: bool,
    needs_list_id: int | None = None,
    consume_stock: bool = False,
) -> None:
    from replenishment.legacy_models import Inventory, ItemBatch

    if delta_sign not in (-1, 1):
        raise ValueError("delta_sign must be -1 or 1")
    now = timezone.now()
    needs_list_items: dict[int, NeedsListItem] = {}
    if update_needs_list and needs_list_id is not None:
        needs_list_items = {
            item.item_id: item
            for item in NeedsListItem.objects.select_for_update().filter(needs_list_id=needs_list_id)
        }

    for row in rows:
        item_id = int(row["item_id"])
        quantity = _quantize_qty(row["quantity"])
        if quantity <= 0:
            continue
        if str(row.get("source_type") or "ON_HAND").upper() == "PROCUREMENT":
            continue
        inventory_id = int(row["inventory_id"])
        batch_id = int(row["batch_id"])

        batch = ItemBatch.objects.select_for_update().get(batch_id=batch_id)
        if int(batch.inventory_id) != inventory_id or int(batch.item_id) != item_id:
            raise DispatchError(
                f"Batch {batch_id} does not belong to inventory {inventory_id} / item {item_id}.",
                code="batch_inventory_mismatch",
            )

        inventory = Inventory.objects.select_for_update().get(
            inventory_id=inventory_id,
            item_id=item_id,
        )

        if delta_sign > 0:
            if consume_stock:
                if _quantize_qty(batch.reserved_qty) < quantity:
                    raise ReservationError(
                        f"Inconsistent reservation state for batch {batch_id}.",
                        code="reservation_drift",
                    )
                if _quantize_qty(inventory.reserved_qty) < quantity:
                    raise ReservationError(
                        f"Inconsistent inventory reservation for item {item_id}.",
                        code="reservation_drift",
                    )
                if _quantize_qty(batch.usable_qty) < quantity:
                    raise ReservationError(
                        f"Insufficient usable stock for batch {batch_id}.",
                        code="insufficient_batch_stock",
                    )
                if _quantize_qty(inventory.usable_qty) < quantity:
                    raise ReservationError(
                        f"Insufficient usable stock for item {item_id} at inventory {inventory_id}.",
                        code="insufficient_inventory_stock",
                    )
                batch.usable_qty = _quantize_qty(batch.usable_qty) - quantity
                batch.reserved_qty = _quantize_qty(batch.reserved_qty) - quantity
                inventory.usable_qty = _quantize_qty(inventory.usable_qty) - quantity
                inventory.reserved_qty = _quantize_qty(inventory.reserved_qty) - quantity
            else:
                if _quantize_qty(batch.available_qty) < quantity:
                    raise ReservationError(
                        f"Insufficient available stock for batch {batch_id}.",
                        code="insufficient_batch_stock",
                    )
                if _quantize_qty(inventory.available_qty) < quantity:
                    raise ReservationError(
                        f"Insufficient warehouse stock for item {item_id} at inventory {inventory_id}.",
                        code="insufficient_inventory_stock",
                    )
                batch.reserved_qty = _quantize_qty(batch.reserved_qty) + quantity
                inventory.reserved_qty = _quantize_qty(inventory.reserved_qty) + quantity
        else:
            if _quantize_qty(batch.reserved_qty) < quantity:
                raise ReservationError(
                    f"Inconsistent reservation state for batch {batch_id}.",
                    code="reservation_drift",
                )
            if _quantize_qty(inventory.reserved_qty) < quantity:
                raise ReservationError(
                    f"Inconsistent inventory reservation for item {item_id}.",
                    code="reservation_drift",
                )
            batch.reserved_qty = _quantize_qty(batch.reserved_qty) - quantity
            inventory.reserved_qty = _quantize_qty(inventory.reserved_qty) - quantity

        batch_updated = ItemBatch.objects.filter(
            batch_id=batch.batch_id,
            version_nbr=batch.version_nbr,
        ).update(
            usable_qty=batch.usable_qty,
            reserved_qty=batch.reserved_qty,
            update_by_id=actor_user_id,
            update_dtime=now,
            version_nbr=F("version_nbr") + 1,
        )
        if batch_updated != 1:
            raise OptimisticLockError(
                f"Batch {batch_id} changed during stock update.",
                code="batch_version_mismatch",
            )

        inventory_updated = Inventory.objects.filter(
            inventory_id=inventory.inventory_id,
            item_id=inventory.item_id,
            version_nbr=inventory.version_nbr,
        ).update(
            usable_qty=inventory.usable_qty,
            reserved_qty=inventory.reserved_qty,
            update_by_id=actor_user_id,
            update_dtime=now,
            version_nbr=F("version_nbr") + 1,
        )
        if inventory_updated != 1:
            raise OptimisticLockError(
                f"Inventory row {inventory_id}/{item_id} changed during stock update.",
                code="inventory_version_mismatch",
            )

        if update_needs_list and needs_list_id is not None and item_id in needs_list_items:
            needs_item = needs_list_items[item_id]
            if delta_sign > 0:
                needs_item.reserved_qty = _quantize_qty(needs_item.reserved_qty) + quantity
            else:
                needs_item.reserved_qty = max(
                    Decimal("0"), _quantize_qty(needs_item.reserved_qty) - quantity
                )
            needs_updated = NeedsListItem.objects.filter(
                needs_list_item_id=needs_item.needs_list_item_id,
                version_nbr=needs_item.version_nbr,
            ).update(
                reserved_qty=needs_item.reserved_qty,
                update_by_id=actor_user_id,
                update_dtime=now,
                version_nbr=F("version_nbr") + 1,
            )
            if needs_updated != 1:
                raise OptimisticLockError(
                    f"Needs list item {needs_item.needs_list_item_id} changed during stock update.",
                    code="needs_list_item_version_mismatch",
                )
            needs_item.version_nbr = int(getattr(needs_item, "version_nbr", 0) or 0) + 1
            _log_audit(
                needs_list_id=needs_list_id,
                actor_user_id=actor_user_id,
                action_type="QUANTITY_ADJUSTED",
                needs_list_item_id=needs_item.needs_list_item_id,
                field_name="reserved_qty",
                new_value=str(needs_item.reserved_qty),
                reason_code="allocation_reservation" if delta_sign > 0 else "allocation_release",
            )


def _update_needs_list_fulfillment(
    *,
    needs_list_id: int,
    actor_user_id: str,
    dispatched_rows: Sequence[Mapping[str, Any]],
) -> None:
    now = timezone.now()
    grouped_qty: dict[int, Decimal] = {}
    for row in dispatched_rows:
        grouped_qty[int(row["item_id"])] = grouped_qty.get(int(row["item_id"]), Decimal("0")) + _quantize_qty(
            row["quantity"]
        )
    if not grouped_qty:
        return
    needs_items = {
        item.item_id: item
        for item in NeedsListItem.objects.select_for_update().filter(needs_list_id=needs_list_id)
    }
    for item_id, qty in grouped_qty.items():
        needs_item = needs_items.get(item_id)
        if not needs_item:
            continue
        needs_item.fulfilled_qty = _quantize_qty(needs_item.fulfilled_qty) + qty
        needs_item.reserved_qty = max(Decimal("0"), _quantize_qty(needs_item.reserved_qty) - qty)
        remaining = max(
            Decimal("0"),
            _quantize_qty(needs_item.required_qty) - _quantize_qty(needs_item.fulfilled_qty),
        )
        needs_item.fulfillment_status = "FULFILLED" if remaining <= 0 else "PARTIAL"
        needs_updated = NeedsListItem.objects.filter(
            needs_list_item_id=needs_item.needs_list_item_id,
            version_nbr=needs_item.version_nbr,
        ).update(
            fulfilled_qty=needs_item.fulfilled_qty,
            reserved_qty=needs_item.reserved_qty,
            fulfillment_status=needs_item.fulfillment_status,
            update_by_id=actor_user_id,
            update_dtime=now,
            version_nbr=F("version_nbr") + 1,
        )
        if needs_updated != 1:
            raise OptimisticLockError(
                f"Needs list item {needs_item.needs_list_item_id} changed during fulfillment update.",
                code="needs_list_item_version_mismatch",
            )
        _log_audit(
            needs_list_id=needs_list_id,
            actor_user_id=actor_user_id,
            action_type="FULFILLED",
            needs_list_item_id=needs_item.needs_list_item_id,
            field_name="fulfilled_qty",
            new_value=str(needs_item.fulfilled_qty),
            reason_code="dispatch",
        )


def _reservation_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    summary: dict[tuple[int, int], Decimal] = {}
    for row in rows:
        key = (
            int(row["item_id"]),
            int(row["batch_id"]) if row.get("batch_id") not in (None, "") else -1,
        )
        summary[key] = summary.get(key, Decimal("0")) + _quantize_qty(row["quantity"])
    return {
        "line_count": len(rows),
        "total_qty": str(sum(summary.values(), Decimal("0")).quantize(Decimal("0.0001"))),
        "by_item_batch": [
            {
                "item_id": item_id,
                "batch_id": batch_id if batch_id != -1 else None,
                "reserved_qty": str(qty.quantize(Decimal("0.0001"))),
            }
            for (item_id, batch_id), qty in sorted(summary.items())
        ],
    }


_APPROVAL_REQUIRED_OVERRIDE_MARKERS = frozenset({"insufficient_on_hand_stock"})


def _approval_required_override_markers(markers: Sequence[str]) -> list[str]:
    return [marker for marker in markers if marker in _APPROVAL_REQUIRED_OVERRIDE_MARKERS]


def _load_package_plan_with_source_info(package_id: int) -> list[dict[str, Any]]:
    rows = _load_package_rows(package_id)
    if not rows:
        return []
    plan: list[dict[str, Any]] = []
    for row in rows:
        source_type = "ON_HAND"
        source_record_id = None
        donation_map, transfer_map = _build_batch_source_maps(
            int(row["fr_inventory_id"]), int(row["item_id"])
        )
        batch_rows = _fetch_rows(
            f"""
            SELECT ib.batch_no, i.item_code, i.item_name
            FROM {_qualified_table("itembatch")} ib
            LEFT JOIN {_qualified_table("item")} i ON i.item_id = ib.item_id
            WHERE ib.batch_id = %s
            """,
            [row["batch_id"]],
        )
        batch_info = batch_rows[0] if batch_rows else {}
        batch_no = str(batch_info.get("batch_no") or "") if batch_info else ""
        item_code = str(batch_info.get("item_code") or "") if batch_info else ""
        item_name = str(batch_info.get("item_name") or "") if batch_info else ""
        if batch_no and (int(row["fr_inventory_id"]), int(row["item_id"]), batch_no) in donation_map:
            source_type = "DONATION"
            source_record_id = donation_map[(int(row["fr_inventory_id"]), int(row["item_id"]), batch_no)]
        elif (
            int(row["fr_inventory_id"]),
            int(row["item_id"]),
            int(row["batch_id"]),
        ) in transfer_map:
            source_type = "TRANSFER"
            source_record_id = transfer_map[
                (int(row["fr_inventory_id"]), int(row["item_id"]), int(row["batch_id"]))
            ]
        plan.append(
            {
                "item_id": int(row["item_id"]),
                "inventory_id": int(row["fr_inventory_id"]),
                "batch_id": int(row["batch_id"]),
                "batch_no": batch_no or None,
                "item_code": item_code or None,
                "item_name": item_name or None,
                "quantity": _quantize_qty(row["item_qty"]),
                "uom_code": row.get("uom_code"),
                "source_type": source_type,
                "source_record_id": source_record_id,
            }
        )
    return plan


def _ensure_request_package_context(
    context: LegacyWorkflowContext,
    *,
    for_update: bool = True,
) -> tuple[Any, Any]:
    if context.reliefrqst_id is None or context.reliefpkg_id is None:
        raise AllocationDispatchError(
            "Legacy request and package ids are required for allocation dispatch operations.",
            code="legacy_context_missing",
        )
    from replenishment.legacy_models import ReliefPkg, ReliefRqst

    request_manager = ReliefRqst.objects.select_for_update() if for_update else ReliefRqst.objects
    package_manager = ReliefPkg.objects.select_for_update() if for_update else ReliefPkg.objects
    request = request_manager.get(reliefrqst_id=context.reliefrqst_id)
    package = package_manager.get(reliefpkg_id=context.reliefpkg_id)
    if int(package.reliefrqst_id) != int(request.reliefrqst_id):
        raise AllocationDispatchError(
            "Package does not belong to the supplied relief request.",
            code="request_package_mismatch",
        )
    return request, package


def _request_header_update_values(
    *,
    request: Any,
    package_status: str,
    needs_list: NeedsList | Mapping[str, Any] | None,
    actor_user_id: str,
    event_time: datetime,
) -> dict[str, Any]:
    current_review_by = getattr(request, "review_by_id", None)
    current_review_dtime = getattr(request, "review_dtime", None)
    current_action_by = getattr(request, "action_by_id", None)
    current_action_dtime = getattr(request, "action_dtime", None)
    review_by_id = current_review_by
    review_dtime = current_review_dtime
    if review_by_id in (None, "") or review_dtime is None:
        if needs_list is not None:
            review_by_id, review_dtime = _request_review_metadata(
                needs_list,
                actor_user_id=actor_user_id,
            )
        else:
            review_by_id = current_review_by or actor_user_id
            review_dtime = current_review_dtime or event_time

    if package_status in {"A", "P", "C", "V"}:
        return {
            "status_code": STATUS_SUBMITTED,
            "review_by_id": review_by_id,
            "review_dtime": review_dtime,
            "action_by_id": None,
            "action_dtime": None,
            "status_reason_desc": None,
        }
    if package_status == "D":
        return {
            "status_code": STATUS_PART_FILLED,
            "review_by_id": review_by_id,
            "review_dtime": review_dtime,
            "action_by_id": actor_user_id,
            "action_dtime": event_time,
            "status_reason_desc": None,
        }
    return {
        "status_code": getattr(request, "status_code", None),
        "review_by_id": review_by_id,
        "review_dtime": review_dtime,
        "action_by_id": current_action_by,
        "action_dtime": current_action_dtime,
        "status_reason_desc": getattr(request, "status_reason_desc", None),
    }


def _apply_package_header_updates(
    *,
    request: Any,
    package: Any,
    needs_list: NeedsList | Mapping[str, Any] | None,
    actor_user_id: str,
    status_code: str,
    transport_mode: str | None = None,
) -> None:
    from replenishment.legacy_models import ReliefPkg, ReliefRqst

    now = timezone.now()
    request_update_values = _request_header_update_values(
        request=request,
        package_status=status_code,
        needs_list=needs_list,
        actor_user_id=actor_user_id,
        event_time=now,
    )
    request_update = ReliefRqst.objects.filter(
        reliefrqst_id=request.reliefrqst_id,
        version_nbr=request.version_nbr,
    ).update(**request_update_values, version_nbr=F("version_nbr") + 1)
    if request_update != 1:
        raise OptimisticLockError(
            f"Relief request {request.reliefrqst_id} changed during allocation update.",
            code="request_version_mismatch",
        )

    package_update = ReliefPkg.objects.filter(
        reliefpkg_id=package.reliefpkg_id,
        version_nbr=package.version_nbr,
    ).update(
        status_code=status_code,
        transport_mode=transport_mode or package.transport_mode,
        update_by_id=actor_user_id,
        update_dtime=now,
        version_nbr=F("version_nbr") + 1,
    )
    if package_update != 1:
        raise OptimisticLockError(
            f"Relief package {package.reliefpkg_id} changed during allocation update.",
            code="package_version_mismatch",
        )


def sort_needs_list_items_for_allocation(
    needs_list: NeedsList | Mapping[str, Any],
    items: Sequence[NeedsListItem],
) -> list[NeedsListItem]:
    submitted_at = _read_value(needs_list, "submitted_at")
    create_dtime = _read_value(needs_list, "create_dtime")
    fallback_dt = submitted_at or create_dtime or timezone.now()

    def _item_key(item: NeedsListItem) -> tuple[Any, ...]:
        return (
            _criticality_rank(_read_value(item, "effective_criticality_level")),
            fallback_dt,
            create_dtime or fallback_dt,
            int(_read_value(item, "item_id", 0)),
        )

    return sorted(list(items), key=_item_key)


def get_allocation_options(
    needs_list_id: int,
    *,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    needs_list = _load_needs_list(needs_list_id)
    if str(needs_list.status_code or "").upper() in {"CANCELLED", "REJECTED", "SUPERSEDED"}:
        raise AllocationDispatchError(
            f"Needs list {needs_list_id} is no longer eligible for allocation.",
            code="needs_list_closed",
        )

    item_ids = list(
        NeedsListItem.objects.filter(needs_list_id=needs_list_id).values_list("item_id", flat=True)
    )
    open_scope_conflicts = (
        NeedsListItem.objects.filter(
            needs_list__warehouse_id=needs_list.warehouse_id,
            item_id__in=item_ids,
            needs_list__status_code__in=sorted(
                {"DRAFT", "PENDING_APPROVAL", "UNDER_REVIEW", "APPROVED", "IN_PROGRESS", "RETURNED"}
            ),
        )
        .exclude(needs_list_id=needs_list_id)
        .values("needs_list_id")
        .distinct()
    )
    if open_scope_conflicts.exists():
        raise AllocationDispatchError(
            "Another open needs list already overlaps the same warehouse/item scope.",
            code="overlapping_open_needs_list",
        )

    items = sort_needs_list_items_for_allocation(needs_list, _load_needs_list_items(needs_list_id))
    groups: list[dict[str, Any]] = []
    flat_candidates: list[dict[str, Any]] = []

    for needs_item in items:
        item = Item.objects.filter(item_id=needs_item.item_id).first()
        if not item:
            continue
        remaining_qty = max(
            Decimal("0"),
            _quantize_qty(needs_item.required_qty)
            - _quantize_qty(needs_item.fulfilled_qty)
            - _quantize_qty(needs_item.reserved_qty),
        )
        candidates = sort_batch_candidates(
            item,
            _fetch_batch_candidates(
                int(needs_list.warehouse_id),
                int(needs_item.item_id),
                as_of_date=as_of_date,
            ),
            as_of_date=as_of_date,
        )
        suggested_allocations, remaining_after_suggestion = build_greedy_allocation_plan(
            candidates,
            remaining_qty,
        )
        override_required, _, compliance_markers = detect_override_requirement(
            item,
            suggested_allocations,
            candidates,
        )

        group = {
            "needs_list_item_id": needs_item.needs_list_item_id,
            "item_id": needs_item.item_id,
            "item_code": getattr(item, "item_code", None),
            "item_name": getattr(item, "item_name", None),
            "criticality_level": needs_item.effective_criticality_level,
            "criticality_rank": _criticality_rank(needs_item.effective_criticality_level),
            "required_qty": str(_quantize_qty(needs_item.required_qty)),
            "fulfilled_qty": str(_quantize_qty(needs_item.fulfilled_qty)),
            "reserved_qty": str(_quantize_qty(needs_item.reserved_qty)),
            "remaining_qty": str(remaining_qty.quantize(Decimal("0.0001"))),
            "remaining_after_suggestion": str(remaining_after_suggestion.quantize(Decimal("0.0001"))),
            "item_uom_code": needs_item.uom_code,
            "can_expire_flag": bool(getattr(item, "can_expire_flag", False)),
            "issuance_order": str(getattr(item, "issuance_order", "FIFO") or "FIFO").upper(),
            "candidates": [],
            "suggested_allocations": [
                {
                    **row,
                    "quantity": str(_quantize_qty(row["quantity"])),
                }
                for row in suggested_allocations
            ],
            "compliance_markers": compliance_markers,
            "override_required": override_required,
        }
        for candidate in candidates:
            row = dict(candidate)
            row["available_qty"] = str(_quantize_qty(row["available_qty"]))
            row["usable_qty"] = str(_quantize_qty(row["usable_qty"]))
            row["reserved_qty"] = str(_quantize_qty(row["reserved_qty"]))
            row["batch_date"] = _as_iso(row.get("batch_date"))
            row["expiry_date"] = _as_iso(row.get("expiry_date"))
            row["source_type"] = str(row.get("source_type") or "ON_HAND")
            row["source_record_id"] = row.get("source_record_id")
            row["compliance_markers"] = [
                marker
                for marker in (
                    "donation_source" if row["source_type"] == "DONATION" else "",
                    "transfer_source" if row["source_type"] == "TRANSFER" else "",
                )
                if marker
            ]
            group["candidates"].append(row)
            flat_candidates.append({"item_id": needs_item.item_id, **row})
        groups.append(group)

    return {
        "needs_list": {
            "needs_list_id": needs_list.needs_list_id,
            "needs_list_no": needs_list.needs_list_no,
            "warehouse_id": needs_list.warehouse_id,
            "event_id": needs_list.event_id,
            "status_code": needs_list.status_code,
            "submitted_at": _as_iso(needs_list.submitted_at),
            "create_dtime": _as_iso(needs_list.create_dtime),
        },
        "items": groups,
        "flat_candidates": flat_candidates,
    }


def _selected_plan_for_package(package_id: int) -> list[dict[str, Any]]:
    return _group_plan_rows(_load_package_plan_with_source_info(package_id))


@transaction.atomic
def commit_allocation(
    context: LegacyWorkflowContext | Mapping[str, Any],
    selections: Sequence[Mapping[str, Any] | AllocationSelection],
    *,
    actor_user_id: str,
    expected_request_version_nbr: int | None = None,
    expected_package_version_nbr: int | None = None,
    override_reason_code: str | None = None,
    override_note: str | None = None,
    supervisor_user_id: str | None = None,
    supervisor_role_codes: Iterable[str] | None = None,
    allow_pending_override: bool = True,
) -> dict[str, Any]:
    ctx = _normalize_context(context)
    needs_list = _load_needs_list(ctx.needs_list_id)
    needs_items_list = _load_needs_list_items(needs_list.needs_list_id)
    request, package = _ensure_legacy_request_package(
        ctx,
        needs_list=needs_list,
        needs_list_items=needs_items_list,
        actor_user_id=actor_user_id,
    )
    if int(package.reliefrqst_id) != int(request.reliefrqst_id):
        raise AllocationDispatchError(
            "Package does not belong to the supplied relief request.",
            code="request_package_mismatch",
        )
    current_package_status = _current_package_status(package)
    if current_package_status in {"D", "R"}:
        raise DispatchError(
            f"Committed package cannot be modified from status '{current_package_status}'.",
            code="package_already_dispatched",
        )

    if expected_request_version_nbr is not None and int(request.version_nbr) != int(
        expected_request_version_nbr
    ):
        raise OptimisticLockError(
            "Relief request changed before allocation commit.",
            code="request_version_mismatch",
        )
    if expected_package_version_nbr is not None and int(package.version_nbr) != int(
        expected_package_version_nbr
    ):
        raise OptimisticLockError(
            "Relief package changed before allocation commit.",
            code="package_version_mismatch",
        )

    selected_rows = _group_plan_rows(selections)
    if not selected_rows:
        raise AllocationDispatchError(
            "At least one allocation selection is required.",
            code="allocation_selection_missing",
        )

    needs_items = {item.item_id: item for item in needs_items_list}
    selected_item_ids = {int(row["item_id"]) for row in selected_rows}
    missing_item_ids = sorted(selected_item_ids - set(needs_items))
    if missing_item_ids:
        raise AllocationDispatchError(
            f"Allocation contains item(s) not present in the needs list: {', '.join(str(item_id) for item_id in missing_item_ids)}.",
            code="allocation_item_not_in_needs",
        )
    candidate_by_item: dict[int, list[dict[str, Any]]] = {}
    for item_id in needs_items:
        item = Item.objects.filter(item_id=item_id).first() or {"issuance_order": "FIFO"}
        candidate_by_item[item_id] = sort_batch_candidates(
            item,
            _fetch_batch_candidates(int(needs_list.warehouse_id), int(item_id)),
        )

    override_markers: list[str] = []
    for item_id, rows in _package_plan_map(selected_rows).items():
        candidates = candidate_by_item.get(item_id, [])
        target_qty = sum((_quantize_qty(row["quantity"]) for row in rows), Decimal("0"))
        recommended, remaining = build_greedy_allocation_plan(candidates, target_qty)
        if remaining > 0:
            override_markers.append("insufficient_on_hand_stock")
        if _group_plan_rows(recommended) != rows:
            override_markers.append("allocation_order_override")
    override_markers = list(dict.fromkeys(override_markers))
    approval_markers = _approval_required_override_markers(override_markers)
    override_required = bool(approval_markers)

    if override_markers:
        if not override_reason_code:
            raise OverrideApprovalError(
                "Override reason code is required for non-compliant allocations.",
                code="override_details_missing",
            )
    if override_required:
        if not override_note:
            raise OverrideApprovalError(
                "Override note is required for allocations awaiting approval.",
                code="override_details_missing",
            )
        if not allow_pending_override:
            validate_override_approval(
                approver_user_id=supervisor_user_id,
                approver_role_codes=supervisor_role_codes,
                submitter_user_id=ctx.submitted_by or actor_user_id,
                needs_list_submitted_by=needs_list.submitted_by,
            )

    current_reserved = current_package_status in {
        "P",
        "C",
        "V",
    }
    old_rows = _selected_plan_for_package(package.reliefpkg_id) if current_reserved else []
    if old_rows:
        _apply_stock_delta_for_rows(
            old_rows,
            actor_user_id=actor_user_id,
            delta_sign=-1,
            update_needs_list=True,
            needs_list_id=needs_list.needs_list_id,
        )

    _upsert_package_rows(
        package_id=package.reliefpkg_id,
        plan_rows=selected_rows,
        actor_user_id=actor_user_id,
        notes=(override_reason_code or override_note) or f"NL:{needs_list.needs_list_id}:{needs_list.needs_list_no}",
    )

    if not override_required or not allow_pending_override:
        _apply_stock_delta_for_rows(
            selected_rows,
            actor_user_id=actor_user_id,
            delta_sign=1,
            update_needs_list=True,
            needs_list_id=needs_list.needs_list_id,
        )
        package_status = "P"
        audit_action = (
            "ALLOCATION_OVERRIDE_APPROVED" if override_required else "ALLOCATION_COMMITTED"
        )
    else:
        package_status = "A"
        audit_action = "ALLOCATION_OVERRIDE_SUBMITTED"

    _apply_package_header_updates(
        request=request,
        package=package,
        needs_list=needs_list,
        actor_user_id=actor_user_id,
        status_code=package_status,
        transport_mode=ctx.transport_mode,
    )

    _log_audit(
        needs_list_id=needs_list.needs_list_id,
        actor_user_id=actor_user_id,
        action_type=audit_action,
        reason_code=override_reason_code if override_required else "allocation_commit",
        notes_text=override_note,
    )

    return {
        "status": (
            "PENDING_OVERRIDE_APPROVAL"
            if override_required and allow_pending_override
            else "COMMITTED"
        ),
        "needs_list_id": needs_list.needs_list_id,
        "reliefrqst_id": request.reliefrqst_id,
        "reliefpkg_id": package.reliefpkg_id,
        "request_tracking_no": request.tracking_no,
        "package_tracking_no": package.tracking_no,
        "override_required": override_required,
        "override_markers": override_markers,
        "reserved_stock_summary": (
            _reservation_summary(selected_rows)
            if (not override_required or not allow_pending_override)
            else {}
        ),
        "allocation_lines": [
            {**row, "quantity": str(_quantize_qty(row["quantity"]))}
            for row in selected_rows
        ],
    }


@transaction.atomic
def approve_override(
    context: LegacyWorkflowContext | Mapping[str, Any],
    selections: Sequence[Mapping[str, Any] | AllocationSelection],
    *,
    actor_user_id: str,
    supervisor_user_id: str,
    supervisor_role_codes: Iterable[str] | None,
    override_reason_code: str,
    override_note: str,
    submitter_user_id: str | None = None,
    expected_request_version_nbr: int | None = None,
    expected_package_version_nbr: int | None = None,
) -> dict[str, Any]:
    ctx = _normalize_context(context)
    needs_list = _load_needs_list(ctx.needs_list_id)
    validate_override_approval(
        approver_user_id=supervisor_user_id,
        approver_role_codes=supervisor_role_codes,
        submitter_user_id=submitter_user_id or ctx.submitted_by,
        needs_list_submitted_by=needs_list.submitted_by,
    )
    return commit_allocation(
        ctx,
        selections,
        actor_user_id=actor_user_id,
        expected_request_version_nbr=expected_request_version_nbr,
        expected_package_version_nbr=expected_package_version_nbr,
        override_reason_code=override_reason_code,
        override_note=override_note,
        supervisor_user_id=supervisor_user_id,
        supervisor_role_codes=supervisor_role_codes,
        allow_pending_override=False,
    )


def build_waybill_payload(
    *,
    needs_list: NeedsList,
    request: Any,
    package: Any,
    dispatched_rows: Sequence[Mapping[str, Any]],
    actor_user_id: str,
    dispatch_dtime: datetime | None = None,
    transport_mode: str | None = None,
) -> dict[str, Any]:
    dispatch_at = dispatch_dtime or timezone.now()
    source_warehouse_ids = sorted(
        {
            int(row["inventory_id"])
            for row in dispatched_rows
            if row.get("inventory_id") not in (None, "")
        }
    )
    source_warehouse_name_map, _ = data_access.get_warehouse_names(source_warehouse_ids)
    source_warehouse_names = [
        source_warehouse_name_map[warehouse_id]
        for warehouse_id in source_warehouse_ids
        if warehouse_id in source_warehouse_name_map
    ]
    destination_name = (
        data_access.get_warehouse_name(int(package.to_inventory_id))
        if package.to_inventory_id is not None
        else None
    )
    event_name = data_access.get_event_name(int(needs_list.event_id))
    line_items = [
        {
            "item_id": int(row["item_id"]),
            "inventory_id": int(row["inventory_id"]),
            "batch_id": int(row["batch_id"]),
            "batch_no": row.get("batch_no"),
            "quantity": str(_quantize_qty(row["quantity"])),
            "uom_code": row.get("uom_code"),
            "source_type": row.get("source_type"),
            "source_record_id": row.get("source_record_id"),
        }
        for row in dispatched_rows
    ]
    return {
        "waybill_no": f"WB-{package.tracking_no}",
        "request_tracking_no": request.tracking_no,
        "package_tracking_no": package.tracking_no,
        "needs_list_id": needs_list.needs_list_id,
        "needs_list_no": needs_list.needs_list_no,
        "agency_id": request.agency_id,
        "event_id": needs_list.event_id,
        "event_name": event_name,
        "source_warehouse_ids": source_warehouse_ids,
        "source_warehouse_names": source_warehouse_names,
        "source_warehouse_id": source_warehouse_ids[0] if len(source_warehouse_ids) == 1 else None,
        "destination_warehouse_id": package.to_inventory_id,
        "destination_warehouse_name": destination_name,
        "actor_user_id": str(actor_user_id),
        "dispatch_dtime": dispatch_at.isoformat(),
        "transport_mode": transport_mode or package.transport_mode,
        "line_items": line_items,
    }


def _advance_transfer_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    actor_user_id: str,
    dispatched_at: datetime,
) -> None:
    transfer_ids = sorted(
        {
            int(row["source_record_id"])
            for row in rows
            if str(row.get("source_type") or "").upper() == "TRANSFER"
            and row.get("source_record_id") not in (None, "")
        }
    )
    if not transfer_ids:
        return
    table_name = _qualified_table("transfer")
    for transfer_id in transfer_ids:
        _execute(
            f"""
            UPDATE {table_name}
            SET status_code = %s,
                update_by_id = %s,
                update_dtime = %s,
                verify_by_id = %s,
                verify_dtime = %s,
                version_nbr = version_nbr + 1
            WHERE transfer_id = %s
            """,
            ["D", actor_user_id, dispatched_at, actor_user_id, dispatched_at, transfer_id],
        )


@transaction.atomic
def dispatch_package(
    context: LegacyWorkflowContext | Mapping[str, Any],
    *,
    actor_user_id: str,
    expected_request_version_nbr: int | None = None,
    expected_package_version_nbr: int | None = None,
    transport_mode: str | None = None,
) -> dict[str, Any]:
    from replenishment.legacy_models import ReliefPkg, ReliefRqst, ReliefRqstItem

    ctx = _normalize_context(context)
    if ctx.reliefrqst_id is None or ctx.reliefpkg_id is None:
        raise AllocationDispatchError(
            "Both reliefrqst_id and reliefpkg_id are required for dispatch.",
            code="legacy_context_missing",
        )

    needs_list = _load_needs_list(ctx.needs_list_id)
    request, package = _ensure_request_package_context(ctx)
    current_status = _current_package_status(package)
    if current_status == "D":
        raise DispatchError("Package has already been dispatched.", code="duplicate_dispatch")
    if current_status not in {"P", "C", "V"}:
        raise DispatchError(
            f"Package cannot be dispatched from status '{current_status}'.",
            code="package_not_committed",
        )
    if expected_request_version_nbr is not None and int(request.version_nbr) != int(
        expected_request_version_nbr
    ):
        raise OptimisticLockError(
            "Relief request changed before dispatch.",
            code="request_version_mismatch",
        )
    if expected_package_version_nbr is not None and int(package.version_nbr) != int(
        expected_package_version_nbr
    ):
        raise OptimisticLockError(
            "Relief package changed before dispatch.",
            code="package_version_mismatch",
        )

    package_rows = _selected_plan_for_package(package.reliefpkg_id)
    if not package_rows:
        raise DispatchError("Package contains no allocation rows to dispatch.", code="dispatch_plan_empty")

    _apply_stock_delta_for_rows(
        package_rows,
        actor_user_id=actor_user_id,
        delta_sign=1,
        update_needs_list=False,
        consume_stock=True,
    )

    now = timezone.now()
    package_update = ReliefPkg.objects.filter(
        reliefpkg_id=package.reliefpkg_id,
        version_nbr=package.version_nbr,
    ).update(
        status_code="D",
        dispatch_dtime=now,
        transport_mode=transport_mode or package.transport_mode,
        update_by_id=actor_user_id,
        update_dtime=now,
        version_nbr=F("version_nbr") + 1,
    )
    if package_update != 1:
        raise OptimisticLockError(
            f"Relief package {package.reliefpkg_id} changed during dispatch.",
            code="package_version_mismatch",
        )

    _update_needs_list_fulfillment(
        needs_list_id=needs_list.needs_list_id,
        actor_user_id=actor_user_id,
        dispatched_rows=package_rows,
    )
    _advance_transfer_rows(
        package_rows,
        actor_user_id=actor_user_id,
        dispatched_at=now,
    )

    rqst_item_table = _qualified_table("reliefrqst_item")
    for row in package_rows:
        _execute(
            f"""
            UPDATE {rqst_item_table}
            SET issue_qty = COALESCE(issue_qty, 0) + %s,
                status_code = CASE
                    WHEN COALESCE(issue_qty, 0) + %s >= request_qty THEN 'F'
                    ELSE 'P'
                END,
                action_by_id = %s,
                action_dtime = %s,
                version_nbr = version_nbr + 1
            WHERE reliefrqst_id = %s
              AND item_id = %s
            """,
            [
                row["quantity"],
                row["quantity"],
                actor_user_id,
                now,
                request.reliefrqst_id,
                row["item_id"],
            ],
        )

    request_update_values = _request_header_update_values(
        request=request,
        package_status="D",
        needs_list=needs_list,
        actor_user_id=actor_user_id,
        event_time=now,
    )
    request_update_values["status_code"] = _request_completion_status(int(request.reliefrqst_id))
    request_update = ReliefRqst.objects.filter(
        reliefrqst_id=request.reliefrqst_id,
        version_nbr=request.version_nbr,
    ).update(**request_update_values, version_nbr=F("version_nbr") + 1)
    if request_update != 1:
        raise OptimisticLockError(
            f"Relief request {request.reliefrqst_id} changed during dispatch.",
            code="request_version_mismatch",
        )

    waybill_payload = build_waybill_payload(
        needs_list=needs_list,
        request=request,
        package=package,
        dispatched_rows=package_rows,
        actor_user_id=actor_user_id,
        dispatch_dtime=now,
        transport_mode=transport_mode or package.transport_mode,
    )
    _log_audit(
        needs_list_id=needs_list.needs_list_id,
        actor_user_id=actor_user_id,
        action_type="DISPATCHED",
        reason_code="dispatch",
        notes_text=waybill_payload["waybill_no"],
    )
    return {
        "status": "DISPATCHED",
        "needs_list_id": needs_list.needs_list_id,
        "reliefrqst_id": request.reliefrqst_id,
        "reliefpkg_id": package.reliefpkg_id,
        "request_tracking_no": request.tracking_no,
        "package_tracking_no": package.tracking_no,
        "waybill_no": waybill_payload["waybill_no"],
        "waybill_payload": waybill_payload,
        "dispatched_rows": [
            {**row, "quantity": str(_quantize_qty(row["quantity"]))}
            for row in package_rows
        ],
        "reserved_stock_summary": _reservation_summary(package_rows),
    }


@transaction.atomic
def release_allocation(
    context: LegacyWorkflowContext | Mapping[str, Any],
    *,
    actor_user_id: str,
    reason_code: str,
    expected_request_version_nbr: int | None = None,
    expected_package_version_nbr: int | None = None,
) -> dict[str, Any]:
    from replenishment.legacy_models import ReliefPkg, ReliefRqst

    ctx = _normalize_context(context)
    if ctx.reliefrqst_id is None or ctx.reliefpkg_id is None:
        raise AllocationDispatchError(
            "Both reliefrqst_id and reliefpkg_id are required for release.",
            code="legacy_context_missing",
        )
    needs_list = _load_needs_list(ctx.needs_list_id)
    request, package = _ensure_request_package_context(ctx)
    if _current_package_status(package) == "D":
        raise DispatchError("Dispatched packages cannot be released.", code="package_dispatched")

    if expected_request_version_nbr is not None and int(request.version_nbr) != int(
        expected_request_version_nbr
    ):
        raise OptimisticLockError(
            "Relief request changed before release.",
            code="request_version_mismatch",
        )
    if expected_package_version_nbr is not None and int(package.version_nbr) != int(
        expected_package_version_nbr
    ):
        raise OptimisticLockError(
            "Relief package changed before release.",
            code="package_version_mismatch",
        )

    package_rows = _selected_plan_for_package(package.reliefpkg_id)
    if package_rows and _current_package_status(package) in {"P", "C", "V", "R"}:
        _apply_stock_delta_for_rows(
            package_rows,
            actor_user_id=actor_user_id,
            delta_sign=-1,
            update_needs_list=True,
            needs_list_id=needs_list.needs_list_id,
        )

    now = timezone.now()
    request_update = ReliefRqst.objects.filter(
        reliefrqst_id=request.reliefrqst_id,
        version_nbr=request.version_nbr,
    ).update(
        status_code=STATUS_APPROVED,
        status_reason_desc=str(reason_code or "allocation_release")[:255],
        action_by_id=actor_user_id,
        action_dtime=now,
        version_nbr=F("version_nbr") + 1,
    )
    if request_update != 1:
        raise OptimisticLockError(
            f"Relief request {request.reliefrqst_id} changed during release.",
            code="request_version_mismatch",
        )

    package_update = ReliefPkg.objects.filter(
        reliefpkg_id=package.reliefpkg_id,
        version_nbr=package.version_nbr,
    ).update(
        status_code="A",
        dispatch_dtime=None,
        update_by_id=actor_user_id,
        update_dtime=now,
        version_nbr=F("version_nbr") + 1,
    )
    if package_update != 1:
        raise OptimisticLockError(
            f"Relief package {package.reliefpkg_id} changed during release.",
            code="package_version_mismatch",
        )

    _log_audit(
        needs_list_id=needs_list.needs_list_id,
        actor_user_id=actor_user_id,
        action_type="ALLOCATION_RELEASED",
        reason_code=reason_code,
        notes_text=f"package={package.reliefpkg_id}",
    )
    return {
        "status": "RELEASED",
        "needs_list_id": needs_list.needs_list_id,
        "reliefrqst_id": request.reliefrqst_id,
        "reliefpkg_id": package.reliefpkg_id,
        "released_stock_summary": _reservation_summary(package_rows),
    }


def get_current_allocation(
    context: LegacyWorkflowContext | Mapping[str, Any],
) -> dict[str, Any]:
    ctx = _normalize_context(context)
    if ctx.reliefrqst_id is None or ctx.reliefpkg_id is None:
        raise AllocationDispatchError(
            "Both reliefrqst_id and reliefpkg_id are required to inspect allocations.",
            code="legacy_context_missing",
        )
    needs_list = _load_needs_list(ctx.needs_list_id)
    request, package = _ensure_request_package_context(ctx, for_update=False)
    plan_rows = _load_package_plan_with_source_info(package.reliefpkg_id)
    return {
        "needs_list_id": needs_list.needs_list_id,
        "reliefrqst_id": request.reliefrqst_id,
        "reliefpkg_id": package.reliefpkg_id,
        "request_tracking_no": request.tracking_no,
        "package_tracking_no": package.tracking_no,
        "package_status": _current_package_status(package),
        "allocation_lines": [
            {**row, "quantity": str(_quantize_qty(row["quantity"]))}
            for row in plan_rows
        ],
        "reserved_stock_summary": _reservation_summary(plan_rows),
        "dispatch_dtime": _as_iso(package.dispatch_dtime),
        "waybill_no": f"WB-{package.tracking_no}" if package.dispatch_dtime else None,
    }


__all__ = [
    "AllocationDispatchError",
    "AllocationSelection",
    "DispatchError",
    "LegacyWorkflowContext",
    "OptimisticLockError",
    "OverrideApprovalError",
    "ReservationError",
    "approve_override",
    "build_greedy_allocation_plan",
    "build_waybill_payload",
    "commit_allocation",
    "detect_override_requirement",
    "dispatch_package",
    "get_allocation_options",
    "get_current_allocation",
    "release_allocation",
    "sort_batch_candidates",
    "sort_needs_list_items_for_allocation",
    "validate_override_approval",
]
