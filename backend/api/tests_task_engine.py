from __future__ import annotations

from django.test import SimpleTestCase

from api.rbac import PERM_NEEDS_LIST_CANCEL, PERM_NEEDS_LIST_EXECUTE
from api.task_engine import TaskRule, resolve_available_tasks
from replenishment.views import _NEEDS_LIST_TASK_RULES


class TaskEngineTests(SimpleTestCase):
    def test_resolves_tasks_for_matching_status_and_permission(self) -> None:
        rules = (
            TaskRule(
                task_code="approve",
                required_permissions=("replenishment.needs_list.approve",),
                statuses=frozenset({"PENDING_APPROVAL"}),
            ),
            TaskRule(
                task_code="return",
                required_permissions=("replenishment.needs_list.return",),
                statuses=frozenset({"PENDING_APPROVAL"}),
            ),
        )

        tasks = resolve_available_tasks(
            rules,
            status="PENDING_APPROVAL",
            permissions=["replenishment.needs_list.return"],
            can_write_scope=True,
        )

        self.assertEqual(tasks, ["return"])

    def test_requires_write_scope_when_rule_demands_it(self) -> None:
        rules = (
            TaskRule(
                task_code="submit",
                required_permissions=("replenishment.needs_list.submit",),
                statuses=frozenset({"DRAFT"}),
                requires_write_scope=True,
            ),
        )

        tasks = resolve_available_tasks(
            rules,
            status="DRAFT",
            permissions=["replenishment.needs_list.submit"],
            can_write_scope=False,
        )

        self.assertEqual(tasks, [])

    def test_permission_mode_all_requires_all_permissions(self) -> None:
        rules = (
            TaskRule(
                task_code="publish_policy",
                required_permissions=("tenant.approval_policy.view", "tenant.approval_policy.manage"),
                permission_mode="all",
            ),
        )

        self.assertEqual(
            resolve_available_tasks(
                rules,
                status="ANY",
                permissions=["tenant.approval_policy.view"],
                can_write_scope=True,
            ),
            [],
        )
        self.assertEqual(
            resolve_available_tasks(
                rules,
                status="ANY",
                permissions=["tenant.approval_policy.view", "tenant.approval_policy.manage"],
                can_write_scope=True,
            ),
            ["publish_policy"],
        )

    def test_permission_mode_none_requires_absence_of_required_permissions(self) -> None:
        rules = (
            TaskRule(
                task_code="can_request_access",
                required_permissions=("tenant.approval_policy.manage",),
                permission_mode="none",
            ),
        )

        self.assertEqual(
            resolve_available_tasks(
                rules,
                status="ANY",
                permissions=["tenant.approval_policy.view"],
                can_write_scope=True,
            ),
            ["can_request_access"],
        )
        self.assertEqual(
            resolve_available_tasks(
                rules,
                status="ANY",
                permissions=["tenant.approval_policy.manage"],
                can_write_scope=True,
            ),
            [],
        )

    def test_predicate_allows_domain_specific_guard(self) -> None:
        rules = (
            TaskRule(
                task_code="escalate",
                required_permissions=("replenishment.needs_list.escalate",),
                predicate=lambda ctx: bool(ctx.get("record", {}).get("escalation_allowed")),
            ),
        )

        without_flag = resolve_available_tasks(
            rules,
            status="PENDING_APPROVAL",
            permissions=["replenishment.needs_list.escalate"],
            can_write_scope=True,
            context={"record": {"escalation_allowed": False}},
        )
        with_flag = resolve_available_tasks(
            rules,
            status="PENDING_APPROVAL",
            permissions=["replenishment.needs_list.escalate"],
            can_write_scope=True,
            context={"record": {"escalation_allowed": True}},
        )

        self.assertEqual(without_flag, [])
        self.assertEqual(with_flag, ["escalate"])

    def test_unsupported_permission_mode_raises_value_error(self) -> None:
        rules = (
            TaskRule(
                task_code="bad_mode_rule",
                required_permissions=("tenant.approval_policy.view",),
                permission_mode="ANYY",
            ),
        )

        with self.assertRaisesMessage(ValueError, "Unsupported permission_mode"):
            resolve_available_tasks(
                rules,
                status="ANY",
                permissions=["tenant.approval_policy.view"],
                can_write_scope=True,
            )

    def test_status_matching_is_case_insensitive(self) -> None:
        rules = (
            TaskRule(
                task_code="review",
                required_permissions=("tenant.approval_policy.view",),
                statuses=frozenset({"pending_approval"}),
            ),
        )

        tasks = resolve_available_tasks(
            rules,
            status="PENDING_APPROVAL",
            permissions=["tenant.approval_policy.view"],
            can_write_scope=True,
        )

        self.assertEqual(tasks, ["review"])


class NeedsListExecutionTaskRuleTests(SimpleTestCase):
    def _resolve(self, status: str, record: dict[str, object] | None = None) -> list[str]:
        effective_record = record or {"status": status}
        return resolve_available_tasks(
            _NEEDS_LIST_TASK_RULES,
            status=status,
            permissions=[PERM_NEEDS_LIST_EXECUTE],
            can_write_scope=True,
            context={"record": effective_record},
        )

    def test_start_preparation_only_for_approved_status(self) -> None:
        tasks = self._resolve("APPROVED")
        self.assertIn("start_preparation", tasks)
        self.assertNotIn("mark_dispatched", tasks)
        self.assertNotIn("mark_received", tasks)
        self.assertNotIn("mark_completed", tasks)

    def test_mark_dispatched_only_for_preparation_stage_statuses(self) -> None:
        in_preparation_tasks = self._resolve("IN_PREPARATION")
        dispatched_tasks = self._resolve("DISPATCHED")

        self.assertIn("mark_dispatched", in_preparation_tasks)
        self.assertNotIn("mark_dispatched", dispatched_tasks)
        self.assertIn("mark_received", dispatched_tasks)

    def test_in_progress_stage_predicates_gate_execution_actions(self) -> None:
        prep_started_tasks = self._resolve(
            "IN_PROGRESS",
            {
                "status": "IN_PROGRESS",
                "prep_started_at": "2026-01-01T00:00:00Z",
                "dispatched_at": None,
                "received_at": None,
                "completed_at": None,
            },
        )
        dispatched_tasks = self._resolve(
            "IN_PROGRESS",
            {
                "status": "IN_PROGRESS",
                "prep_started_at": "2026-01-01T00:00:00Z",
                "dispatched_at": "2026-01-01T01:00:00Z",
                "received_at": None,
                "completed_at": None,
            },
        )

        self.assertIn("mark_dispatched", prep_started_tasks)
        self.assertNotIn("mark_received", prep_started_tasks)
        self.assertNotIn("mark_completed", prep_started_tasks)
        self.assertIn("mark_received", dispatched_tasks)
        self.assertNotIn("mark_dispatched", dispatched_tasks)


class NeedsListCancelTaskRuleTests(SimpleTestCase):
    def _resolve_with_record(self, status: str, record: dict[str, object] | None = None) -> list[str]:
        effective_record = record or {"status": status}
        return resolve_available_tasks(
            _NEEDS_LIST_TASK_RULES,
            status=status,
            permissions=[PERM_NEEDS_LIST_CANCEL],
            can_write_scope=True,
            context={"record": effective_record},
        )

    def test_cancel_not_advertised_for_dispatched_or_received(self) -> None:
        self.assertNotIn("cancel", self._resolve_with_record("DISPATCHED"))
        self.assertNotIn("cancel", self._resolve_with_record("RECEIVED"))

    def test_cancel_not_advertised_after_dispatch_metadata_exists(self) -> None:
        tasks = self._resolve_with_record(
            "IN_PROGRESS",
            {
                "status": "IN_PROGRESS",
                "dispatched_at": "2026-01-01T01:00:00Z",
                "received_at": None,
                "completed_at": None,
            },
        )
        self.assertNotIn("cancel", tasks)
