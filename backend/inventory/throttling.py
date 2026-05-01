"""
DRF throttle scopes for the inventory module. Mirrors the pattern in
`backend/masterdata/throttling.py`.

Tiers (per CLAUDE.md and architecture review):
    inventory-read       120 req/min  GET dashboard, drilldown, lookups, ledger view
    inventory-write       40 req/min  POST/PATCH OB lines, edits, evidence upload
    inventory-workflow    15 req/min  submit, approve, reject, cancel, reservation, recount
    inventory-high-risk   10 req/min  post (creates ledger), pick.confirm, evidence delete
    inventory-bulk         5 req/min  bulk-import OB lines, CSV upload

Production: Redis-backed via Django cache framework. Local-only: LocMemCache (acceptable
for single-developer dev runs only — not for shared, staging, or production-like
environments).
"""

from __future__ import annotations

from rest_framework.throttling import UserRateThrottle


class _ScopedUserRateThrottle(UserRateThrottle):
    """Base class so subclasses can declare scope + rate cleanly."""

    write_methods = frozenset({"POST", "PATCH", "PUT", "DELETE"})

    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            ident = (
                getattr(user, "pk", None)
                or getattr(user, "user_id", None)
                or getattr(user, "id", None)
                or self.get_ident(request)
            )
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class InventoryReadThrottle(_ScopedUserRateThrottle):
    scope = "inventory-read"
    rate = "120/minute"


class InventoryWriteThrottle(_ScopedUserRateThrottle):
    scope = "inventory-write"
    rate = "40/minute"

    def allow_request(self, request, view):
        if request.method not in self.write_methods:
            return True
        return super().allow_request(request, view)


class InventoryWorkflowThrottle(_ScopedUserRateThrottle):
    scope = "inventory-workflow"
    rate = "15/minute"


class InventoryHighRiskThrottle(_ScopedUserRateThrottle):
    scope = "inventory-high-risk"
    rate = "10/minute"


class InventoryBulkThrottle(_ScopedUserRateThrottle):
    scope = "inventory-bulk"
    rate = "5/minute"
