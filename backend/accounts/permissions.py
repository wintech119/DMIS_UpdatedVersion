from __future__ import annotations


def bridge_codename(resource: str, action: str) -> str:
    """Translate a DMIS permission row into the Django codename used by the bridge."""
    return f"{resource}__{action}"
