"""
Generic API views for master data CRUD.

All endpoints are parameterized by ``table_key`` which maps to a
``TableConfig`` in the registry.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from django.conf import settings
from django.core.cache import cache
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from api.authentication import LegacyCompatAuthentication
from masterdata.ifrc_code_agent import IFRCCodeSuggestion, IFRCAgent, cb_is_open
from masterdata.models import ItemIfrcSuggestLog
from masterdata.permissions import (
    MasterDataPermission,
    PERM_MASTERDATA_CREATE,
    PERM_MASTERDATA_EDIT,
    PERM_MASTERDATA_INACTIVATE,
    PERM_MASTERDATA_VIEW,
)
from masterdata.serializers import IFRCSuggestionResponseSerializer
from masterdata.services.data_access import (
    TABLE_REGISTRY,
    activate_record,
    check_dependencies,
    create_record,
    get_lookup,
    get_record,
    get_summary_counts,
    get_table_config,
    inactivate_record,
    list_records,
    update_record,
)
from masterdata.services.validation import validate_record

logger = logging.getLogger(__name__)

DEFAULT_PAGE_LIMIT = 100
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 500
_SAFE_INPUT_RE = re.compile(r"[^a-zA-Z0-9\s\-\'\(\)/]")
_IFRC_AGENT_SINGLETON: IFRCAgent | None = None


def _actor_id(request) -> str:
    return str(getattr(request.user, "user_id", "system"))


def _validate_table_key(table_key: str):
    cfg = get_table_config(table_key)
    if cfg is None:
        return None, Response({"detail": f"Unknown table: {table_key}"}, status=404)
    return cfg, None


def _ifrc_cfg() -> dict[str, Any]:
    cfg = getattr(settings, "IFRC_AGENT", {})
    return {
        "IFRC_ENABLED": bool(cfg.get("IFRC_ENABLED", True)),
        "MIN_INPUT_LENGTH": int(cfg.get("MIN_INPUT_LENGTH", 3)),
        "MAX_INPUT_LENGTH": int(cfg.get("MAX_INPUT_LENGTH", 120)),
        "RATE_LIMIT_PER_MINUTE": int(cfg.get("RATE_LIMIT_PER_MINUTE", 30)),
        "AUTO_FILL_CONFIDENCE_THRESHOLD": float(cfg.get("AUTO_FILL_CONFIDENCE_THRESHOLD", 0.80)),
        "OLLAMA_MODEL_ID": str(cfg.get("OLLAMA_MODEL_ID", "qwen3.5:0.8b")),
        "LLM_ENABLED": bool(cfg.get("LLM_ENABLED", False)),
    }


def _ifrc_agent() -> IFRCAgent:
    global _IFRC_AGENT_SINGLETON
    if _IFRC_AGENT_SINGLETON is None:
        _IFRC_AGENT_SINGLETON = IFRCAgent()
    return _IFRC_AGENT_SINGLETON


def _ifrc_rate_limit_key(user_id: str) -> str:
    return f"ifrc:rate:{user_id}:{int(time.time() // 60)}"


def _allow_ifrc_request(user_id: str, per_minute: int) -> bool:
    key = _ifrc_rate_limit_key(user_id)
    if cache.add(key, 1, timeout=70):
        return True
    try:
        current = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=70)
        current = 1
    return int(current) <= int(per_minute)


# ---------------------------------------------------------------------------
# List + Create
# ---------------------------------------------------------------------------

@api_view(["GET", "POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def master_list_create(request, table_key: str):
    cfg, err = _validate_table_key(table_key)
    if err:
        return err

    if request.method == "GET":
        return _handle_list(request, cfg)
    return _handle_create(request, cfg)


master_list_create.required_permission = {
    "GET": PERM_MASTERDATA_VIEW,
    "POST": PERM_MASTERDATA_CREATE,
}


def _handle_list(request, cfg):
    status_filter = request.query_params.get("status")
    search = request.query_params.get("search")
    order_by = request.query_params.get("order_by")
    try:
        limit = int(request.query_params.get("limit", DEFAULT_PAGE_LIMIT))
        limit = max(MIN_PAGE_LIMIT, min(limit, MAX_PAGE_LIMIT))
        offset = max(int(request.query_params.get("offset", 0)), 0)
    except (ValueError, TypeError):
        limit, offset = DEFAULT_PAGE_LIMIT, 0

    rows, total, warnings = list_records(
        cfg.key,
        status_filter=status_filter,
        search=search,
        order_by=order_by,
        limit=limit,
        offset=offset,
    )
    return Response({
        "results": rows,
        "count": total,
        "limit": limit,
        "offset": offset,
        "warnings": warnings,
    })


def _handle_create(request, cfg):
    data = request.data or {}
    errors = validate_record(cfg, data, is_update=False)
    if errors:
        return Response({"errors": errors}, status=400)

    pk_val, warnings = create_record(cfg.key, data, _actor_id(request))
    if pk_val is None:
        return Response(
            {"detail": "Failed to create record.", "warnings": warnings},
            status=500,
        )

    # Fetch the newly created record to return it
    record, _ = get_record(cfg.key, pk_val)
    _link_ifrc_selection_if_present(
        request_data=data,
        actor_id=_actor_id(request),
        table_key=cfg.key,
        record=record,
        warnings=warnings,
    )
    return Response({"record": record, "warnings": warnings}, status=201)


# ---------------------------------------------------------------------------
# Detail + Update
# ---------------------------------------------------------------------------

@api_view(["GET", "PATCH"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def master_detail_update(request, table_key: str, pk: str):
    cfg, err = _validate_table_key(table_key)
    if err:
        return err

    pk_value = _coerce_pk(cfg, pk)

    if request.method == "GET":
        return _handle_detail(cfg, pk_value)
    return _handle_update(request, cfg, pk_value)


master_detail_update.required_permission = {
    "GET": PERM_MASTERDATA_VIEW,
    "PATCH": PERM_MASTERDATA_EDIT,
}


def _coerce_pk(cfg, pk_str: str) -> Any:
    pk_def = cfg._pk_def
    if pk_def and pk_def.db_type in ("int", "smallint"):
        try:
            return int(pk_str)
        except (ValueError, TypeError):
            pass
    return pk_str


def _handle_detail(cfg, pk_value):
    record, warnings = get_record(cfg.key, pk_value)
    if record is None:
        return Response({"detail": "Not found."}, status=404)
    return Response({"record": record, "warnings": warnings})


def _handle_update(request, cfg, pk_value):
    data = request.data or {}
    expected_version = data.pop("version_nbr", None)
    if expected_version is not None:
        try:
            expected_version = int(expected_version)
        except (ValueError, TypeError):
            expected_version = None

    existing_record = None
    if cfg.key == "items" and (
        "issuance_order" in data or "can_expire_flag" in data
    ):
        existing_record, read_warnings = get_record(cfg.key, pk_value)
        if existing_record is None:
            if "db_error" in read_warnings:
                return Response(
                    {"detail": "Failed to load record for validation.", "warnings": read_warnings},
                    status=500,
                )
            return Response({"detail": "Not found."}, status=404)

    errors = validate_record(
        cfg,
        data,
        is_update=True,
        current_pk=pk_value,
        existing_record=existing_record,
    )
    if errors:
        return Response({"errors": errors}, status=400)

    success, warnings = update_record(
        cfg.key, pk_value, data, _actor_id(request), expected_version,
    )
    if not success:
        if "version_conflict" in warnings:
            return Response(
                {"detail": "Record was modified by another user. Please reload.", "warnings": warnings},
                status=409,
            )
        if "not_found" in warnings:
            return Response({"detail": "Not found."}, status=404)
        return Response({"detail": "Update failed.", "warnings": warnings}, status=500)

    record, _ = get_record(cfg.key, pk_value)
    _link_ifrc_selection_if_present(
        request_data=data,
        actor_id=_actor_id(request),
        table_key=cfg.key,
        record=record,
        warnings=warnings,
    )
    return Response({"record": record, "warnings": warnings})


def _link_ifrc_selection_if_present(
    *,
    request_data: dict[str, Any],
    actor_id: str,
    table_key: str,
    record: dict[str, Any] | None,
    warnings: list[str],
) -> None:
    """
    If an item save includes `ifrc_suggest_log_id`, link the saved item_code
    back to that suggestion log row for audit traceability.
    """
    if table_key != "items" or not record:
        return

    suggestion_id = request_data.get("ifrc_suggest_log_id")
    if suggestion_id in (None, ""):
        return

    item_code = str(record.get("item_code") or "").strip().upper()
    if not item_code:
        return

    try:
        updated = ItemIfrcSuggestLog.objects.filter(
            pk=suggestion_id,
            user_id=actor_id,
        ).update(selected_code=item_code[:30])
        if updated == 0:
            warnings.append("ifrc_log_not_linked")
    except Exception as exc:
        logger.warning("Failed to link IFRC suggestion log %r: %s", suggestion_id, exc)
        warnings.append("ifrc_log_link_failed")


# ---------------------------------------------------------------------------
# Summary counts
# ---------------------------------------------------------------------------

@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def master_summary(request, table_key: str):
    cfg, err = _validate_table_key(table_key)
    if err:
        return err
    counts, warnings = get_summary_counts(cfg.key)
    return Response({"counts": counts, "warnings": warnings})


master_summary.required_permission = PERM_MASTERDATA_VIEW


# ---------------------------------------------------------------------------
# Lookup (FK dropdown data)
# ---------------------------------------------------------------------------

@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def master_lookup(request, table_key: str):
    cfg, err = _validate_table_key(table_key)
    if err:
        return err
    active_only = request.query_params.get("active_only", "true").lower() != "false"
    items, warnings = get_lookup(cfg.key, active_only=active_only)
    return Response({"items": items, "warnings": warnings})


master_lookup.required_permission = PERM_MASTERDATA_VIEW


# ---------------------------------------------------------------------------
# IFRC Suggest / Health
# ---------------------------------------------------------------------------


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def ifrc_suggest(request):
    cfg = _ifrc_cfg()
    if not cfg["IFRC_ENABLED"]:
        return Response({"detail": "IFRC suggestion service is disabled."}, status=503)

    user_id = _actor_id(request)
    if not _allow_ifrc_request(user_id, cfg["RATE_LIMIT_PER_MINUTE"]):
        return Response({"detail": "Rate limit exceeded."}, status=429)

    raw_name = str(request.query_params.get("name", "")).strip()
    if len(raw_name) < cfg["MIN_INPUT_LENGTH"]:
        return Response(
            {"error": f"'name' must be at least {cfg['MIN_INPUT_LENGTH']} characters."},
            status=400,
        )
    if len(raw_name) > cfg["MAX_INPUT_LENGTH"]:
        return Response(
            {"error": f"'name' must not exceed {cfg['MAX_INPUT_LENGTH']} characters."},
            status=400,
        )

    sanitized_name = _SAFE_INPUT_RE.sub("", raw_name).strip()
    if not sanitized_name:
        return Response({"error": "Input contains no usable characters."}, status=400)

    # Optional hint params: fold into item name for v4 agent's single-input pipeline
    size_weight = _SAFE_INPUT_RE.sub("", str(request.query_params.get("size_weight", ""))).strip()[:20]
    form = _SAFE_INPUT_RE.sub("", str(request.query_params.get("form", ""))).strip()[:20]
    material = _SAFE_INPUT_RE.sub("", str(request.query_params.get("material", ""))).strip()[:30]

    # Build combined input (v4 classify from name alone; extra hints improve results)
    combined_name = sanitized_name
    for hint in (size_weight, form, material):
        if hint:
            combined_name = f"{combined_name} {hint}"
    combined_name = combined_name.strip()

    suggestion = _ifrc_agent().generate(combined_name)
    suggestion_id = _write_ifrc_audit_log(
        item_name_input=sanitized_name,
        suggestion=suggestion,
        user_id=user_id,
    )

    response_payload = {
        "suggestion_id": str(suggestion_id) if suggestion_id is not None else None,
        # Map v4 field names to existing API field names for backward compatibility
        "ifrc_code": suggestion.item_code,
        "ifrc_description": suggestion.standardised_name,
        "confidence": suggestion.confidence,
        "match_type": suggestion.match_type,
        "construction_rationale": suggestion.construction_rationale,
        "group_code": suggestion.grp or "",
        "family_code": suggestion.fam or "",
        "category_code": suggestion.cat or "",
        "spec_segment": suggestion.spec_seg or "",
        "sequence": suggestion.seq or 0,
        "auto_fill_threshold": cfg["AUTO_FILL_CONFIDENCE_THRESHOLD"],
    }

    serializer = IFRCSuggestionResponseSerializer(response_payload)
    return Response(serializer.data, status=200)


ifrc_suggest.required_permission = PERM_MASTERDATA_VIEW


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def ifrc_health(request):
    cfg = _ifrc_cfg()
    breaker_open = cb_is_open()
    status = "healthy" if cfg["IFRC_ENABLED"] and not breaker_open else "degraded"

    return Response(
        {
            "status": status,
            "ifrc_enabled": cfg["IFRC_ENABLED"],
            "llm_enabled": cfg["LLM_ENABLED"],
            "llm_circuit_breaker_open": breaker_open,
            "model_id": cfg["OLLAMA_MODEL_ID"],
        },
        status=200 if status == "healthy" else 206,
    )


ifrc_health.required_permission = PERM_MASTERDATA_VIEW


def _write_ifrc_audit_log(
    *,
    item_name_input: str,
    suggestion: IFRCCodeSuggestion,
    user_id: str,
) -> int | None:
    try:
        row = ItemIfrcSuggestLog.objects.create(
            item_name_input=item_name_input[:120],
            suggested_code=(suggestion.item_code or "")[:30],
            suggested_desc=(suggestion.standardised_name or "")[:120],
            confidence=suggestion.confidence,
            match_type=(suggestion.match_type or "none")[:20],
            construction_rationale=(suggestion.construction_rationale or "")[:4000],
            user_id=user_id[:50],
        )
        return int(row.pk)
    except Exception as exc:
        logger.warning("Failed to write IFRC audit log for user %s: %s", user_id, exc)
        return None


# ---------------------------------------------------------------------------
# Inactivate / Activate
# ---------------------------------------------------------------------------

@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def master_inactivate(request, table_key: str, pk: str):
    cfg, err = _validate_table_key(table_key)
    if err:
        return err
    if not cfg.has_status:
        return Response({"detail": "This table does not support status changes."}, status=400)
    pk_value = _coerce_pk(cfg, pk)

    # Check dependencies first
    blocking, dep_warnings = check_dependencies(cfg.key, pk_value)
    if blocking:
        return Response({
            "detail": "Cannot inactivate: referenced by other records.",
            "blocking": blocking,
            "warnings": dep_warnings,
        }, status=409)

    expected_version = (request.data or {}).get("version_nbr")
    if expected_version is not None:
        try:
            expected_version = int(expected_version)
        except (ValueError, TypeError):
            expected_version = None

    success, warnings = inactivate_record(
        cfg.key, pk_value, _actor_id(request), expected_version,
    )
    if not success:
        if "version_conflict" in warnings:
            return Response(
                {"detail": "Record was modified by another user.", "warnings": warnings},
                status=409,
            )
        return Response({"detail": "Inactivation failed.", "warnings": warnings}, status=500)

    record, _ = get_record(cfg.key, pk_value)
    return Response({"record": record, "warnings": warnings})


master_inactivate.required_permission = PERM_MASTERDATA_INACTIVATE


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def master_activate(request, table_key: str, pk: str):
    cfg, err = _validate_table_key(table_key)
    if err:
        return err
    if not cfg.has_status:
        return Response({"detail": "This table does not support status changes."}, status=400)
    pk_value = _coerce_pk(cfg, pk)

    expected_version = (request.data or {}).get("version_nbr")
    if expected_version is not None:
        try:
            expected_version = int(expected_version)
        except (ValueError, TypeError):
            expected_version = None

    success, warnings = activate_record(
        cfg.key, pk_value, _actor_id(request), expected_version,
    )
    if not success:
        if "version_conflict" in warnings:
            return Response(
                {"detail": "Record was modified by another user.", "warnings": warnings},
                status=409,
            )
        return Response({"detail": "Activation failed.", "warnings": warnings}, status=500)

    record, _ = get_record(cfg.key, pk_value)
    return Response({"record": record, "warnings": warnings})


master_activate.required_permission = PERM_MASTERDATA_EDIT


for _view in (
    master_list_create,
    master_detail_update,
    master_summary,
    master_lookup,
    ifrc_suggest,
    ifrc_health,
    master_inactivate,
    master_activate,
):
    if hasattr(_view, "cls"):
        _view.cls.required_permission = _view.required_permission
