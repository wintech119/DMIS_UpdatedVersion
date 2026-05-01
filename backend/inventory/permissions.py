"""
DRF permission classes for the inventory module.

Mirrors the pattern in `backend/api/permissions.py` (`NeedsListPermission`).
Each permission class declares a `required_permission` string that is checked
against the resolved Principal's permission set. When `required_permission` is
None or empty, the class only requires authentication.

Backend authorization is authoritative — frontend route guards are UX only.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from api.rbac import resolve_roles_and_permissions


class _InventoryPermissionBase(BasePermission):
    required_permission: str | None = None

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        if not self.required_permission:
            return True
        principal = getattr(request, "principal", None)
        if principal is None:
            return False
        try:
            _, perms = resolve_roles_and_permissions(principal)
        except Exception:
            return False
        return self.required_permission in perms


def _make_perm(name: str, perm_code: str) -> type[_InventoryPermissionBase]:
    return type(name, (_InventoryPermissionBase,), {"required_permission": perm_code})


# Read tier
InventoryViewPermission = _make_perm("InventoryViewPermission", "inventory.view")
InventoryLedgerViewPermission = _make_perm(
    "InventoryLedgerViewPermission", "inventory.ledger.view"
)
InventoryProvenanceViewPermission = _make_perm(
    "InventoryProvenanceViewPermission", "inventory.provenance.view"
)
InventoryExceptionViewPermission = _make_perm(
    "InventoryExceptionViewPermission", "inventory.exception.view"
)
InventoryExceptionResolvePermission = _make_perm(
    "InventoryExceptionResolvePermission", "inventory.exception.resolve"
)
InventoryReservationViewPermission = _make_perm(
    "InventoryReservationViewPermission", "inventory.reservation.view"
)
InventoryEvidenceViewPermission = _make_perm(
    "InventoryEvidenceViewPermission", "inventory.evidence.view"
)

# Opening Balance workflow
InventoryOBCreatePermission = _make_perm(
    "InventoryOBCreatePermission", "inventory.opening_balance.create"
)
InventoryOBEditPermission = _make_perm(
    "InventoryOBEditPermission", "inventory.opening_balance.edit"
)
InventoryOBSubmitPermission = _make_perm(
    "InventoryOBSubmitPermission", "inventory.opening_balance.submit"
)
InventoryOBApprovePermission = _make_perm(
    "InventoryOBApprovePermission", "inventory.opening_balance.approve"
)
InventoryOBPostPermission = _make_perm(
    "InventoryOBPostPermission", "inventory.opening_balance.post"
)
InventoryOBRejectPermission = _make_perm(
    "InventoryOBRejectPermission", "inventory.opening_balance.reject"
)
InventoryOBCancelPermission = _make_perm(
    "InventoryOBCancelPermission", "inventory.opening_balance.cancel"
)

# Reservations / picking / evidence
InventoryReservationCreatePermission = _make_perm(
    "InventoryReservationCreatePermission", "inventory.reservation.create"
)
InventoryPickRecommendPermission = _make_perm(
    "InventoryPickRecommendPermission", "inventory.pick.recommend"
)
InventoryPickConfirmPermission = _make_perm(
    "InventoryPickConfirmPermission", "inventory.pick.confirm"
)
InventoryEvidenceUploadPermission = _make_perm(
    "InventoryEvidenceUploadPermission", "inventory.evidence.upload"
)
InventoryEvidenceDeletePermission = _make_perm(
    "InventoryEvidenceDeletePermission", "inventory.evidence.delete"
)
