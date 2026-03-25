from __future__ import annotations

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from api.authentication import LegacyCompatAuthentication
from api.rbac import (
    PERM_NEEDS_LIST_APPROVE,
    PERM_NEEDS_LIST_EXECUTE,
    PERM_NEEDS_LIST_SUBMIT,
    resolve_roles_and_permissions,
)
from operations.permissions import OperationsPermission
from operations import services as operations_service
from operations.services import OperationValidationError
from replenishment.services.allocation_dispatch import (
    DispatchError,
    OptimisticLockError,
    OverrideApprovalError,
)


def _actor_id(request) -> str:
    return str(getattr(request.user, "user_id", None) or getattr(request.user, "username", None) or "system")


def _service_error_response(exc: Exception) -> Response:
    if isinstance(exc, OperationValidationError):
        return Response({"errors": exc.errors}, status=400)
    if isinstance(exc, OverrideApprovalError):
        return Response({"errors": {"override": exc.message}}, status=400)
    if isinstance(exc, OptimisticLockError):
        return Response({"errors": {"version": exc.message}}, status=409)
    if isinstance(exc, DispatchError):
        return Response({"errors": {"dispatch": exc.message}}, status=409)
    raise exc


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
                )
            )
        return Response(
            operations_service.create_request(
                payload=request.data or {},
                actor_id=_actor_id(request),
            ),
            status=201,
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_requests.required_permission = {
    "GET": [PERM_NEEDS_LIST_SUBMIT, PERM_NEEDS_LIST_APPROVE, PERM_NEEDS_LIST_EXECUTE],
    "POST": [PERM_NEEDS_LIST_SUBMIT, PERM_NEEDS_LIST_EXECUTE],
}


@api_view(["GET", "PATCH"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_request_detail(request, reliefrqst_id: int):
    try:
        if request.method == "GET":
            return Response(operations_service.get_request(reliefrqst_id, actor_id=_actor_id(request)))
        return Response(
            operations_service.update_request(
                reliefrqst_id,
                payload=request.data or {},
                actor_id=_actor_id(request),
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_request_detail.required_permission = {
    "GET": [PERM_NEEDS_LIST_SUBMIT, PERM_NEEDS_LIST_APPROVE, PERM_NEEDS_LIST_EXECUTE],
    "PATCH": [PERM_NEEDS_LIST_SUBMIT, PERM_NEEDS_LIST_EXECUTE],
}


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_request_submit(request, reliefrqst_id: int):
    try:
        return Response(operations_service.submit_request(reliefrqst_id, actor_id=_actor_id(request)))
    except Exception as exc:
        return _service_error_response(exc)


operations_request_submit.required_permission = [PERM_NEEDS_LIST_SUBMIT, PERM_NEEDS_LIST_EXECUTE]


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_eligibility_queue(request):
    try:
        return Response(operations_service.list_eligibility_queue(actor_id=_actor_id(request)))
    except Exception as exc:
        return _service_error_response(exc)


operations_eligibility_queue.required_permission = PERM_NEEDS_LIST_APPROVE


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_eligibility_detail(request, reliefrqst_id: int):
    try:
        return Response(operations_service.get_eligibility_request(reliefrqst_id, actor_id=_actor_id(request)))
    except Exception as exc:
        return _service_error_response(exc)


operations_eligibility_detail.required_permission = PERM_NEEDS_LIST_APPROVE


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
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_eligibility_decision.required_permission = PERM_NEEDS_LIST_APPROVE


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_packages_queue(request):
    try:
        return Response(operations_service.list_packages(actor_id=_actor_id(request)))
    except Exception as exc:
        return _service_error_response(exc)


operations_packages_queue.required_permission = [PERM_NEEDS_LIST_EXECUTE, PERM_NEEDS_LIST_APPROVE]


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_package_current(request, reliefrqst_id: int):
    try:
        return Response(operations_service.get_package(reliefrqst_id, actor_id=_actor_id(request)))
    except Exception as exc:
        return _service_error_response(exc)


operations_package_current.required_permission = [PERM_NEEDS_LIST_EXECUTE, PERM_NEEDS_LIST_APPROVE]


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_package_draft(request, reliefrqst_id: int):
    try:
        return Response(
            operations_service.save_package(
                reliefrqst_id,
                payload=request.data or {},
                actor_id=_actor_id(request),
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_package_draft.required_permission = [PERM_NEEDS_LIST_EXECUTE, PERM_NEEDS_LIST_APPROVE]


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_package_allocation_options(request, reliefrqst_id: int):
    try:
        source_warehouse_id = request.query_params.get("source_warehouse_id")
        return Response(
            operations_service.get_package_allocation_options(
                reliefrqst_id,
                source_warehouse_id=int(source_warehouse_id) if source_warehouse_id not in (None, "") else None,
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_package_allocation_options.required_permission = [PERM_NEEDS_LIST_EXECUTE, PERM_NEEDS_LIST_APPROVE]


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
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_package_commit_allocation.required_permission = [PERM_NEEDS_LIST_EXECUTE, PERM_NEEDS_LIST_APPROVE]


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_package_override_approve(request, reliefrqst_id: int):
    try:
        roles, _ = resolve_roles_and_permissions(request, request.user)
        return Response(
            operations_service.approve_override(
                reliefrqst_id,
                payload=request.data or {},
                actor_id=_actor_id(request),
                actor_roles=roles,
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_package_override_approve.required_permission = [PERM_NEEDS_LIST_APPROVE, PERM_NEEDS_LIST_EXECUTE]


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_dispatch_queue(request):
    try:
        return Response(operations_service.list_dispatch_queue(actor_id=_actor_id(request)))
    except Exception as exc:
        return _service_error_response(exc)


operations_dispatch_queue.required_permission = [PERM_NEEDS_LIST_EXECUTE, PERM_NEEDS_LIST_APPROVE]


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_dispatch_detail(request, reliefpkg_id: int):
    try:
        return Response(operations_service.get_dispatch_package(reliefpkg_id, actor_id=_actor_id(request)))
    except Exception as exc:
        return _service_error_response(exc)


operations_dispatch_detail.required_permission = [PERM_NEEDS_LIST_EXECUTE, PERM_NEEDS_LIST_APPROVE]


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
            )
        )
    except Exception as exc:
        return _service_error_response(exc)


operations_dispatch_handoff.required_permission = [PERM_NEEDS_LIST_EXECUTE, PERM_NEEDS_LIST_APPROVE]


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([IsAuthenticated, OperationsPermission])
def operations_dispatch_waybill(request, reliefpkg_id: int):
    try:
        return Response(operations_service.get_waybill(reliefpkg_id))
    except Exception as exc:
        return _service_error_response(exc)


operations_dispatch_waybill.required_permission = [PERM_NEEDS_LIST_EXECUTE, PERM_NEEDS_LIST_APPROVE]
