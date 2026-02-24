"""
Procurement service layer for Horizon C workflow.

Handles creation, approval, ordering, shipping, and receiving of procurement orders.
All state transitions are validated and audit-logged.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from django.db import IntegrityError, connection, transaction
from django.db.models import IntegerField, Max, Sum
from django.db.models.functions import Cast, Length, Substr
from django.utils import timezone

from replenishment import rules
from replenishment.models import (
    NeedsList,
    NeedsListItem,
    Procurement,
    ProcurementItem,
    Supplier,
)

logger = logging.getLogger("dmis.audit")

_PROCUREMENT_NO_RETRY_ATTEMPTS = 3
_PROCUREMENT_NO_RETRY_BACKOFF_SECONDS = 0.02

# Valid status transitions
_VALID_TRANSITIONS = {
    "DRAFT": {"PENDING_APPROVAL", "CANCELLED"},
    "PENDING_APPROVAL": {"APPROVED", "REJECTED", "CANCELLED"},
    "APPROVED": {"ORDERED", "CANCELLED"},
    "REJECTED": set(),
    "ORDERED": {"SHIPPED", "CANCELLED"},
    "SHIPPED": {"PARTIAL_RECEIVED", "RECEIVED"},
    "PARTIAL_RECEIVED": {"RECEIVED"},
    "RECEIVED": set(),
    "CANCELLED": set(),
}


class ProcurementError(Exception):
    """Raised when a procurement operation fails."""

    def __init__(self, message: str, code: str = "procurement_error"):
        self.message = message
        self.code = code
        super().__init__(message)


def generate_procurement_no() -> str:
    """Generate a unique procurement number: PROC-{YYYYMMDD}-{SEQ}."""
    today = timezone.now().strftime("%Y%m%d")
    prefix = f"PROC-{today}-"
    suffix_start = len(prefix) + 1  # Substr is 1-indexed in SQL backends.

    queryset = Procurement.objects.filter(procurement_no__startswith=prefix)
    if connection.vendor == "postgresql":
        # Avoid invalid integer casts by accepting only strictly numeric suffixes.
        pattern = rf"^{re.escape(prefix)}\d+$"
        queryset = queryset.filter(procurement_no__regex=pattern)
    else:
        # SQLite does not guarantee regex support; keep prefix + length guard.
        queryset = queryset.annotate(no_len=Length("procurement_no")).filter(no_len__gt=len(prefix))

    max_seq = queryset.annotate(
        seq_num=Cast(Substr("procurement_no", suffix_start), IntegerField())
    ).aggregate(
        max_seq=Max("seq_num")
    ).get("max_seq")
    seq = int(max_seq or 0) + 1
    return f"{prefix}{seq:03d}"


def _is_procurement_no_conflict(exc: IntegrityError) -> bool:
    message = str(exc).lower()
    return "procurement_no" in message and ("unique" in message or "duplicate" in message)


def _validate_transition(current: str, target: str) -> None:
    allowed = _VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ProcurementError(
            f"Cannot transition from {current} to {target}.",
            code="invalid_transition",
        )


def _compute_total_value(procurement: Procurement) -> Decimal:
    """Recalculate total value from line items."""
    total = Decimal("0.00")
    for item in procurement.items.all():
        if item.unit_price is not None and item.ordered_qty is not None:
            line = item.ordered_qty * item.unit_price
            item.line_total = line
            item.save(update_fields=["line_total", "update_dtime"])
            total += line
        elif item.line_total is not None:
            total += item.line_total
    return total


def _get_approval_info(
    total_value: Decimal, phase: str
) -> Dict[str, Any]:
    """Get procurement approval tier info from rules engine."""
    approval, _ = rules.get_procurement_approval(
        float(total_value), phase
    )
    return approval


def _normalize_approval_tier_for_model(raw_tier: object) -> str | None:
    """Map rules-engine tier labels to Procurement.approval_threshold_tier choices."""
    normalized = str(raw_tier or "").strip().upper()
    if not normalized:
        return None
    if "EMERGENCY" in normalized:
        return "EMERGENCY"
    if "TIER 3" in normalized or "TIER_3" in normalized:
        return "TIER_3"
    if "TIER 2" in normalized or "TIER_2" in normalized:
        return "TIER_2"
    if "TIER 1" in normalized or "TIER_1" in normalized:
        return "TIER_1"
    return None


def _serialize_procurement(proc: Procurement) -> Dict[str, Any]:
    """Serialize a Procurement instance to a response dict."""
    supplier_data = None
    if proc.supplier:
        s = proc.supplier
        supplier_data = {
            "supplier_id": s.supplier_id,
            "supplier_code": s.supplier_code,
            "supplier_name": s.supplier_name,
            "contact_name": s.contact_name,
            "phone_no": s.phone_no,
            "email_text": s.email_text,
            "default_lead_time_days": s.default_lead_time_days,
            "is_framework_supplier": s.is_framework_supplier,
            "status_code": s.status_code,
        }

    # Fetch warehouse name from legacy table
    warehouse_name = ""
    try:
        from replenishment.services.data_access import get_warehouse_name
        with transaction.atomic():
            warehouse_name = get_warehouse_name(proc.target_warehouse_id) or ""
    except Exception:
        pass

    # Get approval info
    phase = "BASELINE"
    if proc.needs_list:
        phase = proc.needs_list.event_phase or "BASELINE"
    approval = _get_approval_info(proc.total_value, phase)

    # Batch-fetch item names
    proc_items = list(proc.items.order_by("procurement_item_id"))
    item_ids = [pi.item_id for pi in proc_items]
    item_names_map: Dict[int, str] = {}
    if item_ids:
        try:
            from replenishment.services.data_access import get_item_names
            with transaction.atomic():
                names_data, _ = get_item_names(item_ids)
            item_names_map = {
                iid: info.get("name", "") for iid, info in names_data.items()
            }
        except Exception:
            pass

    items = []
    for pi in proc_items:
        items.append(
            {
                "procurement_item_id": pi.procurement_item_id,
                "item_id": pi.item_id,
                "item_name": item_names_map.get(pi.item_id, ""),
                "ordered_qty": float(pi.ordered_qty),
                "unit_price": float(pi.unit_price) if pi.unit_price is not None else None,
                "line_total": float(pi.line_total) if pi.line_total is not None else None,
                "uom_code": pi.uom_code,
                "received_qty": float(pi.received_qty),
                "status_code": pi.status_code,
            }
        )

    return {
        "procurement_id": proc.procurement_id,
        "procurement_no": proc.procurement_no,
        "needs_list_id": proc.needs_list.needs_list_no if proc.needs_list else None,
        "event_id": proc.event_id,
        "target_warehouse_id": proc.target_warehouse_id,
        "warehouse_name": warehouse_name,
        "supplier": supplier_data,
        "procurement_method": proc.procurement_method,
        "po_number": proc.po_number,
        "total_value": str(proc.total_value),
        "currency_code": proc.currency_code,
        "status_code": proc.status_code,
        "approval": approval,
        "items": items,
        "shipped_at": proc.shipped_at.isoformat() if proc.shipped_at else None,
        "expected_arrival": proc.expected_arrival.isoformat() if proc.expected_arrival else None,
        "received_at": proc.received_at.isoformat() if proc.received_at else None,
        "notes_text": proc.notes_text or "",
        "create_dtime": proc.create_dtime.isoformat() if proc.create_dtime else None,
        "update_dtime": proc.update_dtime.isoformat() if proc.update_dtime else None,
    }


def _serialize_supplier(s: Supplier) -> Dict[str, Any]:
    return {
        "supplier_id": s.supplier_id,
        "supplier_code": s.supplier_code,
        "supplier_name": s.supplier_name,
        "contact_name": s.contact_name,
        "phone_no": s.phone_no,
        "email_text": s.email_text,
        "address_text": s.address_text,
        "parish_code": s.parish_code,
        "default_lead_time_days": s.default_lead_time_days,
        "is_framework_supplier": s.is_framework_supplier,
        "framework_contract_no": s.framework_contract_no,
        "framework_expiry_date": (
            s.framework_expiry_date.isoformat() if s.framework_expiry_date else None
        ),
        "status_code": s.status_code,
    }


# ── Core Operations ─────────────────────────────────────────────────────────


@transaction.atomic
def create_procurement_from_needs_list(
    needs_list_id: str, actor_id: str
) -> Dict[str, Any]:
    """Create a procurement order from a needs list's Horizon C items."""
    try:
        nl = NeedsList.objects.get(needs_list_no=needs_list_id)
    except NeedsList.DoesNotExist:
        raise ProcurementError("Needs list not found.", code="not_found")

    if nl.status_code not in ("APPROVED", "IN_PROGRESS", "FULFILLED"):
        raise ProcurementError(
            "Needs list must be approved before creating procurement.",
            code="invalid_status",
        )

    # Get Horizon C items
    horizon_c_items = nl.items.filter(horizon_c_qty__gt=0)
    if not horizon_c_items.exists():
        raise ProcurementError(
            "No Horizon C items found in this needs list.",
            code="no_horizon_c_items",
        )

    proc: Procurement | None = None
    for attempt in range(_PROCUREMENT_NO_RETRY_ATTEMPTS):
        try:
            # Use a savepoint so duplicate-number collisions can retry safely.
            with transaction.atomic():
                proc = Procurement.objects.create(
                    procurement_no=generate_procurement_no(),
                    needs_list=nl,
                    event_id=nl.event_id,
                    target_warehouse_id=nl.warehouse_id,
                    procurement_method="SINGLE_SOURCE",
                    status_code="DRAFT",
                    create_by_id=actor_id,
                    update_by_id=actor_id,
                )
            break
        except IntegrityError as exc:
            if not _is_procurement_no_conflict(exc):
                raise
            if attempt >= _PROCUREMENT_NO_RETRY_ATTEMPTS - 1:
                raise ProcurementError(
                    "Failed to generate a unique procurement number. Please retry.",
                    code="duplicate_procurement_no",
                ) from exc
            time.sleep(_PROCUREMENT_NO_RETRY_BACKOFF_SECONDS * (attempt + 1))

    if proc is None:
        raise ProcurementError(
            "Failed to generate a unique procurement number. Please retry.",
            code="duplicate_procurement_no",
        )

    for nli in horizon_c_items:
        ProcurementItem.objects.create(
            procurement=proc,
            item_id=nli.item_id,
            needs_list_item=nli,
            ordered_qty=nli.horizon_c_qty,
            uom_code=nli.uom_code,
            create_by_id=actor_id,
            update_by_id=actor_id,
        )

    proc.total_value = _compute_total_value(proc)
    approval = _get_approval_info(proc.total_value, nl.event_phase or "BASELINE")
    proc.approval_threshold_tier = _normalize_approval_tier_for_model(approval.get("tier"))
    proc.save(update_fields=["total_value", "approval_threshold_tier", "update_dtime"])

    logger.info(
        "procurement.created proc_no=%s needs_list=%s actor=%s items=%d",
        proc.procurement_no,
        needs_list_id,
        actor_id,
        horizon_c_items.count(),
    )

    return _serialize_procurement(proc)


@transaction.atomic
def create_procurement_standalone(
    event_id: int,
    target_warehouse_id: int,
    items: List[Dict[str, Any]],
    actor_id: str,
    procurement_method: str = "SINGLE_SOURCE",
    supplier_id: Optional[int] = None,
    notes: str = "",
) -> Dict[str, Any]:
    """Create a standalone procurement order (not linked to needs list)."""
    if not items:
        raise ProcurementError("At least one item is required.", code="no_items")

    supplier = None
    if supplier_id:
        try:
            supplier = Supplier.objects.get(supplier_id=supplier_id, status_code="A")
        except Supplier.DoesNotExist:
            raise ProcurementError("Supplier not found or inactive.", code="invalid_supplier")

    proc: Procurement | None = None
    for attempt in range(_PROCUREMENT_NO_RETRY_ATTEMPTS):
        try:
            # Use a savepoint so duplicate-number collisions can retry safely.
            with transaction.atomic():
                proc = Procurement.objects.create(
                    procurement_no=generate_procurement_no(),
                    event_id=event_id,
                    target_warehouse_id=target_warehouse_id,
                    supplier=supplier,
                    procurement_method=procurement_method or "SINGLE_SOURCE",
                    status_code="DRAFT",
                    notes_text=notes,
                    create_by_id=actor_id,
                    update_by_id=actor_id,
                )
            break
        except IntegrityError as exc:
            if not _is_procurement_no_conflict(exc):
                raise
            if attempt >= _PROCUREMENT_NO_RETRY_ATTEMPTS - 1:
                raise ProcurementError(
                    "Failed to generate a unique procurement number. Please retry.",
                    code="duplicate_procurement_no",
                ) from exc
            time.sleep(_PROCUREMENT_NO_RETRY_BACKOFF_SECONDS * (attempt + 1))

    if proc is None:
        raise ProcurementError(
            "Failed to generate a unique procurement number. Please retry.",
            code="duplicate_procurement_no",
        )

    for line in items:
        raw_item_id = line.get("item_id")
        try:
            item_id = int(raw_item_id)
        except (TypeError, ValueError):
            raise ProcurementError(
                f"Invalid item_id for line item: {raw_item_id!r}.",
                code="invalid_item_id",
            )

        unit_price = None
        raw_unit_price = line.get("unit_price")
        if raw_unit_price is not None:
            try:
                unit_price = Decimal(str(raw_unit_price))
            except (InvalidOperation, ValueError, TypeError):
                raise ProcurementError(
                    f"Invalid unit_price for item {item_id}: {raw_unit_price!r}.",
                    code="invalid_unit_price",
                )

        raw_ordered_qty = line.get("ordered_qty", 0)
        try:
            ordered_qty = Decimal(str(raw_ordered_qty))
        except (InvalidOperation, ValueError, TypeError):
            raise ProcurementError(
                f"Invalid ordered_qty for item {item_id}: {raw_ordered_qty!r}.",
                code="invalid_ordered_qty",
            )

        line_total = (ordered_qty * unit_price) if unit_price is not None else None

        ProcurementItem.objects.create(
            procurement=proc,
            item_id=item_id,
            ordered_qty=ordered_qty,
            unit_price=unit_price,
            line_total=line_total,
            uom_code=line.get("uom_code", "EA"),
            create_by_id=actor_id,
            update_by_id=actor_id,
        )

    proc.total_value = _compute_total_value(proc)
    proc.save(update_fields=["total_value", "update_dtime"])

    logger.info(
        "procurement.created proc_no=%s standalone actor=%s items=%d",
        proc.procurement_no,
        actor_id,
        len(items),
    )

    return _serialize_procurement(proc)


def list_procurements(
    filters: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """List procurement orders with optional filters."""
    qs = Procurement.objects.select_related("supplier", "needs_list").all()

    if filters:
        if filters.get("status"):
            qs = qs.filter(status_code=filters["status"])
        if filters.get("warehouse_id"):
            qs = qs.filter(target_warehouse_id=int(filters["warehouse_id"]))
        if filters.get("event_id"):
            qs = qs.filter(event_id=int(filters["event_id"]))
        if filters.get("needs_list_id"):
            qs = qs.filter(needs_list__needs_list_no=filters["needs_list_id"])
        if filters.get("supplier_id"):
            qs = qs.filter(supplier_id=int(filters["supplier_id"]))

    procurements = list(qs.order_by("-create_dtime"))
    return [_serialize_procurement(p) for p in procurements], len(procurements)


def get_procurement(procurement_id: int) -> Dict[str, Any]:
    """Get a single procurement order by ID."""
    try:
        proc = Procurement.objects.select_related("supplier", "needs_list").get(
            procurement_id=procurement_id
        )
    except Procurement.DoesNotExist:
        raise ProcurementError("Procurement not found.", code="not_found")
    return _serialize_procurement(proc)


@transaction.atomic
def update_procurement_draft(
    procurement_id: int, updates: Dict[str, Any], actor_id: str
) -> Dict[str, Any]:
    """Update a procurement order in DRAFT status."""
    try:
        proc = Procurement.objects.select_related("supplier", "needs_list").get(
            procurement_id=procurement_id
        )
    except Procurement.DoesNotExist:
        raise ProcurementError("Procurement not found.", code="not_found")

    if proc.status_code != "DRAFT":
        raise ProcurementError(
            "Only DRAFT procurements can be edited.", code="invalid_status"
        )

    update_fields = ["update_by_id", "update_dtime"]
    proc.update_by_id = actor_id

    if "supplier_id" in updates:
        if updates["supplier_id"]:
            try:
                proc.supplier = Supplier.objects.get(
                    supplier_id=int(updates["supplier_id"]), status_code="A"
                )
            except Supplier.DoesNotExist:
                raise ProcurementError(
                    "Supplier not found or inactive.", code="invalid_supplier"
                )
        else:
            proc.supplier = None
        update_fields.append("supplier")

    if "procurement_method" in updates:
        proc.procurement_method = updates["procurement_method"]
        update_fields.append("procurement_method")

    if "notes" in updates:
        proc.notes_text = updates["notes"]
        update_fields.append("notes_text")

    deleted_item_ids: set[int] = set()
    if "deleted_procurement_item_ids" in updates:
        for raw_item_id in updates.get("deleted_procurement_item_ids") or []:
            try:
                deleted_item_ids.add(int(raw_item_id))
            except (TypeError, ValueError):
                continue
        if deleted_item_ids:
            ProcurementItem.objects.filter(
                procurement=proc,
                procurement_item_id__in=list(deleted_item_ids),
            ).delete()

    # Update line items if provided
    if "items" in updates:
        for line in updates["items"]:
            if line.get("procurement_item_id"):
                try:
                    procurement_item_id = int(line["procurement_item_id"])
                except (TypeError, ValueError):
                    continue
                if procurement_item_id in deleted_item_ids:
                    continue
                try:
                    pi = ProcurementItem.objects.get(
                        procurement_item_id=procurement_item_id,
                        procurement=proc,
                    )
                except ProcurementItem.DoesNotExist:
                    continue

                item_fields = ["update_by_id", "update_dtime"]
                pi.update_by_id = actor_id

                if "ordered_qty" in line:
                    pi.ordered_qty = Decimal(str(line["ordered_qty"]))
                    item_fields.append("ordered_qty")
                if "unit_price" in line:
                    if line["unit_price"] is not None:
                        pi.unit_price = Decimal(str(line["unit_price"]))
                    else:
                        pi.unit_price = None
                    item_fields.append("unit_price")

                if "ordered_qty" in line or "unit_price" in line:
                    if pi.unit_price is not None:
                        pi.line_total = pi.ordered_qty * pi.unit_price
                    else:
                        pi.line_total = None
                    if "line_total" not in item_fields:
                        item_fields.append("line_total")

                pi.save(update_fields=item_fields)
            elif line.get("item_id"):
                # Add new line item
                unit_price = None
                if line.get("unit_price") is not None:
                    unit_price = Decimal(str(line["unit_price"]))
                ordered_qty = Decimal(str(line.get("ordered_qty", 0)))
                line_total = (ordered_qty * unit_price) if unit_price else None

                ProcurementItem.objects.create(
                    procurement=proc,
                    item_id=int(line["item_id"]),
                    ordered_qty=ordered_qty,
                    unit_price=unit_price,
                    line_total=line_total,
                    uom_code=line.get("uom_code", "EA"),
                    create_by_id=actor_id,
                    update_by_id=actor_id,
                )

    # Recalculate total
    proc.total_value = _compute_total_value(proc)
    update_fields.append("total_value")

    phase = "BASELINE"
    if proc.needs_list:
        phase = proc.needs_list.event_phase or "BASELINE"
    approval = _get_approval_info(proc.total_value, phase)
    proc.approval_threshold_tier = _normalize_approval_tier_for_model(approval.get("tier"))
    update_fields.append("approval_threshold_tier")

    proc.save(update_fields=update_fields)

    logger.info(
        "procurement.updated proc_no=%s actor=%s", proc.procurement_no, actor_id
    )

    return _serialize_procurement(proc)


@transaction.atomic
def submit_procurement(procurement_id: int, actor_id: str) -> Dict[str, Any]:
    """Submit procurement for approval: DRAFT → PENDING_APPROVAL."""
    proc = _get_and_validate_transition(procurement_id, "PENDING_APPROVAL")

    if not proc.items.exists():
        raise ProcurementError(
            "Cannot submit procurement with no items.", code="no_items"
        )

    proc.status_code = "PENDING_APPROVAL"
    proc.update_by_id = actor_id
    proc.save(update_fields=["status_code", "update_by_id", "update_dtime"])

    logger.info(
        "procurement.submitted proc_no=%s actor=%s", proc.procurement_no, actor_id
    )

    return _serialize_procurement(proc)


@transaction.atomic
def approve_procurement(
    procurement_id: int, actor_id: str, notes: str = ""
) -> Dict[str, Any]:
    """Approve procurement: PENDING_APPROVAL → APPROVED."""
    proc = _get_and_validate_transition(procurement_id, "APPROVED")

    now = timezone.now()
    proc.status_code = "APPROVED"
    proc.approved_at = now
    proc.approved_by = actor_id
    proc.update_by_id = actor_id
    if notes:
        existing = proc.notes_text or ""
        proc.notes_text = f"{existing}\n[Approval] {notes}".strip()
    proc.save(
        update_fields=[
            "status_code",
            "approved_at",
            "approved_by",
            "update_by_id",
            "notes_text",
            "update_dtime",
        ]
    )

    logger.info(
        "procurement.approved proc_no=%s actor=%s", proc.procurement_no, actor_id
    )

    return _serialize_procurement(proc)


@transaction.atomic
def reject_procurement(
    procurement_id: int, actor_id: str, reason: str
) -> Dict[str, Any]:
    """Reject procurement: PENDING_APPROVAL → REJECTED."""
    proc = _get_and_validate_transition(procurement_id, "REJECTED")

    if not reason or not reason.strip():
        raise ProcurementError("Rejection reason is required.", code="reason_required")

    proc.status_code = "REJECTED"
    proc.update_by_id = actor_id
    existing = proc.notes_text or ""
    proc.notes_text = f"{existing}\n[Rejected] {reason}".strip()
    proc.save(
        update_fields=["status_code", "update_by_id", "notes_text", "update_dtime"]
    )

    logger.info(
        "procurement.rejected proc_no=%s actor=%s reason=%s",
        proc.procurement_no,
        actor_id,
        reason,
    )

    return _serialize_procurement(proc)


@transaction.atomic
def mark_ordered(
    procurement_id: int, po_number: str, actor_id: str
) -> Dict[str, Any]:
    """Mark procurement as ordered: APPROVED → ORDERED."""
    proc = _get_and_validate_transition(procurement_id, "ORDERED")

    if not po_number or not po_number.strip():
        raise ProcurementError("PO number is required.", code="po_required")

    proc.status_code = "ORDERED"
    proc.po_number = po_number.strip()
    proc.update_by_id = actor_id
    proc.save(
        update_fields=["status_code", "po_number", "update_by_id", "update_dtime"]
    )

    logger.info(
        "procurement.ordered proc_no=%s po=%s actor=%s",
        proc.procurement_no,
        po_number,
        actor_id,
    )

    return _serialize_procurement(proc)


@transaction.atomic
def mark_shipped(
    procurement_id: int,
    shipped_at: Optional[str],
    expected_arrival: Optional[str],
    actor_id: str,
) -> Dict[str, Any]:
    """Mark procurement as shipped: ORDERED → SHIPPED."""
    proc = _get_and_validate_transition(procurement_id, "SHIPPED")

    now = timezone.now()
    proc.status_code = "SHIPPED"
    proc.shipped_at = _parse_datetime(shipped_at) or now
    if expected_arrival:
        proc.expected_arrival = _parse_datetime(expected_arrival)
    proc.update_by_id = actor_id
    proc.save(
        update_fields=[
            "status_code",
            "shipped_at",
            "expected_arrival",
            "update_by_id",
            "update_dtime",
        ]
    )

    logger.info(
        "procurement.shipped proc_no=%s actor=%s", proc.procurement_no, actor_id
    )

    return _serialize_procurement(proc)


@transaction.atomic
def receive_items(
    procurement_id: int,
    line_receipts: List[Dict[str, Any]],
    actor_id: str,
) -> Dict[str, Any]:
    """Record received quantities for procurement line items."""
    try:
        proc = Procurement.objects.select_related("supplier", "needs_list").get(
            procurement_id=procurement_id
        )
    except Procurement.DoesNotExist:
        raise ProcurementError("Procurement not found.", code="not_found")

    if proc.status_code not in ("SHIPPED", "PARTIAL_RECEIVED"):
        raise ProcurementError(
            f"Cannot receive items in {proc.status_code} status.",
            code="invalid_status",
        )

    if not line_receipts:
        raise ProcurementError("No receipt lines provided.", code="no_receipts")

    for receipt in line_receipts:
        try:
            pi = ProcurementItem.objects.get(
                procurement_item_id=int(receipt["procurement_item_id"]),
                procurement=proc,
            )
        except ProcurementItem.DoesNotExist:
            raise ProcurementError(
                f"Procurement item {receipt.get('procurement_item_id')} not found.",
                code="item_not_found",
            )

        received_qty = Decimal(str(receipt.get("received_qty", 0)))
        if received_qty <= 0:
            continue

        pi.received_qty += received_qty
        if pi.received_qty >= pi.ordered_qty:
            pi.status_code = "RECEIVED"
        else:
            pi.status_code = "PARTIAL"
        pi.update_by_id = actor_id
        pi.save(
            update_fields=[
                "received_qty",
                "status_code",
                "update_by_id",
                "update_dtime",
            ]
        )

    # Determine overall procurement status
    all_items = proc.items.all()
    all_received = all(i.received_qty >= i.ordered_qty for i in all_items)
    any_received = any(i.received_qty > 0 for i in all_items)

    now = timezone.now()
    if all_received:
        proc.status_code = "RECEIVED"
        proc.received_at = now
        proc.received_by = actor_id
    elif any_received:
        proc.status_code = "PARTIAL_RECEIVED"

    proc.update_by_id = actor_id
    proc.save(
        update_fields=[
            "status_code",
            "received_at",
            "received_by",
            "update_by_id",
            "update_dtime",
        ]
    )

    logger.info(
        "procurement.received proc_no=%s status=%s actor=%s",
        proc.procurement_no,
        proc.status_code,
        actor_id,
    )

    return _serialize_procurement(proc)


@transaction.atomic
def cancel_procurement(
    procurement_id: int, reason: str, actor_id: str
) -> Dict[str, Any]:
    """Cancel a procurement order."""
    try:
        proc = Procurement.objects.select_related("supplier", "needs_list").get(
            procurement_id=procurement_id
        )
    except Procurement.DoesNotExist:
        raise ProcurementError("Procurement not found.", code="not_found")

    _validate_transition(proc.status_code, "CANCELLED")

    if not reason or not reason.strip():
        raise ProcurementError("Cancellation reason is required.", code="reason_required")

    proc.status_code = "CANCELLED"
    proc.update_by_id = actor_id
    existing = proc.notes_text or ""
    proc.notes_text = f"{existing}\n[Cancelled] {reason}".strip()
    proc.save(
        update_fields=["status_code", "update_by_id", "notes_text", "update_dtime"]
    )

    # Cancel all pending items
    proc.items.filter(status_code="PENDING").update(
        status_code="CANCELLED", update_by_id=actor_id
    )

    logger.info(
        "procurement.cancelled proc_no=%s actor=%s reason=%s",
        proc.procurement_no,
        actor_id,
        reason,
    )

    return _serialize_procurement(proc)


# ── Supplier Operations ─────────────────────────────────────────────────────


def list_suppliers(active_only: bool = True) -> List[Dict[str, Any]]:
    """List suppliers, optionally filtered to active only."""
    qs = Supplier.objects.all()
    if active_only:
        qs = qs.filter(status_code="A")
    return [_serialize_supplier(s) for s in qs.order_by("supplier_name")]


def get_supplier(supplier_id: int) -> Dict[str, Any]:
    """Get a single supplier by ID."""
    try:
        s = Supplier.objects.get(supplier_id=supplier_id)
    except Supplier.DoesNotExist:
        raise ProcurementError("Supplier not found.", code="not_found")
    return _serialize_supplier(s)


def create_supplier(data: Dict[str, Any], actor_id: str) -> Dict[str, Any]:
    """Create a new supplier."""
    if not data.get("supplier_name"):
        raise ProcurementError("Supplier name is required.", code="name_required")
    if not data.get("supplier_code"):
        raise ProcurementError("Supplier code is required.", code="code_required")

    if Supplier.objects.filter(supplier_code=data["supplier_code"]).exists():
        raise ProcurementError(
            "Supplier code already exists.", code="duplicate_code"
        )

    s = Supplier.objects.create(
        supplier_code=data["supplier_code"],
        supplier_name=data["supplier_name"],
        contact_name=data.get("contact_name"),
        phone_no=data.get("phone_no"),
        email_text=data.get("email_text"),
        address_text=data.get("address_text"),
        parish_code=data.get("parish_code"),
        default_lead_time_days=int(data.get("default_lead_time_days", 14)),
        is_framework_supplier=bool(data.get("is_framework_supplier", False)),
        framework_contract_no=data.get("framework_contract_no"),
        status_code="A",
        create_by_id=actor_id,
        update_by_id=actor_id,
    )

    logger.info(
        "supplier.created code=%s name=%s actor=%s",
        s.supplier_code,
        s.supplier_name,
        actor_id,
    )

    return _serialize_supplier(s)


def update_supplier(
    supplier_id: int, data: Dict[str, Any], actor_id: str
) -> Dict[str, Any]:
    """Update an existing supplier."""
    try:
        s = Supplier.objects.get(supplier_id=supplier_id)
    except Supplier.DoesNotExist:
        raise ProcurementError("Supplier not found.", code="not_found")

    update_fields = ["update_by_id", "update_dtime"]
    s.update_by_id = actor_id

    for field in (
        "supplier_name",
        "contact_name",
        "phone_no",
        "email_text",
        "address_text",
        "parish_code",
        "framework_contract_no",
        "status_code",
    ):
        if field in data:
            setattr(s, field, data[field])
            update_fields.append(field)

    if "default_lead_time_days" in data:
        s.default_lead_time_days = int(data["default_lead_time_days"])
        update_fields.append("default_lead_time_days")

    if "is_framework_supplier" in data:
        s.is_framework_supplier = bool(data["is_framework_supplier"])
        update_fields.append("is_framework_supplier")

    s.save(update_fields=update_fields)

    logger.info(
        "supplier.updated code=%s actor=%s", s.supplier_code, actor_id
    )

    return _serialize_supplier(s)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_and_validate_transition(procurement_id: int, target: str) -> Procurement:
    """Get procurement and validate the requested transition."""
    try:
        proc = Procurement.objects.select_related("supplier", "needs_list").get(
            procurement_id=procurement_id
        )
    except Procurement.DoesNotExist:
        raise ProcurementError("Procurement not found.", code="not_found")

    _validate_transition(proc.status_code, target)
    return proc


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO datetime string."""
    if not value:
        return None
    from django.utils.dateparse import (
        parse_date as django_parse_date,
        parse_datetime as django_parse,
    )

    parsed = django_parse(value)
    if parsed is None:
        parsed_date = django_parse_date(value)
        if parsed_date is not None:
            parsed = datetime.combine(parsed_date, datetime.min.time())
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed
