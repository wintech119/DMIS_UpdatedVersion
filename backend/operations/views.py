from __future__ import annotations

import logging
import math
import time
import uuid
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.cache import cache
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response

from api.authentication import LegacyCompatAuthentication
from api.rbac import (
    PERM_NATIONAL_ACT_CROSS_TENANT,
    PERM_OPERATIONS_CONSOLIDATION_DISPATCH,
    PERM_OPERATIONS_CONSOLIDATION_RECEIVE,
    PERM_OPERATIONS_DISPATCH_EXECUTE,
    PERM_OPERATIONS_DISPATCH_PREPARE,
    PERM_OPERATIONS_ELIGIBILITY_APPROVE,
    PERM_OPERATIONS_ELIGIBILITY_REJECT,
    PERM_OPERATIONS_ELIGIBILITY_REVIEW,
    PERM_OPERATIONS_PARTIAL_RELEASE_APPROVE,
    PERM_OPERATIONS_PARTIAL_RELEASE_REQUEST,
    PERM_OPERATIONS_PICKUP_RELEASE,
    PERM_OPERATIONS_NOTIFICATION_RECEIVE,
    PERM_OPERATIONS_PACKAGE_ALLOCATE,
    PERM_OPERATIONS_PACKAGE_CREATE,
    PERM_OPERATIONS_PACKAGE_LOCK,
    PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE,
    PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST,
    PERM_OPERATIONS_QUEUE_VIEW,
    PERM_OPERATIONS_RECEIPT_CONFIRM,
    PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE,
    PERM_OPERATIONS_REQUEST_CREATE_ON_BEHALF_BRIDGE,
    PERM_OPERATIONS_REQUEST_CREATE_SELF,
    PERM_OPERATIONS_REQUEST_EDIT_DRAFT,
    PERM_OPERATIONS_REQUEST_SUBMIT,
    PERM_OPERATIONS_WAYBILL_VIEW,
    resolve_roles_and_permissions,
)
from api.tenancy import resolve_tenant_context
from operations import contract_services as operations_service
from operations.constants import (
    ROLE_LOGISTICS_MANAGER,
    ROLE_LOGISTICS_OFFICER,
    normalize_role_codes,
)
from operations.exceptions import OperationValidationError
from operations.permissions import OperationsPermission
from replenishment.services.allocation_dispatch import (
    DispatchError,
    OptimisticLockError,
    OverrideApprovalError,
    ReservationError,
)
from replenishment.services import data_access
from replenishment.views import _parse_positive_int

logger = logging.getLogger("dmis.security")
_RATE_LIMIT_WINDOW_SECONDS = 60
_WRITE_LIMIT_PER_MINUTE = 40
_HIGH_RISK_LIMIT_PER_MINUTE = 10
_WORKFLOW_LIMIT_PER_MINUTE = 15
_RATE_LIMIT_CACHE_TIMEOUT_SECONDS = _RATE_LIMIT_WINDOW_SECONDS + 5
_RATE_LIMIT_LOCK_TIMEOUT_SECONDS = 5
_RATE_LIMIT_LOCK_WAIT_SECONDS = 0.01
_RATE_LIMIT_LOCK_ATTEMPTS = 20
_SURGE_PHASES = {"SURGE", "STABILIZED"}
_MAX_ID_LIST_ITEMS = 100
_MAX_ITEM_PREVIEW_DRAFT_ALLOCATIONS = 200
_SURGE_ROLE_CODES = {
    ROLE_LOGISTICS_OFFICER,
    ROLE_LOGISTICS_MANAGER,
    "AGENCY_DISTRIBUTOR",
}


def _actor_id(request) -> str:
    actor_id = getattr(request.user, "user_id", None) or getattr(request.user, "username", None)
    if actor_id in (None, ""):
        raise AuthenticationFailed("Authenticated operations requests require a stable actor identifier.")
    return str(actor_id)


def _tenant_context(request):
    cached = getattr(request, "_operations_tenant_context_cache", None)
    if cached is not None:
        return cached

    _, permissions = resolve_roles_and_permissions(request, request.user)
    cached = resolve_tenant_context(request, request.user, permissions)
    request._operations_tenant_context_cache = cached
    return cached


def _roles(request) -> list[str]:
    roles, _ = resolve_roles_and_permissions(request, request.user)
    return roles


def _permissions(request) -> list[str]:
    _, permissions = resolve_roles_and_permissions(request, request.user)
    return permissions


def _service_error_response(exc: Exception) -> Response:
    if isinstance(exc, OperationValidationError):
        normalized_errors = {
            str(field_name).strip().lower(): str(message).strip().lower()
            for field_name, message in exc.errors.items()
        }
        scope_message = normalized_errors.get("tenant_scope") or normalized_errors.get(
            "scope"
        )
        if scope_message == "request is outside the active tenant or workflow assignment scope.":
            return Response({"detail": "Not found."}, status=404)
        return Response({"errors": exc.errors}, status=400)
    if isinstance(exc, OverrideApprovalError):
        return Response({"errors": {"override": exc.message}}, status=400)
    if isinstance(exc, ReservationError):
        return Response({"errors": {"allocations": str(exc)}}, status=409)
    if isinstance(exc, OptimisticLockError):
        return Response({"errors": {"version": exc.message}}, status=409)
    if isinstance(exc, DispatchError):
        return Response({"errors": {"dispatch": exc.message}}, status=409)
    raise exc


def _request_ip(request) -> str:
    # X-Forwarded-For is intentionally ignored until DMIS has an explicit
    # trusted-proxy allowlist. For authenticated requests, IP is only a
    # secondary abuse signal and must not be client-spoofable.
    remote_addr = str(request.META.get("REMOTE_ADDR", "")).strip()
    return remote_addr or "unknown"


def _rate_limit_keys(request, scope: str) -> tuple[str, str | None, str, str]:
    actor_id = _actor_id(request)
    tenant_context = _tenant_context(request)
    tenant_id = (
        getattr(tenant_context, "active_tenant_id", None)
        or getattr(tenant_context, "requested_tenant_id", None)
        or "unknown"
    )
    primary_key = f"ops:rate:{scope}:{actor_id}:{tenant_id}"
    client_ip = _request_ip(request) if getattr(request.user, "is_authenticated", False) else "unknown"
    secondary_key = None
    if client_ip and client_ip != "unknown":
        secondary_key = f"{primary_key}:ip:{client_ip}"
    return primary_key, secondary_key, actor_id, str(tenant_id)


def _scaled_rate_limit(request, base_limit: int) -> int:
    normalized_roles = set(normalize_role_codes(_roles(request)))
    permission_set = {str(permission).strip().lower() for permission in _permissions(request)}
    has_surge_override = bool(normalized_roles & _SURGE_ROLE_CODES) or (
        PERM_NATIONAL_ACT_CROSS_TENANT.lower() in permission_set
    )
    if not has_surge_override:
        return base_limit

    active_event = data_access.get_active_event() or {}
    phase = str(active_event.get("phase", "")).strip().upper()
    if phase in _SURGE_PHASES:
        return base_limit * 2
    return base_limit


def _acquire_rate_limit_lock(lock_key: str) -> str | None:
    for _ in range(_RATE_LIMIT_LOCK_ATTEMPTS):
        owner_token = str(uuid.uuid4())
        if cache.add(lock_key, owner_token, timeout=_RATE_LIMIT_LOCK_TIMEOUT_SECONDS):
            return owner_token
        time.sleep(_RATE_LIMIT_LOCK_WAIT_SECONDS)
    return None


def _release_rate_limit_lock(lock_key: str, owner_token: str | None) -> None:
    if not owner_token:
        return
    if cache.get(lock_key) == owner_token:
        cache.delete(lock_key)


def _rate_limit_response(
    request,
    *,
    scope: str,
    limit: int,
    window_seconds: int = _RATE_LIMIT_WINDOW_SECONDS,
) -> Response | None:
    cache_key, secondary_cache_key, actor_id, tenant_id = _rate_limit_keys(request, scope)
    client_ip = _request_ip(request)
    effective_limit = _scaled_rate_limit(request, limit)
    now = time.time()
    lock_key = f"{cache_key}:lock"
    if secondary_cache_key is not None:
        cache.set(secondary_cache_key, {"client_ip": client_ip, "updated_at": now}, timeout=_RATE_LIMIT_CACHE_TIMEOUT_SECONDS)

    lock_owner_token = _acquire_rate_limit_lock(lock_key)
    if not lock_owner_token:
        logger.warning(
            "operations.rate_limit_lock_timeout",
            extra={
                "event": "operations.rate_limit_lock_timeout",
                "scope": scope,
                "actor_id": actor_id,
                "tenant_id": tenant_id,
                "client_ip": client_ip,
            },
        )
        response = Response({"detail": "Rate limit exceeded."}, status=429)
        response["Retry-After"] = "1"
        return response

    try:
        bucket = cache.get(cache_key, {})
        if not isinstance(bucket, dict):
            bucket = {}
        refill_rate = effective_limit / float(window_seconds)
        previous_updated_at = bucket.get("updated_at", now)
        try:
            updated_at = float(previous_updated_at)
        except (TypeError, ValueError):
            updated_at = now
        elapsed = max(0.0, now - updated_at)
        try:
            current_tokens = float(bucket.get("tokens", effective_limit))
        except (TypeError, ValueError):
            current_tokens = float(effective_limit)
        tokens = min(float(effective_limit), current_tokens + (elapsed * refill_rate))

        if tokens < 1.0:
            retry_after = max(1, math.ceil((1.0 - tokens) / refill_rate))
            cache.set(
                cache_key,
                {"tokens": tokens, "updated_at": now},
                timeout=_RATE_LIMIT_CACHE_TIMEOUT_SECONDS,
            )
            logger.warning(
                "operations.rate_limit_exceeded",
                extra={
                    "event": "operations.rate_limit_exceeded",
                    "scope": scope,
                    "actor_id": actor_id,
                    "tenant_id": tenant_id,
                    "client_ip": client_ip,
                    "base_limit": limit,
                    "effective_limit": effective_limit,
                    "window_seconds": window_seconds,
                },
            )
            response = Response({"detail": "Rate limit exceeded."}, status=429)
            response["Retry-After"] = str(retry_after)
            return response

        cache.set(
            cache_key,
            {"tokens": tokens - 1.0, "updated_at": now},
            timeout=_RATE_LIMIT_CACHE_TIMEOUT_SECONDS,
        )
        return None
    finally:
        _release_rate_limit_lock(lock_key, lock_owner_token)


def _required_idempotency_key(request) -> str:
    idempotency_key = str(request.headers.get("Idempotency-Key", "")).strip()
    if not idempotency_key:
        raise OperationValidationError({"idempotency_key": "Idempotency-Key header is required."})
    return idempotency_key


def _cached_idempotent_response(
    *,
    endpoint: str,
    resource_id: int,
    actor_id: str,
    tenant_context,
    idempotency_key: str,
) -> Response | None:
    cached_result = operations_service.peek_idempotent_response(
        endpoint=endpoint,
        actor_id=actor_id,
        tenant_context=tenant_context,
        resource_id=resource_id,
        idempotency_key=idempotency_key,
    )
    if cached_result is None:
        return None
    return Response(cached_result)


def _optional_positive_int_query_param(raw_value: str | None, field_name: str) -> int | None:
    if raw_value in (None, ""):
        return None
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise OperationValidationError({field_name: "Must be a positive integer."}) from exc
    if parsed <= 0:
        raise OperationValidationError({field_name: "Must be a positive integer."})
    return parsed


def _positive_int_query_param_list(raw_values: object, field_name: str) -> list[int]:
    if not isinstance(raw_values, list):
        raise OperationValidationError({field_name: f"{field_name} must be provided as an array."})
    if len(raw_values) > _MAX_ID_LIST_ITEMS:
        raise OperationValidationError(
            {field_name: f"{field_name} must not contain more than {_MAX_ID_LIST_ITEMS} items."}
        )
    normalized: list[int] = []
    seen: set[int] = set()
    for index, raw_value in enumerate(raw_values):
        errors: dict[str, str] = {}
        parsed = _parse_positive_int(raw_value, f"{field_name}[{index}]", errors)
        if errors or parsed is None:
            raise OperationValidationError(errors)
        if parsed in seen:
            continue
        seen.add(parsed)
        normalized.append(parsed)
    return normalized


def _required_positive_int_payload_value(raw_value: object, field_name: str) -> int:
    if raw_value in (None, ""):
        raise OperationValidationError({field_name: f"{field_name} is required."})
    if isinstance(raw_value, bool):
        raise OperationValidationError({field_name: "Must be a positive integer."})
    if isinstance(raw_value, int):
        parsed = raw_value
    elif isinstance(raw_value, str):
        normalized = raw_value.strip()
        if not normalized or not normalized.isdigit():
            raise OperationValidationError({field_name: "Must be a positive integer."})
        parsed = int(normalized)
    else:
        raise OperationValidationError({field_name: "Must be a positive integer."})
    if parsed <= 0:
        raise OperationValidationError({field_name: "Must be a positive integer."})
    return parsed


def _validated_item_preview_draft_allocations(raw_value: object) -> list[dict[str, Any]]:
    if raw_value in (None, ""):
        return []
    if not isinstance(raw_value, list):
        raise OperationValidationError({"draft_allocations": "draft_allocations must be provided as an array."})
    if len(raw_value) > _MAX_ITEM_PREVIEW_DRAFT_ALLOCATIONS:
        raise OperationValidationError(
            {
                "draft_allocations": (
                    f"draft_allocations must contain no more than "
                    f"{_MAX_ITEM_PREVIEW_DRAFT_ALLOCATIONS} entries."
                )
            }
        )

    errors: dict[str, str] = {}
    normalized_rows: list[dict[str, Any]] = []
    for index, raw_row in enumerate(raw_value):
        field_prefix = f"draft_allocations[{index}]"
        if not isinstance(raw_row, Mapping):
            errors[field_prefix] = "Each draft allocation must be an object."
            continue

        missing_fields = [
            field_name
            for field_name in ("item_id", "inventory_id", "batch_id", "quantity")
            if raw_row.get(field_name) in (None, "")
        ]
        if missing_fields:
            errors[field_prefix] = f"Missing required field(s): {', '.join(missing_fields)}."
            continue

        quantity_text = str(raw_row.get("quantity")).strip()
        try:
            quantity = Decimal(quantity_text)
        except (ArithmeticError, InvalidOperation, ValueError):
            errors[f"{field_prefix}.quantity"] = "Must be a decimal number."
            continue
        if quantity <= 0:
            errors[f"{field_prefix}.quantity"] = "Must be greater than zero."
            continue

        normalized_row = dict(raw_row)
        for field_name in ("item_id", "inventory_id", "batch_id"):
            try:
                normalized_row[field_name] = _required_positive_int_payload_value(
                    raw_row.get(field_name),
                    f"{field_prefix}.{field_name}",
                )
            except OperationValidationError as exc:
                errors.update(exc.errors)

        if raw_row.get("source_record_id") not in (None, ""):
            try:
                normalized_row["source_record_id"] = _required_positive_int_payload_value(
                    raw_row.get("source_record_id"),
                    f"{field_prefix}.source_record_id",
                )
            except OperationValidationError as exc:
                errors.update(exc.errors)

        normalized_rows.append(normalized_row)

    if errors:
        raise OperationValidationError(errors)
    return normalized_rows


def _validated_positive_int_payload_list(raw_value: object, field_name: str) -> list[int]:
    if raw_value in (None, ""):
        return []
    if not isinstance(raw_value, list):
        raise OperationValidationError({field_name: f"{field_name} must be provided as an array."})
    if len(raw_value) > _MAX_ID_LIST_ITEMS:
        raise OperationValidationError(
            {field_name: f"{field_name} must not contain more than {_MAX_ID_LIST_ITEMS} items."}
        )
    normalized: list[int] = []
    seen: set[int] = set()
    for index, raw_entry in enumerate(raw_value):
        errors: dict[str, str] = {}
        parsed = _parse_positive_int(raw_entry, f"{field_name}[{index}]", errors)
        if errors or parsed is None:
            raise OperationValidationError(errors)
        if parsed in seen:
            continue
        seen.add(parsed)
        normalized.append(parsed)
    return normalized


def _payload_object(payload: object) -> dict[str, Any]:
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise OperationValidationError({"body": "Request body must be a JSON object."})
    return dict(payload)


def _boolean_payload_flag(payload: object, field_name: str, *, default: bool = False) -> bool:
    raw_value = _payload_object(payload).get(field_name, default)
    if isinstance(raw_value, bool):
        return raw_value
    if raw_value in (None, ""):
        return default
    normalized = str(raw_value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise OperationValidationError({field_name: f"{field_name} must be true or false."})


@api_view(["GET", "POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_requests(request):
    try:
        if request.method == "GET":
            return Response(
                operations_service.list_requests(
                    filter_key=request.query_params.get("filter"),
                    actor_id=_actor_id(request),
                    tenant_context=_tenant_context(request),
                    actor_roles=_roles(request),
                )
            )
        rate_limited = _rate_limit_response(
            request,
            scope="request_create",
            limit=_WRITE_LIMIT_PER_MINUTE,
        )
        if rate_limited is not None:
            return rate_limited
        return Response(
            operations_service.create_request(
                payload=_payload_object(request.data),
                actor_id=_actor_id(request),
                tenant_context=_tenant_context(request),
                permissions=_permissions(request),
                actor_roles=_roles(request),
            ),
            status=201,
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_requests.required_permission = {
    "GET": [PERM_OPERATIONS_QUEUE_VIEW, PERM_OPERATIONS_REQUEST_SUBMIT, PERM_OPERATIONS_REQUEST_EDIT_DRAFT],
    "POST": [
        PERM_OPERATIONS_REQUEST_CREATE_SELF,
        PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE,
        PERM_OPERATIONS_REQUEST_CREATE_ON_BEHALF_BRIDGE,
    ],
}


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_request_reference_data(request):
    try:
        return Response(
            operations_service.get_request_reference_data(
                tenant_context=_tenant_context(request),
                permissions=_permissions(request),
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_request_reference_data.required_permission = [
    PERM_OPERATIONS_REQUEST_CREATE_SELF,
    PERM_OPERATIONS_REQUEST_CREATE_FOR_SUBORDINATE,
    PERM_OPERATIONS_REQUEST_CREATE_ON_BEHALF_BRIDGE,
    PERM_OPERATIONS_REQUEST_EDIT_DRAFT,
]


@api_view(["GET", "PATCH"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_request_detail(request, reliefrqst_id: int):
    try:
        if request.method == "GET":
            return Response(
                operations_service.get_request(
                    reliefrqst_id,
                    actor_id=_actor_id(request),
                    tenant_context=_tenant_context(request),
                    actor_roles=_roles(request),
                )
            )
        rate_limited = _rate_limit_response(
            request,
            scope="request_update",
            limit=_WRITE_LIMIT_PER_MINUTE,
        )
        if rate_limited is not None:
            return rate_limited
        return Response(
            operations_service.update_request(
                reliefrqst_id,
                payload=_payload_object(request.data),
                actor_id=_actor_id(request),
                tenant_context=_tenant_context(request),
                permissions=_permissions(request),
                actor_roles=_roles(request),
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_request_detail.required_permission = {
    "GET": [PERM_OPERATIONS_QUEUE_VIEW, PERM_OPERATIONS_REQUEST_SUBMIT, PERM_OPERATIONS_REQUEST_EDIT_DRAFT],
    "PATCH": [PERM_OPERATIONS_REQUEST_EDIT_DRAFT],
}


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_request_submit(request, reliefrqst_id: int):
    try:
        idempotency_key = _required_idempotency_key(request)
        actor_id = _actor_id(request)
        tenant_context = _tenant_context(request)
        cached_response = _cached_idempotent_response(
            endpoint="request_submit",
            resource_id=reliefrqst_id,
            actor_id=actor_id,
            tenant_context=tenant_context,
            idempotency_key=idempotency_key,
        )
        if cached_response is not None:
            return cached_response
        rate_limited = _rate_limit_response(
            request,
            scope="request_submit",
            limit=_WORKFLOW_LIMIT_PER_MINUTE,
        )
        if rate_limited is not None:
            return rate_limited
        return Response(
            operations_service.submit_request(
                reliefrqst_id,
                actor_id=actor_id,
                tenant_context=tenant_context,
                idempotency_key=idempotency_key,
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_request_submit.required_permission = PERM_OPERATIONS_REQUEST_SUBMIT


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_eligibility_queue(request):
    try:
        return Response(
            operations_service.list_eligibility_queue(
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_eligibility_queue.required_permission = PERM_OPERATIONS_ELIGIBILITY_REVIEW


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_eligibility_detail(request, reliefrqst_id: int):
    try:
        return Response(
            operations_service.get_eligibility_request(
                reliefrqst_id,
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_eligibility_detail.required_permission = PERM_OPERATIONS_ELIGIBILITY_REVIEW


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_eligibility_decision(request, reliefrqst_id: int):
    try:
        idempotency_key = _required_idempotency_key(request)
        actor_id = _actor_id(request)
        tenant_context = _tenant_context(request)
        cached_response = _cached_idempotent_response(
            endpoint="eligibility_decision",
            resource_id=reliefrqst_id,
            actor_id=actor_id,
            tenant_context=tenant_context,
            idempotency_key=idempotency_key,
        )
        if cached_response is not None:
            return cached_response
        rate_limited = _rate_limit_response(
            request,
            scope="eligibility_decision",
            limit=_WORKFLOW_LIMIT_PER_MINUTE,
        )
        if rate_limited is not None:
            return rate_limited
        return Response(
            operations_service.submit_eligibility_decision(
                reliefrqst_id,
                payload=_payload_object(request.data),
                actor_id=actor_id,
                actor_roles=_roles(request),
                tenant_context=tenant_context,
                idempotency_key=idempotency_key,
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_eligibility_decision.required_permission = [PERM_OPERATIONS_ELIGIBILITY_APPROVE, PERM_OPERATIONS_ELIGIBILITY_REJECT]


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_packages_queue(request):
    try:
        return Response(
            operations_service.list_packages(
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_packages_queue.required_permission = [PERM_OPERATIONS_PACKAGE_CREATE, PERM_OPERATIONS_PACKAGE_ALLOCATE, PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE]


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_package_current(request, reliefrqst_id: int):
    try:
        return Response(
            operations_service.get_package(
                reliefrqst_id,
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_package_current.required_permission = [PERM_OPERATIONS_PACKAGE_CREATE, PERM_OPERATIONS_PACKAGE_ALLOCATE, PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE]


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_package_staging_recommendation(request, reliefrqst_id: int):
    try:
        return Response(
            operations_service.get_staging_recommendation(
                reliefrqst_id,
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_package_staging_recommendation.required_permission = [
    PERM_OPERATIONS_PACKAGE_CREATE,
    PERM_OPERATIONS_PACKAGE_ALLOCATE,
]


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_package_draft(request, reliefrqst_id: int):
    try:
        payload = _payload_object(request.data)
        payload["draft_save"] = True
        return Response(
            operations_service.save_package(
                reliefrqst_id,
                payload=payload,
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
                permissions=_permissions(request),
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_package_draft.required_permission = [PERM_OPERATIONS_PACKAGE_CREATE, PERM_OPERATIONS_PACKAGE_LOCK]


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_package_unlock(request, reliefrqst_id: int):
    try:
        payload = _payload_object(request.data)
        permissions = {str(permission).strip().lower() for permission in _permissions(request)}
        force = _boolean_payload_flag(payload, "force", default=False)
        if force and PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE.lower() not in permissions:
            return Response(
                {
                    "errors": {
                        "force": "Override approval permission is required to force-release a package lock."
                    }
                },
                status=403,
            )
        return Response(
            operations_service.release_package_lock(
                reliefrqst_id,
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
                force=force,
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_package_unlock.required_permission = PERM_OPERATIONS_PACKAGE_LOCK


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_package_allocation_options(request, reliefrqst_id: int):
    try:
        source_warehouse_id = request.query_params.get("source_warehouse_id")
        return Response(
            operations_service.get_package_allocation_options(
                reliefrqst_id,
                source_warehouse_id=_optional_positive_int_query_param(source_warehouse_id, "source_warehouse_id"),
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_package_allocation_options.required_permission = PERM_OPERATIONS_PACKAGE_ALLOCATE


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_item_allocation_options(request, reliefrqst_id: int, item_id: int):
    try:
        source_warehouse_id = request.query_params.get("source_warehouse_id")
        additional_warehouse_ids = _positive_int_query_param_list(
            request.query_params.getlist("additional_warehouse_ids"),
            "additional_warehouse_ids",
        )
        if request.query_params.get("draft_allocations") not in (None, ""):
            raise OperationValidationError(
                {"draft_allocations": "Use the preview endpoint for draft-aware allocation guidance."}
            )
        return Response(
            operations_service.get_item_allocation_options(
                reliefrqst_id,
                item_id,
                source_warehouse_id=_optional_positive_int_query_param(source_warehouse_id, "source_warehouse_id"),
                draft_allocations=None,
                additional_warehouse_ids=additional_warehouse_ids,
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_item_allocation_options.required_permission = PERM_OPERATIONS_PACKAGE_ALLOCATE


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_item_allocation_preview(request, reliefrqst_id: int, item_id: int):
    try:
        payload = _payload_object(request.data)
        source_warehouse_id = None
        if payload.get("source_warehouse_id") not in (None, ""):
            source_warehouse_id = _required_positive_int_payload_value(
                payload.get("source_warehouse_id"),
                "source_warehouse_id",
            )
        draft_allocations = _validated_item_preview_draft_allocations(payload.get("draft_allocations", []))
        additional_warehouse_ids = _validated_positive_int_payload_list(
            payload.get("additional_warehouse_ids", []),
            "additional_warehouse_ids",
        )
        normalized_payload = {
            **payload,
            "draft_allocations": draft_allocations,
            "additional_warehouse_ids": additional_warehouse_ids,
        }
        if source_warehouse_id is not None:
            normalized_payload["source_warehouse_id"] = source_warehouse_id
        return Response(
            operations_service.get_item_allocation_preview(
                reliefrqst_id,
                item_id,
                payload=normalized_payload,
                source_warehouse_id=source_warehouse_id,
                draft_allocations=draft_allocations,
                additional_warehouse_ids=additional_warehouse_ids,
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_item_allocation_preview.required_permission = PERM_OPERATIONS_PACKAGE_ALLOCATE


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_package_commit_allocation(request, reliefrqst_id: int):
    try:
        idempotency_key = _required_idempotency_key(request)
        actor_id = _actor_id(request)
        tenant_context = _tenant_context(request)
        cached_response = _cached_idempotent_response(
            endpoint="package_commit_allocation",
            resource_id=reliefrqst_id,
            actor_id=actor_id,
            tenant_context=tenant_context,
            idempotency_key=idempotency_key,
        )
        if cached_response is not None:
            return cached_response
        rate_limited = _rate_limit_response(
            request,
            scope="package_commit_allocation",
            limit=_WORKFLOW_LIMIT_PER_MINUTE,
        )
        if rate_limited is not None:
            return rate_limited
        return Response(
            operations_service.save_package(
                reliefrqst_id,
                payload=_payload_object(request.data),
                actor_id=actor_id,
                actor_roles=_roles(request),
                tenant_context=tenant_context,
                permissions=_permissions(request),
                idempotency_key=idempotency_key,
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_package_commit_allocation.required_permission = [PERM_OPERATIONS_PACKAGE_ALLOCATE, PERM_OPERATIONS_PACKAGE_OVERRIDE_REQUEST]


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_package_override_approve(request, reliefrqst_id: int):
    try:
        idempotency_key = _required_idempotency_key(request)
        actor_id = _actor_id(request)
        tenant_context = _tenant_context(request)
        cached_response = _cached_idempotent_response(
            endpoint="package_override_approve",
            resource_id=reliefrqst_id,
            actor_id=actor_id,
            tenant_context=tenant_context,
            idempotency_key=idempotency_key,
        )
        if cached_response is not None:
            return cached_response
        rate_limited = _rate_limit_response(
            request,
            scope="package_override_approve",
            limit=_WORKFLOW_LIMIT_PER_MINUTE,
        )
        if rate_limited is not None:
            return rate_limited
        return Response(
            operations_service.approve_override(
                reliefrqst_id,
                payload=_payload_object(request.data),
                actor_id=actor_id,
                actor_roles=_roles(request),
                tenant_context=tenant_context,
                idempotency_key=idempotency_key,
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_package_override_approve.required_permission = PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_package_override_return(request, reliefrqst_id: int):
    try:
        idempotency_key = _required_idempotency_key(request)
        actor_id = _actor_id(request)
        tenant_context = _tenant_context(request)
        cached_response = _cached_idempotent_response(
            endpoint="package_override_return",
            resource_id=reliefrqst_id,
            actor_id=actor_id,
            tenant_context=tenant_context,
            idempotency_key=idempotency_key,
        )
        if cached_response is not None:
            return cached_response
        rate_limited = _rate_limit_response(
            request,
            scope="package_override_return",
            limit=_WORKFLOW_LIMIT_PER_MINUTE,
        )
        if rate_limited is not None:
            return rate_limited
        return Response(
            operations_service.return_override(
                reliefrqst_id,
                payload=_payload_object(request.data),
                actor_id=actor_id,
                actor_roles=_roles(request),
                tenant_context=tenant_context,
                idempotency_key=idempotency_key,
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_package_override_return.required_permission = PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_package_override_reject(request, reliefrqst_id: int):
    try:
        idempotency_key = _required_idempotency_key(request)
        actor_id = _actor_id(request)
        tenant_context = _tenant_context(request)
        cached_response = _cached_idempotent_response(
            endpoint="package_override_reject",
            resource_id=reliefrqst_id,
            actor_id=actor_id,
            tenant_context=tenant_context,
            idempotency_key=idempotency_key,
        )
        if cached_response is not None:
            return cached_response
        rate_limited = _rate_limit_response(
            request,
            scope="package_override_reject",
            limit=_WORKFLOW_LIMIT_PER_MINUTE,
        )
        if rate_limited is not None:
            return rate_limited
        return Response(
            operations_service.reject_override(
                reliefrqst_id,
                payload=_payload_object(request.data),
                actor_id=actor_id,
                actor_roles=_roles(request),
                tenant_context=tenant_context,
                idempotency_key=idempotency_key,
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_package_override_reject.required_permission = PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_consolidation_legs(request, reliefpkg_id: int):
    try:
        return Response(
            operations_service.list_consolidation_legs(
                reliefpkg_id,
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_consolidation_legs.required_permission = [
    PERM_OPERATIONS_CONSOLIDATION_DISPATCH,
    PERM_OPERATIONS_CONSOLIDATION_RECEIVE,
]


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_consolidation_leg_dispatch(request, reliefpkg_id: int, leg_id: int):
    try:
        idempotency_key = _required_idempotency_key(request)
        actor_id = _actor_id(request)
        tenant_context = _tenant_context(request)
        cached_response = _cached_idempotent_response(
            endpoint="consolidation_leg_dispatch",
            resource_id=reliefpkg_id,
            actor_id=actor_id,
            tenant_context=tenant_context,
            idempotency_key=idempotency_key,
        )
        if cached_response is not None:
            return cached_response
        rate_limited = _rate_limit_response(
            request,
            scope="consolidation_leg_dispatch",
            limit=_HIGH_RISK_LIMIT_PER_MINUTE,
        )
        if rate_limited is not None:
            return rate_limited
        return Response(
            operations_service.dispatch_consolidation_leg(
                reliefpkg_id,
                leg_id,
                payload=_payload_object(request.data),
                actor_id=actor_id,
                actor_roles=_roles(request),
                tenant_context=tenant_context,
                idempotency_key=idempotency_key,
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_consolidation_leg_dispatch.required_permission = PERM_OPERATIONS_CONSOLIDATION_DISPATCH


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_consolidation_leg_receive(request, reliefpkg_id: int, leg_id: int):
    try:
        idempotency_key = _required_idempotency_key(request)
        actor_id = _actor_id(request)
        tenant_context = _tenant_context(request)
        cached_response = _cached_idempotent_response(
            endpoint="consolidation_leg_receive",
            resource_id=reliefpkg_id,
            actor_id=actor_id,
            tenant_context=tenant_context,
            idempotency_key=idempotency_key,
        )
        if cached_response is not None:
            return cached_response
        rate_limited = _rate_limit_response(
            request,
            scope="consolidation_leg_receive",
            limit=_HIGH_RISK_LIMIT_PER_MINUTE,
        )
        if rate_limited is not None:
            return rate_limited
        return Response(
            operations_service.receive_consolidation_leg(
                reliefpkg_id,
                leg_id,
                payload=_payload_object(request.data),
                actor_id=actor_id,
                actor_roles=_roles(request),
                tenant_context=tenant_context,
                idempotency_key=idempotency_key,
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_consolidation_leg_receive.required_permission = PERM_OPERATIONS_CONSOLIDATION_RECEIVE


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_consolidation_leg_waybill(request, reliefpkg_id: int, leg_id: int):
    try:
        return Response(
            operations_service.get_consolidation_leg_waybill(
                reliefpkg_id,
                leg_id,
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_consolidation_leg_waybill.required_permission = PERM_OPERATIONS_WAYBILL_VIEW


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_partial_release_request(request, reliefpkg_id: int):
    try:
        idempotency_key = _required_idempotency_key(request)
        actor_id = _actor_id(request)
        tenant_context = _tenant_context(request)
        cached_response = _cached_idempotent_response(
            endpoint="partial_release_request",
            resource_id=reliefpkg_id,
            actor_id=actor_id,
            tenant_context=tenant_context,
            idempotency_key=idempotency_key,
        )
        if cached_response is not None:
            return cached_response
        rate_limited = _rate_limit_response(
            request,
            scope="partial_release_request",
            limit=_WORKFLOW_LIMIT_PER_MINUTE,
        )
        if rate_limited is not None:
            return rate_limited
        return Response(
            operations_service.request_partial_release(
                reliefpkg_id,
                payload=_payload_object(request.data),
                actor_id=actor_id,
                actor_roles=_roles(request),
                tenant_context=tenant_context,
                idempotency_key=idempotency_key,
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_partial_release_request.required_permission = PERM_OPERATIONS_PARTIAL_RELEASE_REQUEST


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_partial_release_approve(request, reliefpkg_id: int):
    try:
        idempotency_key = _required_idempotency_key(request)
        actor_id = _actor_id(request)
        tenant_context = _tenant_context(request)
        cached_response = _cached_idempotent_response(
            endpoint="partial_release_approve",
            resource_id=reliefpkg_id,
            actor_id=actor_id,
            tenant_context=tenant_context,
            idempotency_key=idempotency_key,
        )
        if cached_response is not None:
            return cached_response
        rate_limited = _rate_limit_response(
            request,
            scope="partial_release_approve",
            limit=_WORKFLOW_LIMIT_PER_MINUTE,
        )
        if rate_limited is not None:
            return rate_limited
        return Response(
            operations_service.approve_partial_release(
                reliefpkg_id,
                payload=_payload_object(request.data),
                actor_id=actor_id,
                actor_roles=_roles(request),
                tenant_context=tenant_context,
                idempotency_key=idempotency_key,
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_partial_release_approve.required_permission = PERM_OPERATIONS_PARTIAL_RELEASE_APPROVE


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_pickup_release(request, reliefpkg_id: int):
    try:
        idempotency_key = _required_idempotency_key(request)
        actor_id = _actor_id(request)
        tenant_context = _tenant_context(request)
        cached_response = _cached_idempotent_response(
            endpoint="pickup_release",
            resource_id=reliefpkg_id,
            actor_id=actor_id,
            tenant_context=tenant_context,
            idempotency_key=idempotency_key,
        )
        if cached_response is not None:
            return cached_response
        rate_limited = _rate_limit_response(
            request,
            scope="pickup_release",
            limit=_WORKFLOW_LIMIT_PER_MINUTE,
        )
        if rate_limited is not None:
            return rate_limited
        return Response(
            operations_service.pickup_release(
                reliefpkg_id,
                payload=_payload_object(request.data),
                actor_id=actor_id,
                actor_roles=_roles(request),
                tenant_context=tenant_context,
                idempotency_key=idempotency_key,
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_pickup_release.required_permission = PERM_OPERATIONS_PICKUP_RELEASE


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_package_cancel(request, reliefpkg_id: int):
    try:
        idempotency_key = _required_idempotency_key(request)
        actor_id = _actor_id(request)
        tenant_context = _tenant_context(request)
        cached_response = _cached_idempotent_response(
            endpoint="package_cancel",
            resource_id=reliefpkg_id,
            actor_id=actor_id,
            tenant_context=tenant_context,
            idempotency_key=idempotency_key,
        )
        if cached_response is not None:
            return cached_response
        rate_limited = _rate_limit_response(
            request,
            scope="package_cancel",
            limit=_WORKFLOW_LIMIT_PER_MINUTE,
        )
        if rate_limited is not None:
            return rate_limited
        return Response(
            operations_service.cancel_package(
                reliefpkg_id,
                payload=_payload_object(request.data),
                actor_id=actor_id,
                actor_roles=_roles(request),
                tenant_context=tenant_context,
                idempotency_key=idempotency_key,
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_package_cancel.required_permission = PERM_OPERATIONS_PACKAGE_ALLOCATE


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_package_abandon_draft(request, reliefpkg_id: int):
    """Non-terminal abandon: release stock + locks, revert to DRAFT.

    Distinct from ``operations_package_cancel`` which moves the package to the
    terminal CANCELLED status. Abandon releases the fulfillment so another
    officer can pick up the parent relief request (which stays in
    APPROVED_FOR_FULFILLMENT).
    """
    try:
        idempotency_key = _required_idempotency_key(request)
        actor_id = _actor_id(request)
        tenant_context = _tenant_context(request)
        cached_response = _cached_idempotent_response(
            endpoint="package_abandon_draft",
            resource_id=reliefpkg_id,
            actor_id=actor_id,
            tenant_context=tenant_context,
            idempotency_key=idempotency_key,
        )
        if cached_response is not None:
            return cached_response
        rate_limited = _rate_limit_response(
            request,
            scope="package_abandon_draft",
            limit=_WORKFLOW_LIMIT_PER_MINUTE,
        )
        if rate_limited is not None:
            return rate_limited
        return Response(
            operations_service.abandon_package_draft(
                reliefpkg_id,
                payload=_payload_object(request.data),
                actor_id=actor_id,
                actor_roles=_roles(request),
                tenant_context=tenant_context,
                idempotency_key=idempotency_key,
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_package_abandon_draft.required_permission = PERM_OPERATIONS_PACKAGE_ALLOCATE


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_dispatch_queue(request):
    try:
        return Response(
            operations_service.list_dispatch_queue(
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_dispatch_queue.required_permission = [PERM_OPERATIONS_DISPATCH_PREPARE, PERM_OPERATIONS_DISPATCH_EXECUTE]


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_dispatch_detail(request, reliefpkg_id: int):
    try:
        return Response(
            operations_service.get_dispatch_package(
                reliefpkg_id,
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_dispatch_detail.required_permission = [PERM_OPERATIONS_DISPATCH_PREPARE, PERM_OPERATIONS_DISPATCH_EXECUTE]


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_dispatch_handoff(request, reliefpkg_id: int):
    try:
        idempotency_key = _required_idempotency_key(request)
        actor_id = _actor_id(request)
        tenant_context = _tenant_context(request)
        cached_response = _cached_idempotent_response(
            endpoint="dispatch_handoff",
            resource_id=reliefpkg_id,
            actor_id=actor_id,
            tenant_context=tenant_context,
            idempotency_key=idempotency_key,
        )
        if cached_response is not None:
            return cached_response
        rate_limited = _rate_limit_response(
            request,
            scope="dispatch_handoff",
            limit=_HIGH_RISK_LIMIT_PER_MINUTE,
        )
        if rate_limited is not None:
            return rate_limited
        return Response(
            operations_service.submit_dispatch(
                reliefpkg_id,
                payload=_payload_object(request.data),
                actor_id=actor_id,
                actor_roles=_roles(request),
                tenant_context=tenant_context,
                idempotency_key=idempotency_key,
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_dispatch_handoff.required_permission = [PERM_OPERATIONS_DISPATCH_PREPARE, PERM_OPERATIONS_DISPATCH_EXECUTE]


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_dispatch_waybill(request, reliefpkg_id: int):
    try:
        return Response(
            operations_service.get_waybill(
                reliefpkg_id,
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_dispatch_waybill.required_permission = PERM_OPERATIONS_WAYBILL_VIEW


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_receipt_confirm(request, reliefpkg_id: int):
    try:
        idempotency_key = _required_idempotency_key(request)
        actor_id = _actor_id(request)
        tenant_context = _tenant_context(request)
        cached_response = _cached_idempotent_response(
            endpoint="receipt_confirm",
            resource_id=reliefpkg_id,
            actor_id=actor_id,
            tenant_context=tenant_context,
            idempotency_key=idempotency_key,
        )
        if cached_response is not None:
            return cached_response
        rate_limited = _rate_limit_response(
            request,
            scope="receipt_confirm",
            limit=_HIGH_RISK_LIMIT_PER_MINUTE,
        )
        if rate_limited is not None:
            return rate_limited
        return Response(
            operations_service.confirm_receipt(
                reliefpkg_id,
                payload=_payload_object(request.data),
                actor_id=actor_id,
                actor_roles=_roles(request),
                tenant_context=tenant_context,
                idempotency_key=idempotency_key,
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_receipt_confirm.required_permission = PERM_OPERATIONS_RECEIPT_CONFIRM


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_tasks(request):
    try:
        return Response(
            operations_service.list_tasks(
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_tasks.required_permission = [PERM_OPERATIONS_QUEUE_VIEW, PERM_OPERATIONS_NOTIFICATION_RECEIVE]
