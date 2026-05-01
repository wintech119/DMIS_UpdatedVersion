"""
Domain-specific exceptions for the inventory module.

Each exception carries a machine-readable `code`, a human-readable `detail`,
and an HTTP status code so DRF views can translate them directly into
structured error responses.
"""

from __future__ import annotations

from typing import Any


class InventoryError(Exception):
    code: str = "inventory_error"
    status_code: int = 400

    def __init__(self, detail: str = "", *, payload: dict[str, Any] | None = None) -> None:
        super().__init__(detail or self.code)
        self.detail = detail or self.code
        self.payload = payload or {}


class NegativeBalanceError(InventoryError):
    code = "negative_balance_attempt"
    status_code = 409


class StatusTransitionError(InventoryError):
    code = "invalid_status_transition"
    status_code = 409


class SourceTypeError(InventoryError):
    code = "invalid_source_type"
    status_code = 400


class SegregationOfDutyError(InventoryError):
    code = "segregation_of_duty"
    status_code = 403


class WarehouseNotOnboardedError(InventoryError):
    code = "warehouse_not_onboarded"
    status_code = 403


class InsufficientAvailabilityError(InventoryError):
    code = "insufficient_availability"
    status_code = 409


class IdempotencyConflictError(InventoryError):
    code = "idempotency_conflict"
    status_code = 409


class ImmutableLedgerError(InventoryError):
    code = "ledger_is_append_only"
    status_code = 409


class EvidenceRequiredError(InventoryError):
    code = "evidence_required"
    status_code = 400
