from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase

from replenishment.services import tenant_policy


class TenantPolicyServiceTests(SimpleTestCase):
    def test_validate_workflow_a_requires_fixed_roles_and_tier(self) -> None:
        normalized, errors = tenant_policy.validate_approval_policy_payload("A", {"fixed_approval": {}})

        self.assertEqual(normalized.get("workflow_type"), "A")
        self.assertTrue(
            any("approver_role_codes" in message for message in errors),
            "Expected approver_role_codes validation error for workflow A.",
        )
        self.assertTrue(
            any("tier" in message for message in errors),
            "Expected tier validation error for workflow A.",
        )

    def test_validate_workflow_c_requires_open_ended_threshold(self) -> None:
        payload = {
            "thresholds": [
                {"tier": "C1", "max_jmd": 1000, "approver_role_codes": ["PARISH_MANAGER"]},
            ]
        }
        _, errors = tenant_policy.validate_approval_policy_payload("C", payload)

        self.assertIn(
            "thresholds must include one open-ended rule with max_jmd = null.",
            errors,
        )

    @patch("replenishment.services.tenant_policy.get_active_approval_policy")
    def test_resolve_approval_from_policy_uses_threshold(self, get_active_approval_policy) -> None:
        get_active_approval_policy.return_value = {
            "policy": {
                "version": 4,
                "thresholds": [
                    {
                        "tier": "C2",
                        "max_jmd": 5000,
                        "approver_role_codes": ["PARISH_MANAGER"],
                    },
                    {
                        "tier": "C3",
                        "max_jmd": None,
                        "approver_role_codes": ["NEOC_EXECUTIVE"],
                    },
                ],
            }
        }

        result = tenant_policy.resolve_approval_from_tenant_policy(
            tenant_id=12,
            method="C",
            phase="BASELINE",
            total_cost=3000,
            cost_missing=False,
        )

        self.assertIsNotNone(result)
        approval, warnings, rationale = result  # type: ignore[misc]
        self.assertEqual(approval["tier"], "C2")
        self.assertEqual(approval["approver_role_codes"], ["PARISH_MANAGER"])
        self.assertEqual(approval["policy_version"], 4)
        self.assertEqual(warnings, [])
        self.assertIn("tenant approval policy", rationale.lower())

    @patch("replenishment.services.tenant_policy.get_active_approval_policy")
    def test_resolve_approval_returns_none_when_policy_missing(self, get_active_approval_policy) -> None:
        get_active_approval_policy.return_value = None

        result = tenant_policy.resolve_approval_from_tenant_policy(
            tenant_id=12,
            method="C",
            phase="BASELINE",
            total_cost=1200,
            cost_missing=False,
        )

        self.assertIsNone(result)

    @patch("replenishment.services.tenant_policy.get_active_approval_policy")
    def test_resolve_approval_skips_non_numeric_threshold_max_jmd(self, get_active_approval_policy) -> None:
        get_active_approval_policy.return_value = {
            "policy": {
                "version": 7,
                "thresholds": [
                    {
                        "tier": "C_BAD",
                        "max_jmd": "legacy-non-numeric",
                        "approver_role_codes": ["PARISH_MANAGER"],
                    },
                    {
                        "tier": "C_GOOD",
                        "max_jmd": 2000,
                        "approver_role_codes": ["PARISH_MANAGER"],
                    },
                    {
                        "tier": "C_FALLBACK",
                        "max_jmd": None,
                        "approver_role_codes": ["NEOC_EXECUTIVE"],
                    },
                ],
            }
        }

        result = tenant_policy.resolve_approval_from_tenant_policy(
            tenant_id=21,
            method="C",
            phase="BASELINE",
            total_cost=1500,
            cost_missing=False,
        )

        self.assertIsNotNone(result)
        approval, warnings, _rationale = result  # type: ignore[misc]
        self.assertEqual(approval["tier"], "C_GOOD")
        self.assertEqual(warnings, [])
