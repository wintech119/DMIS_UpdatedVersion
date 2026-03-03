from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory

from replenishment.tenant_views import tenant_feature_detail


class TenantFeatureDetailEnabledParsingTests(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = APIRequestFactory()

    @patch("replenishment.tenant_views._tenant_scope_error")
    @patch("replenishment.tenant_views.tenant_policy.set_tenant_feature")
    def test_put_accepts_false_string_without_coercing_to_true(
        self,
        set_tenant_feature_mock,
        tenant_scope_error_mock,
    ) -> None:
        tenant_scope_error_mock.return_value = None
        set_tenant_feature_mock.return_value = {"feature_key": "my_flag", "enabled": False, "settings": {}}
        request = self.factory.put("/replenishment/tenants/12/features/my_flag", {"enabled": "false"}, format="json")
        request.user = SimpleNamespace(user_id="1", username="tester")

        response = tenant_feature_detail(request, tenant_id=12, feature_key="my_flag")

        self.assertEqual(response.status_code, 200)
        set_tenant_feature_mock.assert_called_once()
        self.assertFalse(set_tenant_feature_mock.call_args.kwargs["enabled"])

    @patch("replenishment.tenant_views._tenant_scope_error")
    @patch("replenishment.tenant_views.tenant_policy.set_tenant_feature")
    def test_put_rejects_invalid_enabled_value(
        self,
        set_tenant_feature_mock,
        tenant_scope_error_mock,
    ) -> None:
        tenant_scope_error_mock.return_value = None
        request = self.factory.put("/replenishment/tenants/12/features/my_flag", {"enabled": "maybe"}, format="json")
        request.user = SimpleNamespace(user_id="1", username="tester")

        response = tenant_feature_detail(request, tenant_id=12, feature_key="my_flag")

        self.assertEqual(response.status_code, 400)
        self.assertIn("enabled", response.data.get("errors", {}))
        set_tenant_feature_mock.assert_not_called()
