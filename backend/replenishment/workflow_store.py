from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Tuple
from uuid import uuid4

STORE_LOCK = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store_enabled() -> bool:
    return os.getenv("NEEDS_WORKFLOW_DEV_STORE", "0") == "1"


def _store_path() -> Path:
    base_dir = Path(__file__).resolve().parent.parent
    return base_dir / ".local" / "needs_list_store.json"


def _ensure_store_dir() -> None:
    _store_path().parent.mkdir(parents=True, exist_ok=True)


def _load_store() -> Dict[str, object]:
    if not _store_path().exists():
        return {"needs_lists": {}}
    with _store_path().open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _save_store(store: Dict[str, object]) -> None:
    _ensure_store_dir()
    with _store_path().open("w", encoding="utf-8") as handle:
        json.dump(store, handle, indent=2, sort_keys=True)


def create_draft(
    payload: Dict[str, object],
    items: Iterable[Dict[str, object]],
    warnings: Iterable[str],
    actor: str | None,
) -> Dict[str, object]:
    if not _store_enabled():
        raise RuntimeError("workflow_dev_store_disabled")

    needs_list_id = str(uuid4())
    now = _utc_now()
    stored_items = []
    for item in items:
        item_copy = dict(item)
        if "computed_required_qty" not in item_copy and "required_qty" in item_copy:
            item_copy["computed_required_qty"] = item_copy.get("required_qty")
        stored_items.append(item_copy)

    record = {
        "needs_list_id": needs_list_id,
        "event_id": payload.get("event_id"),
        "warehouse_id": payload.get("warehouse_id"),
        "phase": payload.get("phase"),
        "as_of_datetime": payload.get("as_of_datetime"),
        "planning_window_days": payload.get("planning_window_days"),
        "filters": payload.get("filters"),
        "status": "DRAFT",
        "created_by": actor,
        "created_at": now,
        "updated_by": actor,
        "updated_at": now,
        "submitted_by": None,
        "submitted_at": None,
        "reviewed_by": None,
        "reviewed_at": None,
        "review_started_by": None,
        "review_started_at": None,
        "approved_by": None,
        "approved_at": None,
        "approval_tier": None,
        "approval_rationale": None,
        "prep_started_by": None,
        "prep_started_at": None,
        "dispatched_by": None,
        "dispatched_at": None,
        "received_by": None,
        "received_at": None,
        "completed_by": None,
        "completed_at": None,
        "cancelled_by": None,
        "cancelled_at": None,
        "cancel_reason": None,
        "escalated_by": None,
        "escalated_at": None,
        "escalation_reason": None,
        "returned_by": None,
        "returned_at": None,
        "return_reason": None,
        "rejected_by": None,
        "rejected_at": None,
        "reject_reason": None,
        "line_overrides": {},
        "line_review_notes": {},
        "snapshot": {
            "items": stored_items,
            "warnings": list(warnings),
            "planning_window_days": payload.get("planning_window_days"),
            "as_of_datetime": payload.get("as_of_datetime"),
        },
    }

    with STORE_LOCK:
        store = _load_store()
        needs_lists = store.setdefault("needs_lists", {})
        needs_lists[needs_list_id] = record
        _save_store(store)

    return record


def get_record(needs_list_id: str) -> Dict[str, object] | None:
    if not _store_enabled():
        raise RuntimeError("workflow_dev_store_disabled")
    with STORE_LOCK:
        store = _load_store()
        return store.get("needs_lists", {}).get(needs_list_id)


def update_record(needs_list_id: str, record: Dict[str, object]) -> None:
    if not _store_enabled():
        raise RuntimeError("workflow_dev_store_disabled")
    with STORE_LOCK:
        store = _load_store()
        needs_lists = store.setdefault("needs_lists", {})
        needs_lists[needs_list_id] = record
        _save_store(store)


def apply_overrides(record: Dict[str, object]) -> Dict[str, object]:
    snapshot = dict(record.get("snapshot") or {})
    items = [dict(item) for item in snapshot.get("items") or []]
    overrides = record.get("line_overrides") or {}
    review_notes = record.get("line_review_notes") or {}
    for item in items:
        item_id = str(item.get("item_id"))
        if item_id not in overrides:
            override = None
        else:
            override = overrides[item_id]
        if override:
            if "computed_required_qty" not in item:
                item["computed_required_qty"] = item.get("required_qty")
            item["required_qty"] = override.get("overridden_qty")
            item["override_reason"] = override.get("reason")
            item["override_updated_by"] = override.get("updated_by")
            item["override_updated_at"] = override.get("updated_at")
        note = review_notes.get(item_id)
        if note:
            item["review_comment"] = note.get("comment")
            item["review_updated_by"] = note.get("updated_by")
            item["review_updated_at"] = note.get("updated_at")
    snapshot["items"] = items
    return snapshot


def add_line_overrides(
    record: Dict[str, object],
    overrides: Iterable[Dict[str, object]],
    actor: str | None,
) -> Tuple[Dict[str, object], list[str]]:
    errors: list[str] = []
    now = _utc_now()
    items = record.get("snapshot", {}).get("items") or []
    valid_item_ids = {str(item.get("item_id")) for item in items}
    line_overrides = record.get("line_overrides") or {}
    for override in overrides:
        item_id = override.get("item_id")
        reason = override.get("reason")
        overridden_qty = override.get("overridden_qty")
        if item_id is None or str(item_id) not in valid_item_ids:
            errors.append(f"item_id {item_id} not found in draft")
            continue
        if not reason:
            errors.append(f"reason required for item_id {item_id}")
            continue
        line_overrides[str(item_id)] = {
            "overridden_qty": overridden_qty,
            "reason": reason,
            "updated_by": actor,
            "updated_at": now,
        }
    record["line_overrides"] = line_overrides
    record["updated_by"] = actor
    record["updated_at"] = now
    return record, errors


def add_line_review_notes(
    record: Dict[str, object],
    notes: Iterable[Dict[str, object]],
    actor: str | None,
) -> Tuple[Dict[str, object], list[str]]:
    errors: list[str] = []
    now = _utc_now()
    items = record.get("snapshot", {}).get("items") or []
    valid_item_ids = {str(item.get("item_id")) for item in items}
    line_notes = record.get("line_review_notes") or {}
    for note in notes:
        item_id = note.get("item_id")
        comment = note.get("comment")
        if item_id is None or str(item_id) not in valid_item_ids:
            errors.append(f"item_id {item_id} not found in draft")
            continue
        if not comment or not str(comment).strip():
            errors.append(f"comment required for item_id {item_id}")
            continue
        line_notes[str(item_id)] = {
            "comment": str(comment).strip(),
            "updated_by": actor,
            "updated_at": now,
        }
    record["line_review_notes"] = line_notes
    record["updated_by"] = actor
    record["updated_at"] = now
    return record, errors


def transition_status(
    record: Dict[str, object],
    to_status: str,
    actor: str | None,
    reason: str | None = None,
) -> Dict[str, object]:
    now = _utc_now()
    record["status"] = to_status
    record["updated_by"] = actor
    record["updated_at"] = now
    if to_status == "SUBMITTED":
        record["submitted_by"] = actor
        record["submitted_at"] = now
    if to_status == "UNDER_REVIEW":
        record["review_started_by"] = actor
        record["review_started_at"] = now
        record["reviewed_by"] = actor
        record["reviewed_at"] = now
    if to_status == "APPROVED":
        record["approved_by"] = actor
        record["approved_at"] = now
    if to_status == "IN_PREPARATION":
        record["prep_started_by"] = actor
        record["prep_started_at"] = now
    if to_status == "DISPATCHED":
        record["dispatched_by"] = actor
        record["dispatched_at"] = now
    if to_status == "RECEIVED":
        record["received_by"] = actor
        record["received_at"] = now
    if to_status == "COMPLETED":
        record["completed_by"] = actor
        record["completed_at"] = now
    if to_status == "REJECTED":
        record["rejected_by"] = actor
        record["rejected_at"] = now
        record["reject_reason"] = reason
    if to_status == "RETURNED":
        record["returned_by"] = actor
        record["returned_at"] = now
        record["return_reason"] = reason
    if to_status == "ESCALATED":
        record["escalated_by"] = actor
        record["escalated_at"] = now
        record["escalation_reason"] = reason
    if to_status == "CANCELLED":
        record["cancelled_by"] = actor
        record["cancelled_at"] = now
        record["cancel_reason"] = reason
    return record


def store_enabled_or_raise() -> None:
    if not _store_enabled():
        raise RuntimeError("workflow_dev_store_disabled")
