from __future__ import annotations

from typing import Any

from django.db import DatabaseError, connection, transaction

from replenishment import rules
from replenishment.models import EventPhaseConfig


class PhaseWindowPolicyError(ValueError):
    """Raised when event phase window payloads are invalid."""


def _normalize_phase(value: object) -> str:
    phase = str(value or "").strip().upper()
    if phase not in rules.PHASES:
        raise PhaseWindowPolicyError("phase must be one of: SURGE, STABILIZED, BASELINE.")
    return phase


def _coerce_positive_hours(value: object, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise PhaseWindowPolicyError(f"{field_name} must be a positive integer.") from None
    if parsed <= 0:
        raise PhaseWindowPolicyError(f"{field_name} must be a positive integer.")
    return parsed


def _actor_ref(actor: object) -> str:
    text = str(actor or "SYSTEM").strip() or "SYSTEM"
    return text[:20]


def _event_exists(event_id: int) -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM event WHERE event_id = %s LIMIT 1", [event_id])
            return cursor.fetchone() is not None
    except DatabaseError:
        # Do not hard-fail on metadata lookup problems; save path will still guard integrity.
        return True


def _fetch_active_event_phase_config(event_id: int, phase: str) -> EventPhaseConfig | None:
    try:
        return (
            EventPhaseConfig.objects
            .filter(event_id=int(event_id), phase=phase, is_active=True)
            .order_by("-update_dtime", "-config_id")
            .first()
        )
    except DatabaseError:
        return None


def get_effective_phase_windows(event_id: int, phase: str) -> dict[str, Any]:
    normalized_phase = _normalize_phase(phase)
    default_windows = rules.get_phase_windows(normalized_phase)
    config = _fetch_active_event_phase_config(int(event_id), normalized_phase)

    if config is None:
        return {
            "event_id": int(event_id),
            "phase": normalized_phase,
            "demand_hours": int(default_windows["demand_hours"]),
            "planning_hours": int(default_windows["planning_hours"]),
            "source": "rules_default",
            "config_id": None,
        }

    return {
        "event_id": int(event_id),
        "phase": normalized_phase,
        "demand_hours": int(config.demand_window_hours),
        "planning_hours": int(config.planning_window_hours),
        "source": "event_phase_config",
        "config_id": int(config.config_id),
    }


def list_effective_phase_windows(event_id: int) -> list[dict[str, Any]]:
    return [get_effective_phase_windows(int(event_id), phase) for phase in rules.PHASES]


@transaction.atomic
def set_event_phase_windows(
    *,
    event_id: int,
    phase: str,
    demand_hours: object,
    planning_hours: object,
    actor: object,
) -> dict[str, Any]:
    normalized_phase = _normalize_phase(phase)
    event = int(event_id)
    demand = _coerce_positive_hours(demand_hours, "demand_hours")
    planning = _coerce_positive_hours(planning_hours, "planning_hours")
    actor_ref = _actor_ref(actor)
    if not _event_exists(event):
        raise PhaseWindowPolicyError(f"event_id {event} does not exist.")

    stale_threshold = rules.FRESHNESS_THRESHOLDS.get(normalized_phase, {}).get("warn_max_hours", 6)
    fresh_threshold = rules.FRESHNESS_THRESHOLDS.get(normalized_phase, {}).get("fresh_max_hours", 2)

    try:
        existing = (
            EventPhaseConfig.objects
            .select_for_update()
            .filter(event_id=event, phase=normalized_phase)
            .order_by("-config_id")
            .first()
        )
    except DatabaseError as exc:
        raise PhaseWindowPolicyError(f"Unable to access event phase config store: {exc}") from exc

    if existing is None:
        try:
            EventPhaseConfig.objects.create(
                event_id=event,
                phase=normalized_phase,
                demand_window_hours=demand,
                planning_window_hours=planning,
                safety_buffer_pct="25.00",
                safety_factor="1.25",
                freshness_threshold_hours=int(fresh_threshold),
                stale_threshold_hours=int(stale_threshold),
                is_active=True,
                create_by_id=actor_ref,
                update_by_id=actor_ref,
                version_nbr=1,
            )
        except DatabaseError as exc:
            raise PhaseWindowPolicyError(f"Unable to create event phase config: {exc}") from exc
    else:
        existing.demand_window_hours = demand
        existing.planning_window_hours = planning
        existing.is_active = True
        existing.update_by_id = actor_ref
        existing.version_nbr = int(existing.version_nbr or 1) + 1
        try:
            existing.save(
                update_fields=[
                    "demand_window_hours",
                    "planning_window_hours",
                    "is_active",
                    "update_by_id",
                    "update_dtime",
                    "version_nbr",
                ]
            )
        except DatabaseError as exc:
            raise PhaseWindowPolicyError(f"Unable to update event phase config: {exc}") from exc

    return get_effective_phase_windows(event, normalized_phase)
