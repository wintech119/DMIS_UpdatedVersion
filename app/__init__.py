"""Legacy Flask runtime metadata and retirement gate."""

from __future__ import annotations

import os
from typing import Final

__version__ = "0.2.3b1"

FLASK_RUNTIME_DISABLED: Final[str] = "disabled"
FLASK_RUNTIME_ROLLBACK_ONLY: Final[str] = "rollback-only"
_ALLOWED_FLASK_RUNTIME_MODES: Final[set[str]] = {
    FLASK_RUNTIME_DISABLED,
    FLASK_RUNTIME_ROLLBACK_ONLY,
}


class LegacyFlaskRuntimeDisabledError(RuntimeError):
    """Raised when the legacy Flask runtime is started outside rollback mode."""


def get_flask_runtime_mode() -> str:
    """Return the configured legacy Flask runtime mode."""
    raw_mode = os.environ.get("DMIS_FLASK_RUNTIME_MODE", FLASK_RUNTIME_DISABLED)
    mode = str(raw_mode or FLASK_RUNTIME_DISABLED).strip().lower()
    if mode not in _ALLOWED_FLASK_RUNTIME_MODES:
        allowed = ", ".join(sorted(_ALLOWED_FLASK_RUNTIME_MODES))
        raise LegacyFlaskRuntimeDisabledError(
            "DMIS_FLASK_RUNTIME_MODE must be one of "
            f"{allowed}. Received {raw_mode!r}."
        )
    return mode


def require_flask_runtime_rollback_only(entrypoint: str) -> str:
    """
    Fail closed unless the legacy runtime is explicitly enabled for rollback.
    """
    mode = get_flask_runtime_mode()
    if mode != FLASK_RUNTIME_ROLLBACK_ONLY:
        raise LegacyFlaskRuntimeDisabledError(
            f"{entrypoint} refused to start because the legacy Flask runtime is retired "
            "from the DMIS live path. Angular + Django is the production path of record. "
            "Set DMIS_FLASK_RUNTIME_MODE=rollback-only only for a temporary, "
            "operator-controlled rollback exception pending DMIS-10 full decommission."
        )
    return mode


def flask_runtime_warning(entrypoint: str) -> str:
    """Return the operator warning emitted when rollback mode is enabled."""
    return (
        f"{entrypoint} is running the legacy Flask runtime in rollback-only mode. "
        "This exception is temporary, must stay out of normal navigation and deployment, "
        "and is scheduled for removal in DMIS-10."
    )
