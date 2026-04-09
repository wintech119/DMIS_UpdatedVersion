from __future__ import annotations

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response

from api.authentication import LegacyCompatAuthentication
from api.rbac import (
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
from operations.exceptions import OperationValidationError
from operations.permissions import OperationsPermission
from replenishment.services.allocation_dispatch import (
    DispatchError,
    OptimisticLockError,
    OverrideApprovalError,
    ReservationError,
)


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


def _boolean_payload_flag(payload: dict[str, object], field_name: str, *, default: bool = False) -> bool:
    raw_value = payload.get(field_name, default)
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
        return Response(
            operations_service.create_request(
                payload=request.data or {},
                actor_id=_actor_id(request),
                tenant_context=_tenant_context(request),
                permissions=_permissions(request),
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
        return Response(
            operations_service.update_request(
                reliefrqst_id,
                payload=request.data or {},
                actor_id=_actor_id(request),
                tenant_context=_tenant_context(request),
                permissions=_permissions(request),
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
        return Response(
            operations_service.submit_request(
                reliefrqst_id,
                actor_id=_actor_id(request),
                tenant_context=_tenant_context(request),
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
        return Response(
            operations_service.submit_eligibility_decision(
                reliefrqst_id,
                payload=request.data or {},
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
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
        payload = dict(request.data or {})
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
        payload = request.data or {}
        return Response(
            operations_service.release_package_lock(
                reliefrqst_id,
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
                force=_boolean_payload_flag(payload, "force", default=False),
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
        if source_warehouse_id in (None, ""):
            raise OperationValidationError({"source_warehouse_id": "source_warehouse_id is required."})
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
        return Response(
            operations_service.get_item_allocation_preview(
                reliefrqst_id,
                item_id,
                payload=request.data or {},
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
        return Response(
            operations_service.save_package(
                reliefrqst_id,
                payload=request.data or {},
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
                permissions=_permissions(request),
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
        return Response(
            operations_service.approve_override(
                reliefrqst_id,
                payload=request.data or {},
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_package_override_approve.required_permission = PERM_OPERATIONS_PACKAGE_OVERRIDE_APPROVE


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
        return Response(
            operations_service.dispatch_consolidation_leg(
                reliefpkg_id,
                leg_id,
                payload=request.data or {},
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
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
        return Response(
            operations_service.receive_consolidation_leg(
                reliefpkg_id,
                leg_id,
                payload=request.data or {},
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
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
        return Response(
            operations_service.request_partial_release(
                reliefpkg_id,
                payload=request.data or {},
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
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
        return Response(
            operations_service.approve_partial_release(
                reliefpkg_id,
                payload=request.data or {},
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
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
        return Response(
            operations_service.pickup_release(
                reliefpkg_id,
                payload=request.data or {},
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
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
        return Response(
            operations_service.cancel_package(
                reliefpkg_id,
                payload=request.data or {},
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
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
        return Response(
            operations_service.abandon_package_draft(
                reliefpkg_id,
                payload=request.data or {},
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
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
        return Response(
            operations_service.submit_dispatch(
                reliefpkg_id,
                payload=request.data or {},
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
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
        return Response(
            operations_service.confirm_receipt(
                reliefpkg_id,
                payload=request.data or {},
                actor_id=_actor_id(request),
                actor_roles=_roles(request),
                tenant_context=_tenant_context(request),
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
