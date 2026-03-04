"""
Generic API views for master data CRUD.

All endpoints are parameterized by ``table_key`` which maps to a
``TableConfig`` in the registry.
"""
from __future__ import annotations

import logging
from typing import Any

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from api.authentication import LegacyCompatAuthentication
from masterdata.permissions import (
    MasterDataPermission,
    PERM_MASTERDATA_CREATE,
    PERM_MASTERDATA_EDIT,
    PERM_MASTERDATA_INACTIVATE,
    PERM_MASTERDATA_VIEW,
)
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


def _actor_id(request) -> str:
    return str(getattr(request.user, "user_id", "system"))


def _validate_table_key(table_key: str):
    cfg = get_table_config(table_key)
    if cfg is None:
        return None, Response({"detail": f"Unknown table: {table_key}"}, status=404)
    return cfg, None


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

    errors = validate_record(cfg, data, is_update=True, current_pk=pk_value)
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
    return Response({"record": record, "warnings": warnings})


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
    master_inactivate,
    master_activate,
):
    if hasattr(_view, "cls"):
        _view.cls.required_permission = _view.required_permission
