from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from django.db import DatabaseError, connection, transaction
from django.db.models import Q
from django.utils import timezone

from api.tenancy import (
    is_phase_window_authority_tenant_code,
    phase_window_authority_tenant_codes,
)
from replenishment import rules
from replenishment.models import LeadTimeConfig

_PHASE_WINDOW_CONFIG_KEY_PREFIX = "replenishment.phase_window."
_PHASE_WINDOW_DESCRIPTION = "Global replenishment phase window"
_JUSTIFICATION_MAX_LENGTH = 500


class PhaseWindowPolicyError(ValueError):
    """Raised when phase-window payloads are invalid."""


@dataclass(frozen=True)
class GlobalPhaseWindowConfigRecord:
    config_id: int
    tenant_id: int
    tenant_code: str
    tenant_name: str
    effective_date: Any
    update_dtime: Any
    value: dict[str, Any]


def _normalize_phase(value: object) -> str:
    phase = str(value or "").strip().upper()
    if phase not in rules.PHASES:
        raise PhaseWindowPolicyError("phase must be one of: SURGE, STABILIZED, BASELINE.")
    return phase


def _config_key(phase: str) -> str:
    return f"{_PHASE_WINDOW_CONFIG_KEY_PREFIX}{phase.lower()}"


def _normalize_tenant_code(value: object) -> str:
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text


def _configured_admin_codes() -> list[str]:
    return sorted(phase_window_authority_tenant_codes())


def _coerce_positive_hours(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise PhaseWindowPolicyError(f"{field_name} must be a positive integer.")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        stripped = value.strip()
        if not re.fullmatch(r"\d+", stripped):
            raise PhaseWindowPolicyError(f"{field_name} must be a positive integer.")
        parsed = int(stripped)
    else:
        raise PhaseWindowPolicyError(f"{field_name} must be a positive integer.")
    if parsed <= 0:
        raise PhaseWindowPolicyError(f"{field_name} must be a positive integer.")
    return parsed


def _coerce_existing_or_default_hours(
    existing: GlobalPhaseWindowConfigRecord | None,
    field_name: str,
    default_value: int,
) -> int:
    if existing is None:
        return int(default_value)
    try:
        return _coerce_positive_hours(existing.value.get(field_name), field_name)
    except PhaseWindowPolicyError:
        return int(default_value)


def _is_authoritative_phase_window_tenant(tenant: dict[str, Any]) -> bool:
    tenant_type = _normalize_tenant_code(tenant.get("tenant_type"))
    return (
        tenant_type in {"NATIONAL", "NATIONAL_LEVEL"}
        and is_phase_window_authority_tenant_code(tenant.get("tenant_code"))
    )


def _lock_global_phase_window_config_scope(
    cursor,
    *,
    tenant_id: int,
    config_key: str,
) -> None:
    if getattr(connection, "vendor", "") != "postgresql":
        return
    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s))",
        [f"replenishment.phase_window:{int(tenant_id)}:{config_key}"],
    )


def _expire_active_global_phase_window_configs(
    cursor,
    *,
    tenant_id: int,
    config_key: str,
    actor_ref: str,
    now,
    today,
) -> None:
    cursor.execute(
        """
        UPDATE tenant_config
        SET
            expiry_date = %s,
            update_by_id = %s,
            update_dtime = %s,
            version_nbr = COALESCE(version_nbr, 1) + 1
        WHERE
            tenant_id = %s
            AND config_key = %s
            AND effective_date <= %s
            AND (expiry_date IS NULL OR expiry_date >= %s)
        """,
        [
            today,
            actor_ref,
            now,
            int(tenant_id),
            config_key,
            today,
            today,
        ],
    )


def _coerce_justification(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise PhaseWindowPolicyError("justification is required.")
    if len(text) > _JUSTIFICATION_MAX_LENGTH:
        raise PhaseWindowPolicyError(
            f"justification must be {_JUSTIFICATION_MAX_LENGTH} characters or fewer."
        )
    return text


def _actor_ref(actor: object) -> str:
    text = str(actor or "SYSTEM").strip() or "SYSTEM"
    return text[:20]


def _parse_json_object(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _json_text(value: dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _tenant_row_by_id(tenant_id: int) -> dict[str, Any] | None:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT tenant_id, tenant_code, tenant_name, tenant_type
                FROM tenant
                WHERE tenant_id = %s AND COALESCE(status_code, 'A') = 'A'
                LIMIT 1
                """,
                [int(tenant_id)],
            )
            row = cursor.fetchone()
    except DatabaseError:
        return None
    if not row:
        return None
    return {
        "tenant_id": int(row[0]),
        "tenant_code": str(row[1] or ""),
        "tenant_name": str(row[2] or ""),
        "tenant_type": str(row[3] or ""),
    }


def _resolve_authoritative_phase_window_tenant() -> dict[str, Any] | None:
    try:
        with connection.cursor() as cursor:
            for tenant_code in _configured_admin_codes():
                cursor.execute(
                    """
                    SELECT tenant_id, tenant_code, tenant_name, tenant_type
                    FROM tenant
                    WHERE
                        COALESCE(status_code, 'A') = 'A'
                        AND UPPER(REPLACE(REPLACE(COALESCE(tenant_code, ''), '-', '_'), ' ', '_')) = %s
                    ORDER BY tenant_id ASC
                    LIMIT 1
                    """,
                    [tenant_code],
                )
                row = cursor.fetchone()
                if row:
                    tenant = {
                        "tenant_id": int(row[0]),
                        "tenant_code": str(row[1] or ""),
                        "tenant_name": str(row[2] or ""),
                        "tenant_type": str(row[3] or ""),
                    }
                    if _is_authoritative_phase_window_tenant(tenant):
                        return tenant
    except DatabaseError:
        return None
    return None


def _fetch_effective_global_phase_window_config(
    phase: str,
    *,
    tenant_id: int | None = None,
) -> GlobalPhaseWindowConfigRecord | None:
    normalized_phase = _normalize_phase(phase)
    authoritative_tenant = (
        _tenant_row_by_id(int(tenant_id))
        if tenant_id is not None
        else _resolve_authoritative_phase_window_tenant()
    )
    if authoritative_tenant is None:
        return None
    if not _is_authoritative_phase_window_tenant(authoritative_tenant):
        return None

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    tc.config_id,
                    tc.tenant_id,
                    t.tenant_code,
                    t.tenant_name,
                    tc.effective_date,
                    tc.update_dtime,
                    tc.config_value
                FROM tenant_config tc
                JOIN tenant t ON t.tenant_id = tc.tenant_id
                WHERE
                    tc.tenant_id = %s
                    AND tc.config_key = %s
                    AND tc.effective_date <= CURRENT_DATE
                    AND (tc.expiry_date IS NULL OR tc.expiry_date > CURRENT_DATE)
                ORDER BY tc.effective_date DESC, tc.update_dtime DESC, tc.config_id DESC
                LIMIT 1
                """,
                [int(authoritative_tenant["tenant_id"]), _config_key(normalized_phase)],
            )
            row = cursor.fetchone()
    except DatabaseError:
        return None

    if not row:
        return None

    payload = _parse_json_object(row[6])
    if payload is None:
        return None

    return GlobalPhaseWindowConfigRecord(
        config_id=int(row[0]),
        tenant_id=int(row[1]),
        tenant_code=str(row[2] or ""),
        tenant_name=str(row[3] or ""),
        effective_date=row[4],
        update_dtime=row[5],
        value=payload,
    )


def _serialize_window_response(
    *,
    event_id: int | None,
    phase: str,
    demand_hours: int,
    planning_hours: int,
    source: str,
    config_id: int | None,
    tenant: dict[str, Any] | None,
    justification: str | None = None,
    audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event_id": None if event_id is None else int(event_id),
        "phase": phase,
        "scope": "global",
        "applies_globally": True,
        "demand_hours": int(demand_hours),
        "planning_hours": int(planning_hours),
        "source": source,
        "config_id": config_id,
        "authoritative_tenant": tenant,
        "justification": justification,
        "audit": audit or {},
    }


def get_effective_phase_windows(event_id: int | None, phase: str) -> dict[str, Any]:
    normalized_phase = _normalize_phase(phase)
    default_windows = rules.get_phase_windows(normalized_phase)
    authoritative_tenant = _resolve_authoritative_phase_window_tenant()
    config = _fetch_effective_global_phase_window_config(normalized_phase)

    if config is None:
        return _serialize_window_response(
            event_id=event_id,
            phase=normalized_phase,
            demand_hours=int(default_windows["demand_hours"]),
            planning_hours=int(default_windows["planning_hours"]),
            source="backlog_default",
            config_id=None,
            tenant=authoritative_tenant,
        )

    try:
        demand_hours = _coerce_positive_hours(config.value.get("demand_hours"), "demand_hours")
        planning_hours = _coerce_positive_hours(
            config.value.get("planning_hours"),
            "planning_hours",
        )
    except PhaseWindowPolicyError:
        return _serialize_window_response(
            event_id=event_id,
            phase=normalized_phase,
            demand_hours=int(default_windows["demand_hours"]),
            planning_hours=int(default_windows["planning_hours"]),
            source="backlog_default",
            config_id=None,
            tenant=authoritative_tenant,
        )

    return _serialize_window_response(
        event_id=event_id,
        phase=normalized_phase,
        demand_hours=demand_hours,
        planning_hours=planning_hours,
        source="tenant_config_global",
        config_id=int(config.config_id),
        tenant={
            "tenant_id": int(config.tenant_id),
            "tenant_code": config.tenant_code,
            "tenant_name": config.tenant_name,
        },
        justification=str(config.value.get("justification") or "").strip() or None,
        audit=config.value.get("audit") if isinstance(config.value.get("audit"), dict) else None,
    )


def list_effective_phase_windows(event_id: int | None = None) -> list[dict[str, Any]]:
    return [get_effective_phase_windows(event_id, phase) for phase in rules.PHASES]


@transaction.atomic
def set_global_phase_windows(
    *,
    phase: str,
    demand_hours: object,
    planning_hours: object,
    justification: object,
    actor: object,
    tenant_id: int,
) -> dict[str, Any]:
    normalized_phase = _normalize_phase(phase)
    demand = _coerce_positive_hours(demand_hours, "demand_hours")
    planning = _coerce_positive_hours(planning_hours, "planning_hours")
    justification_text = _coerce_justification(justification)
    actor_ref = _actor_ref(actor)

    tenant = _tenant_row_by_id(int(tenant_id))
    if tenant is None:
        raise PhaseWindowPolicyError("Authoritative ODPEM national tenant was not found.")
    if not _is_authoritative_phase_window_tenant(tenant):
        raise PhaseWindowPolicyError(
            "Phase-window configuration must be stored under the authoritative ODPEM national tenant."
        )

    config_key = _config_key(normalized_phase)
    try:
        with connection.cursor() as cursor:
            _lock_global_phase_window_config_scope(
                cursor,
                tenant_id=int(tenant["tenant_id"]),
                config_key=config_key,
            )
    except DatabaseError as exc:
        raise PhaseWindowPolicyError(
            f"Unable to lock global phase window configuration: {exc}"
        ) from exc

    existing = _fetch_effective_global_phase_window_config(
        normalized_phase,
        tenant_id=int(tenant["tenant_id"]),
    )
    default_windows = rules.get_phase_windows(normalized_phase)
    prior_values = {
        "demand_hours": _coerce_existing_or_default_hours(
            existing,
            "demand_hours",
            int(default_windows["demand_hours"]),
        ),
        "planning_hours": _coerce_existing_or_default_hours(
            existing,
            "planning_hours",
            int(default_windows["planning_hours"]),
        ),
    }
    new_values = {
        "demand_hours": int(demand),
        "planning_hours": int(planning),
    }
    if existing is not None and prior_values == new_values:
        raise PhaseWindowPolicyError("No phase-window change detected.")

    payload = {
        "phase": normalized_phase,
        "scope": "global",
        "applies_globally": True,
        "demand_hours": int(demand),
        "planning_hours": int(planning),
        "freshness_thresholds": dict(rules.FRESHNESS_THRESHOLDS.get(normalized_phase, {})),
        "justification": justification_text,
        "audit": {
            "prior_values": prior_values,
            "new_values": new_values,
        },
    }
    serialized = _json_text(payload)
    now = timezone.now()
    today = timezone.localdate()

    try:
        with connection.cursor() as cursor:
            _expire_active_global_phase_window_configs(
                cursor,
                tenant_id=int(tenant["tenant_id"]),
                config_key=config_key,
                actor_ref=actor_ref,
                now=now,
                today=today,
            )
            cursor.execute(
                """
                INSERT INTO tenant_config (
                    tenant_id,
                    config_key,
                    config_value,
                    config_type,
                    effective_date,
                    expiry_date,
                    description,
                    create_by_id,
                    create_dtime,
                    update_by_id,
                    update_dtime,
                    version_nbr
                )
                VALUES (%s, %s, %s, %s, %s, NULL, %s, %s, %s, %s, %s, 1)
                """,
                [
                    int(tenant["tenant_id"]),
                    config_key,
                    serialized,
                    "json",
                    today,
                    _PHASE_WINDOW_DESCRIPTION,
                    actor_ref,
                    now,
                    actor_ref,
                    now,
                ],
            )
    except DatabaseError as exc:
        raise PhaseWindowPolicyError(
            f"Unable to persist global phase window configuration: {exc}"
        ) from exc

    return get_effective_phase_windows(None, normalized_phase)


def get_default_horizon_lead_times() -> dict[str, dict[str, Any]]:
    defaults = rules.get_default_horizon_lead_times()
    today = timezone.localdate()
    resolved: dict[str, dict[str, Any]] = {}

    for horizon, fallback in defaults.items():
        try:
            config = (
                LeadTimeConfig.objects.filter(
                    horizon=horizon,
                    is_default=True,
                    effective_from__lte=today,
                )
                .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=today))
                .order_by("-effective_from", "-update_dtime", "-config_id")
                .first()
            )
        except DatabaseError:
            config = None

        if config is None:
            resolved[horizon] = {
                "horizon": horizon,
                "lead_time_hours": int(fallback),
                "source": "backlog_default",
                "config_id": None,
            }
            continue

        resolved[horizon] = {
            "horizon": horizon,
            "lead_time_hours": int(config.lead_time_hours),
            "source": "lead_time_config",
            "config_id": int(config.config_id),
        }

    return resolved
