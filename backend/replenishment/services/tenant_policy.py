from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable, List

from django.db import DatabaseError, connection, transaction
from django.utils import timezone


WORKFLOW_TYPES = {"A", "B", "C"}
FEATURE_KEY_PREFIX = "feature."


class TenantPolicyError(ValueError):
    """Raised when tenant policy payloads are invalid."""


def _actor_ref(actor: object) -> str:
    text = str(actor or "SYSTEM").strip() or "SYSTEM"
    # Existing audit columns are VARCHAR(20).
    return text[:20]


def _approval_config_key(workflow_type: str) -> str:
    return f"approval.workflow.{workflow_type}"


def _approval_draft_config_key(workflow_type: str) -> str:
    return f"approval.workflow.{workflow_type}.draft"


def _feature_config_key(feature_key: str) -> str:
    normalized = str(feature_key or "").strip().lower().replace(" ", "_")
    if not normalized:
        raise TenantPolicyError("feature_key is required.")
    return f"{FEATURE_KEY_PREFIX}{normalized}"


def _ensure_workflow_type(workflow_type: object) -> str:
    normalized = str(workflow_type or "").strip().upper()
    if normalized not in WORKFLOW_TYPES:
        raise TenantPolicyError("workflow_type must be one of: A, B, C.")
    return normalized


def _parse_json_dict(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def _json_text(value: dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True)
class TenantConfigValue:
    config_id: int
    tenant_id: int
    config_key: str
    config_type: str | None
    effective_date: date
    expiry_date: date | None
    update_dtime: Any
    value: dict[str, Any]


def _fetch_latest_config(tenant_id: int, config_key: str) -> TenantConfigValue | None:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    config_id,
                    tenant_id,
                    config_key,
                    config_type,
                    effective_date,
                    expiry_date,
                    update_dtime,
                    config_value
                FROM tenant_config
                WHERE tenant_id = %s AND config_key = %s
                ORDER BY effective_date DESC, update_dtime DESC, config_id DESC
                LIMIT 1
                """,
                [tenant_id, config_key],
            )
            row = cursor.fetchone()
    except DatabaseError:
        return None
    if not row:
        return None
    payload = _parse_json_dict(row[7])
    if payload is None:
        return None
    return TenantConfigValue(
        config_id=int(row[0]),
        tenant_id=int(row[1]),
        config_key=str(row[2]),
        config_type=str(row[3] or "").strip() or None,
        effective_date=row[4],
        expiry_date=row[5],
        update_dtime=row[6],
        value=payload,
    )


def _fetch_effective_config(tenant_id: int, config_key: str) -> TenantConfigValue | None:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    config_id,
                    tenant_id,
                    config_key,
                    config_type,
                    effective_date,
                    expiry_date,
                    update_dtime,
                    config_value
                FROM tenant_config
                WHERE
                    tenant_id = %s
                    AND config_key = %s
                    AND effective_date <= CURRENT_DATE
                    AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
                ORDER BY effective_date DESC, update_dtime DESC, config_id DESC
                LIMIT 1
                """,
                [tenant_id, config_key],
            )
            row = cursor.fetchone()
    except DatabaseError:
        return None
    if not row:
        return None
    payload = _parse_json_dict(row[7])
    if payload is None:
        return None
    return TenantConfigValue(
        config_id=int(row[0]),
        tenant_id=int(row[1]),
        config_key=str(row[2]),
        config_type=str(row[3] or "").strip() or None,
        effective_date=row[4],
        expiry_date=row[5],
        update_dtime=row[6],
        value=payload,
    )


def _validate_role_codes(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    codes = []
    for value in values:
        normalized = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
        while "__" in normalized:
            normalized = normalized.replace("__", "_")
        if normalized:
            codes.append(normalized)
    return list(dict.fromkeys(codes))


def validate_approval_policy_payload(
    workflow_type: str,
    payload: object,
) -> tuple[dict[str, Any], list[str]]:
    workflow = _ensure_workflow_type(workflow_type)
    policy = _parse_json_dict(payload)
    if policy is None:
        return {}, ["policy must be a JSON object."]

    errors: list[str] = []
    fixed = policy.get("fixed_approval")
    thresholds = policy.get("thresholds")
    default_approval = policy.get("default_approval")

    if workflow in {"A", "B"}:
        block = fixed if isinstance(fixed, dict) else policy
        role_codes = _validate_role_codes(block.get("approver_role_codes"))
        if not role_codes:
            errors.append("fixed approval approver_role_codes is required for workflow A/B.")
        if not str(block.get("tier") or "").strip():
            errors.append("fixed approval tier is required for workflow A/B.")
    else:
        if not isinstance(thresholds, list) or not thresholds:
            errors.append("thresholds array is required for workflow C.")
        else:
            seen_open_ended = False
            for idx, threshold in enumerate(thresholds):
                if not isinstance(threshold, dict):
                    errors.append(f"thresholds[{idx}] must be an object.")
                    continue
                if not str(threshold.get("tier") or "").strip():
                    errors.append(f"thresholds[{idx}].tier is required.")
                role_codes = _validate_role_codes(threshold.get("approver_role_codes"))
                if not role_codes:
                    errors.append(f"thresholds[{idx}].approver_role_codes is required.")
                max_jmd = threshold.get("max_jmd")
                if max_jmd is None:
                    seen_open_ended = True
                else:
                    try:
                        parsed = float(max_jmd)
                        if parsed < 0:
                            errors.append(f"thresholds[{idx}].max_jmd must be >= 0.")
                    except (TypeError, ValueError):
                        errors.append(f"thresholds[{idx}].max_jmd must be numeric or null.")
            if not seen_open_ended:
                errors.append("thresholds must include one open-ended rule with max_jmd = null.")
        if default_approval is not None and not isinstance(default_approval, dict):
            errors.append("default_approval must be an object when provided.")

    normalized = dict(policy)
    normalized["workflow_type"] = workflow
    return normalized, errors


def _serialize_policy_result(config: TenantConfigValue | None, workflow_type: str) -> dict[str, Any] | None:
    if config is None:
        return None
    return {
        "tenant_id": config.tenant_id,
        "workflow_type": workflow_type,
        "config_id": config.config_id,
        "effective_date": config.effective_date.isoformat(),
        "expiry_date": config.expiry_date.isoformat() if config.expiry_date else None,
        "policy": config.value,
    }


def get_active_approval_policy(tenant_id: int, workflow_type: str) -> dict[str, Any] | None:
    workflow = _ensure_workflow_type(workflow_type)
    config = _fetch_effective_config(int(tenant_id), _approval_config_key(workflow))
    return _serialize_policy_result(config, workflow)


def get_draft_approval_policy(tenant_id: int, workflow_type: str) -> dict[str, Any] | None:
    workflow = _ensure_workflow_type(workflow_type)
    config = _fetch_latest_config(int(tenant_id), _approval_draft_config_key(workflow))
    return _serialize_policy_result(config, workflow)


@transaction.atomic
def save_approval_policy_draft(
    tenant_id: int,
    workflow_type: str,
    payload: object,
    actor: object,
) -> dict[str, Any]:
    workflow = _ensure_workflow_type(workflow_type)
    policy, errors = validate_approval_policy_payload(workflow, payload)
    if errors:
        raise TenantPolicyError("; ".join(errors))

    key = _approval_draft_config_key(workflow)
    actor_ref = _actor_ref(actor)
    serialized = _json_text(policy)
    today = timezone.localdate()
    now = timezone.now()

    latest = _fetch_latest_config(int(tenant_id), key)
    with connection.cursor() as cursor:
        if latest is None:
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
                    int(tenant_id),
                    key,
                    serialized,
                    "json",
                    today,
                    "Draft approval workflow policy",
                    actor_ref,
                    now,
                    actor_ref,
                    now,
                ],
            )
        else:
            cursor.execute(
                """
                UPDATE tenant_config
                SET
                    config_value = %s,
                    config_type = %s,
                    update_by_id = %s,
                    update_dtime = %s,
                    version_nbr = COALESCE(version_nbr, 1) + 1
                WHERE config_id = %s
                """,
                [serialized, "json", actor_ref, now, latest.config_id],
            )

    result = get_draft_approval_policy(int(tenant_id), workflow)
    if result is None:
        raise TenantPolicyError("Failed to save approval policy draft.")
    return result


@transaction.atomic
def publish_approval_policy(
    tenant_id: int,
    workflow_type: str,
    actor: object,
) -> dict[str, Any]:
    workflow = _ensure_workflow_type(workflow_type)
    actor_ref = _actor_ref(actor)
    today = timezone.localdate()
    now = timezone.now()

    draft = _fetch_latest_config(int(tenant_id), _approval_draft_config_key(workflow))
    if draft is None:
        raise TenantPolicyError("No draft approval policy found for this workflow.")

    active = _fetch_effective_config(int(tenant_id), _approval_config_key(workflow))
    current_version = 0
    if active is not None:
        active_version = active.value.get("version")
        try:
            current_version = int(active_version)
        except (TypeError, ValueError):
            current_version = 0

    policy = dict(draft.value)
    policy["workflow_type"] = workflow
    policy["version"] = current_version + 1
    policy["published_at"] = now.isoformat()
    policy["published_by"] = actor_ref
    serialized = _json_text(policy)

    with connection.cursor() as cursor:
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
                today - timedelta(days=1),
                actor_ref,
                now,
                int(tenant_id),
                _approval_config_key(workflow),
                today,
                today,
            ],
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
                int(tenant_id),
                _approval_config_key(workflow),
                serialized,
                "json",
                today,
                "Published approval workflow policy",
                actor_ref,
                now,
                actor_ref,
                now,
            ],
        )

    result = get_active_approval_policy(int(tenant_id), workflow)
    if result is None:
        raise TenantPolicyError("Failed to publish approval policy.")
    return result


def _latest_active_feature_rows(tenant_id: int) -> list[tuple]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                config_id,
                config_key,
                config_value,
                effective_date,
                expiry_date,
                update_dtime
            FROM tenant_config
            WHERE
                tenant_id = %s
                AND config_key LIKE %s
                AND effective_date <= CURRENT_DATE
                AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
            ORDER BY config_key ASC, effective_date DESC, update_dtime DESC, config_id DESC
            """,
            [tenant_id, f"{FEATURE_KEY_PREFIX}%"],
        )
        return cursor.fetchall()


def list_tenant_features(tenant_id: int) -> list[dict[str, Any]]:
    try:
        rows = _latest_active_feature_rows(int(tenant_id))
    except DatabaseError:
        return []

    seen_keys: set[str] = set()
    features: list[dict[str, Any]] = []
    for row in rows:
        key = str(row[1] or "")
        if key in seen_keys:
            continue
        seen_keys.add(key)
        value = _parse_json_dict(row[2]) or {}
        feature_key = key[len(FEATURE_KEY_PREFIX):] if key.startswith(FEATURE_KEY_PREFIX) else key
        features.append(
            {
                "feature_key": feature_key,
                "enabled": bool(value.get("enabled", False)),
                "settings": value.get("settings", {}),
                "effective_date": row[3].isoformat() if row[3] else None,
                "expiry_date": row[4].isoformat() if row[4] else None,
                "config_id": int(row[0]),
            }
        )
    return features


@transaction.atomic
def set_tenant_feature(
    tenant_id: int,
    feature_key: str,
    enabled: bool,
    settings: dict[str, Any] | None,
    actor: object,
) -> dict[str, Any]:
    key = _feature_config_key(feature_key)
    normalized_feature_key = key[len(FEATURE_KEY_PREFIX):]
    actor_ref = _actor_ref(actor)
    now = timezone.now()
    today = timezone.localdate()
    value = {
        "enabled": bool(enabled),
        "settings": settings if isinstance(settings, dict) else {},
    }
    serialized = _json_text(value)

    with connection.cursor() as cursor:
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
            [today - timedelta(days=1), actor_ref, now, int(tenant_id), key, today, today],
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
                int(tenant_id),
                key,
                serialized,
                "json",
                today,
                "Tenant feature flag",
                actor_ref,
                now,
                actor_ref,
                now,
            ],
        )

    latest = next(
        (feature for feature in list_tenant_features(int(tenant_id)) if feature["feature_key"] == normalized_feature_key),
        None,
    )
    if latest is None:
        latest = {
            "feature_key": normalized_feature_key,
            "enabled": bool(enabled),
            "settings": settings if isinstance(settings, dict) else {},
            "effective_date": today.isoformat(),
            "expiry_date": None,
        }
    return latest


def _block_role_codes(block: dict[str, Any], phase: str) -> list[str]:
    phase_key = str(phase or "").strip().upper() or "BASELINE"
    by_phase = block.get("approver_role_codes_by_phase")
    if isinstance(by_phase, dict):
        phase_codes = by_phase.get(phase_key) or by_phase.get("DEFAULT")
        codes = _validate_role_codes(phase_codes)
        if codes:
            return codes
    return _validate_role_codes(block.get("approver_role_codes"))


def _approval_from_block(block: dict[str, Any], phase: str) -> dict[str, Any] | None:
    role_codes = _block_role_codes(block, phase)
    if not role_codes:
        return None
    tier = str(block.get("tier") or "").strip()
    if not tier:
        return None
    methods_allowed = block.get("methods_allowed")
    if isinstance(methods_allowed, list):
        methods = [str(value).strip() for value in methods_allowed if str(value).strip()]
    else:
        methods = []
    approver_role = str(block.get("approver_role_label") or "").strip()
    if not approver_role:
        approver_role = role_codes[0]
    return {
        "tier": tier,
        "approver_role": approver_role,
        "approver_role_codes": role_codes,
        "methods_allowed": methods,
    }


def _coerce_cost(value: object) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def resolve_approval_from_tenant_policy(
    tenant_id: int | None,
    method: str,
    phase: str,
    total_cost: float | None,
    cost_missing: bool,
) -> tuple[dict[str, Any], list[str], str] | None:
    if tenant_id is None:
        return None
    workflow = _ensure_workflow_type(method or "C")
    active = get_active_approval_policy(int(tenant_id), workflow)
    if not active:
        return None
    policy = active.get("policy")
    if not isinstance(policy, dict):
        return None

    warnings: list[str] = []
    rationale = str(policy.get("rationale") or "").strip()
    if not rationale:
        rationale = "Approval tier resolved from tenant approval policy."

    if workflow in {"A", "B"}:
        block = policy.get("fixed_approval")
        if not isinstance(block, dict):
            block = policy
        approval = _approval_from_block(block, phase)
        if approval is None:
            warnings.append("tenant_policy_invalid_fallback")
            return None
        approval["policy_version"] = policy.get("version")
        return approval, warnings, rationale

    thresholds = policy.get("thresholds")
    if not isinstance(thresholds, list) or not thresholds:
        warnings.append("tenant_policy_invalid_fallback")
        return None

    selected_block: dict[str, Any] | None = None
    parsed_cost = _coerce_cost(total_cost)
    if cost_missing or parsed_cost is None:
        default_block = policy.get("default_approval")
        if isinstance(default_block, dict):
            selected_block = default_block
        else:
            for threshold in thresholds:
                if isinstance(threshold, dict) and threshold.get("max_jmd") is None:
                    selected_block = threshold
                    break
            if selected_block is None:
                selected_block = thresholds[-1] if isinstance(thresholds[-1], dict) else None
        warnings.append("approval_tier_conservative")
    else:
        selected_thresholds: list[dict[str, Any]] = [item for item in thresholds if isinstance(item, dict)]
        def _threshold_sort_key(item: dict[str, Any]) -> float:
            coerced = _coerce_cost(item.get("max_jmd"))
            return coerced if coerced is not None else float("inf")

        selected_thresholds.sort(key=_threshold_sort_key)
        for threshold in selected_thresholds:
            max_jmd = threshold.get("max_jmd")
            if max_jmd is None:
                selected_block = threshold
                break
            coerced = _coerce_cost(max_jmd)
            if coerced is None:
                continue
            if parsed_cost <= coerced:
                selected_block = threshold
                break

    if not isinstance(selected_block, dict):
        warnings.append("tenant_policy_invalid_fallback")
        return None

    approval = _approval_from_block(selected_block, phase)
    if approval is None:
        warnings.append("tenant_policy_invalid_fallback")
        return None
    approval["policy_version"] = policy.get("version")
    return approval, warnings, rationale
