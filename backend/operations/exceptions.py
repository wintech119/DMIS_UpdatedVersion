from __future__ import annotations

from typing import Any


class OperationValidationError(ValueError):
    def __init__(self, errors: dict[str, Any]):
        super().__init__("Validation error")
        self.errors = errors
