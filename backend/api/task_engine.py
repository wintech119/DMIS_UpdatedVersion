from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence


TaskPredicate = Callable[[Mapping[str, Any]], bool]


@dataclass(frozen=True)
class TaskRule:
    task_code: str
    required_permissions: tuple[str, ...] = ()
    statuses: frozenset[str] = frozenset()
    permission_mode: str = "any"  # any | all | none
    requires_write_scope: bool = True
    predicate: TaskPredicate | None = None


def _normalize_permission_set(permissions: Iterable[str]) -> set[str]:
    return {
        str(permission or "").strip().lower()
        for permission in permissions
        if str(permission or "").strip()
    }


def _status_value(status: object) -> str:
    return str(status or "").strip().upper()


def _matches_permission(rule: TaskRule, permission_set: set[str]) -> bool:
    if not rule.required_permissions:
        return True
    required = {
        str(permission or "").strip().lower()
        for permission in rule.required_permissions
        if str(permission or "").strip()
    }
    if not required:
        return True
    mode = str(rule.permission_mode or "any").strip().lower()
    if mode not in {"any", "all", "none"}:
        raise ValueError(f"Unsupported permission_mode: {rule.permission_mode!r}")
    if mode == "all":
        return required.issubset(permission_set)
    if mode == "none":
        return not any(permission in permission_set for permission in required)
    return any(permission in permission_set for permission in required)


def resolve_available_tasks(
    rules: Sequence[TaskRule],
    *,
    status: object,
    permissions: Iterable[str],
    can_write_scope: bool,
    context: Mapping[str, Any] | None = None,
) -> list[str]:
    normalized_status = _status_value(status)
    permission_set = _normalize_permission_set(permissions)
    eval_context: Mapping[str, Any] = context or {}
    tasks: list[str] = []

    for rule in rules:
        if not rule.task_code:
            continue
        if rule.requires_write_scope and not can_write_scope:
            continue
        if rule.statuses and normalized_status not in rule.statuses:
            continue
        if not _matches_permission(rule, permission_set):
            continue
        if rule.predicate is not None and not bool(rule.predicate(eval_context)):
            continue
        if rule.task_code not in tasks:
            tasks.append(rule.task_code)
    return tasks
