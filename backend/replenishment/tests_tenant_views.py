from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from replenishment import views as replenishment_views
from replenishment.tenant_views import tenant_feature_detail


class TenantFeatureDetailEnabledParsingTests(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = APIRequestFactory()
        self.user = SimpleNamespace(
            is_authenticated=True,
            user_id="1",
            username="tester",
            roles=[],
            permissions=[],
        )

    @patch("replenishment.tenant_views.NeedsListPermission.has_permission", return_value=True)
    @patch("replenishment.tenant_views._tenant_scope_error")
    @patch("replenishment.tenant_views.tenant_policy.set_tenant_feature")
    def test_put_accepts_false_string_without_coercing_to_true(
        self,
        set_tenant_feature_mock,
        tenant_scope_error_mock,
        _mock_permission,
    ) -> None:
        tenant_scope_error_mock.return_value = None
        set_tenant_feature_mock.return_value = {"feature_key": "my_flag", "enabled": False, "settings": {}}
        request = self.factory.put("/replenishment/tenants/12/features/my_flag", {"enabled": "false"}, format="json")
        force_authenticate(request, user=self.user)

        response = tenant_feature_detail(request, tenant_id=12, feature_key="my_flag")

        self.assertEqual(response.status_code, 200)
        set_tenant_feature_mock.assert_called_once()
        self.assertFalse(set_tenant_feature_mock.call_args.kwargs["enabled"])

    @patch("replenishment.tenant_views.NeedsListPermission.has_permission", return_value=True)
    @patch("replenishment.tenant_views._tenant_scope_error")
    @patch("replenishment.tenant_views.tenant_policy.set_tenant_feature")
    def test_put_rejects_invalid_enabled_value(
        self,
        set_tenant_feature_mock,
        tenant_scope_error_mock,
        _mock_permission,
    ) -> None:
        tenant_scope_error_mock.return_value = None
        request = self.factory.put("/replenishment/tenants/12/features/my_flag", {"enabled": "maybe"}, format="json")
        force_authenticate(request, user=self.user)

        response = tenant_feature_detail(request, tenant_id=12, feature_key="my_flag")

        self.assertEqual(response.status_code, 400)
        self.assertIn("enabled", response.data.get("errors", {}))
        set_tenant_feature_mock.assert_not_called()


class ReplenishmentIdempotencyViewTests(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = APIRequestFactory()
        self.user = SimpleNamespace(
            is_authenticated=True,
            user_id="1",
            username="tester",
            roles=[],
            permissions=[],
        )

    @patch("replenishment.views.logger.exception")
    @patch("replenishment.views._release_idempotency_reservation")
    @patch("replenishment.views.cache.set", side_effect=RuntimeError("cache unavailable"))
    @patch("replenishment.views.transaction.on_commit")
    def test_cache_idempotent_response_after_commit_swallows_cache_write_failures(
        self,
        on_commit_mock,
        cache_set_mock,
        release_mock,
        logger_exception_mock,
    ) -> None:
        on_commit_mock.side_effect = lambda callback: callback()

        replenishment_views._cache_idempotent_response_after_commit(
            "cache-key",
            {"status": "ok"},
            request_fingerprint="fp",
            reservation_key="reservation-key",
            reservation_token="reservation-token",
        )

        on_commit_mock.assert_called_once()
        cache_set_mock.assert_called_once()
        release_mock.assert_called_once_with("reservation-key", "reservation-token")
        logger_exception_mock.assert_called_once()

    @patch("replenishment.views._high_risk_transition_rate_limit_response")
    @patch("replenishment.views._begin_idempotent_response")
    @patch("replenishment.views._cached_idempotent_response", return_value=None)
    @patch("replenishment.views._required_idempotency_key", return_value="idem-dispatch")
    @patch("replenishment.views._is_odpem_replenishment_only_record", return_value=False)
    @patch("replenishment.views._require_record_scope", return_value=None)
    @patch("replenishment.views.workflow_store.get_record")
    @patch("replenishment.views.NeedsListPermission.has_permission", return_value=True)
    def test_mark_dispatched_returns_in_progress_response_before_rate_limit(
        self,
        _permission_mock,
        get_record_mock,
        _scope_mock,
        _odpem_mock,
        _key_mock,
        _cached_mock,
        begin_mock,
        rate_limit_mock,
    ) -> None:
        get_record_mock.return_value = {
            "needs_list_id": "NL-1",
            "status": "IN_PREPARATION",
            "prep_started_at": "2026-04-23T00:00:00Z",
            "dispatched_at": None,
        }
        begin_mock.return_value = (
            "cache-key",
            "reservation-key",
            "reservation-token",
            Response({"cached": True}, status=200),
        )

        request = self.factory.post("/replenishment/needs-list/NL-1/mark-dispatched", {}, format="json")
        force_authenticate(request, user=self.user)

        response = replenishment_views.needs_list_mark_dispatched(request, needs_list_id="NL-1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"cached": True})
        rate_limit_mock.assert_not_called()

    @patch("replenishment.views._high_risk_transition_rate_limit_response")
    @patch("replenishment.views._begin_idempotent_response")
    @patch("replenishment.views._cached_idempotent_response", return_value=None)
    @patch("replenishment.views._required_idempotency_key", return_value="idem-receive")
    @patch("replenishment.views._is_odpem_replenishment_only_record", return_value=False)
    @patch("replenishment.views._require_record_scope", return_value=None)
    @patch("replenishment.views.workflow_store.get_record")
    @patch("replenishment.views.NeedsListPermission.has_permission", return_value=True)
    def test_mark_received_returns_in_progress_response_before_rate_limit(
        self,
        _permission_mock,
        get_record_mock,
        _scope_mock,
        _odpem_mock,
        _key_mock,
        _cached_mock,
        begin_mock,
        rate_limit_mock,
    ) -> None:
        get_record_mock.return_value = {
            "needs_list_id": "NL-1",
            "status": "DISPATCHED",
            "dispatched_at": "2026-04-23T01:00:00Z",
            "received_at": None,
        }
        begin_mock.return_value = (
            "cache-key",
            "reservation-key",
            "reservation-token",
            Response({"cached": True}, status=200),
        )

        request = self.factory.post("/replenishment/needs-list/NL-1/mark-received", {}, format="json")
        force_authenticate(request, user=self.user)

        response = replenishment_views.needs_list_mark_received(request, needs_list_id="NL-1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"cached": True})
        rate_limit_mock.assert_not_called()

    @patch("replenishment.views._high_risk_transition_rate_limit_response")
    @patch("replenishment.views._begin_idempotent_response")
    @patch("replenishment.views._allocation_context_from_record", return_value={})
    @patch("replenishment.views.resolve_roles_and_permissions", return_value=([], []))
    @patch("replenishment.views._normalize_selected_method_for_execution", return_value=None)
    @patch("replenishment.views._parse_allocation_selections", return_value=[])
    @patch("replenishment.views._status_matches", return_value=True)
    @patch("replenishment.views._execution_needs_list_pk", return_value=1)
    @patch("replenishment.views._execution_link_for_record", return_value=None)
    @patch("replenishment.views._cached_idempotent_response", return_value=None)
    @patch("replenishment.views._required_idempotency_key", return_value="idem-commit")
    @patch("replenishment.views._is_odpem_replenishment_only_record", return_value=False)
    @patch("replenishment.views._allocation_record_or_response")
    @patch("replenishment.views.NeedsListPermission.has_permission", return_value=True)
    def test_allocation_commit_returns_in_progress_response_before_rate_limit(
        self,
        _permission_mock,
        allocation_record_mock,
        _odpem_mock,
        _key_mock,
        _cached_mock,
        _link_mock,
        _needs_list_pk_mock,
        _status_matches_mock,
        _parse_mock,
        _selected_method_mock,
        _roles_mock,
        _context_mock,
        begin_mock,
        rate_limit_mock,
    ) -> None:
        allocation_record_mock.return_value = ({"needs_list_id": "NL-1", "status": "APPROVED"}, None)
        begin_mock.return_value = (
            "cache-key",
            "reservation-key",
            "reservation-token",
            Response({"cached": True}, status=200),
        )

        request = self.factory.post(
            "/replenishment/needs-list/NL-1/allocations/commit",
            {"allocations": [], "agency_id": 10, "urgency_ind": "H"},
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = replenishment_views.needs_list_allocations_commit(request, needs_list_id="NL-1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"cached": True})
        rate_limit_mock.assert_not_called()
