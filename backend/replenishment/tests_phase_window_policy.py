from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from replenishment.services import phase_window_policy


class PhaseWindowPolicyTests(SimpleTestCase):
    @patch("replenishment.services.phase_window_policy._fetch_active_event_phase_config", return_value=None)
    def test_effective_phase_windows_fall_back_to_rules(self, _mock_fetch) -> None:
        windows = phase_window_policy.get_effective_phase_windows(1, "SURGE")
        self.assertEqual(windows["source"], "rules_default")
        self.assertEqual(windows["phase"], "SURGE")
        self.assertGreater(windows["planning_hours"], 0)
        self.assertGreater(windows["demand_hours"], 0)

    @patch("replenishment.services.phase_window_policy._fetch_active_event_phase_config")
    def test_effective_phase_windows_use_event_config(self, mock_fetch) -> None:
        mock_fetch.return_value = SimpleNamespace(
            demand_window_hours=12,
            planning_window_hours=144,
            config_id=99,
        )
        windows = phase_window_policy.get_effective_phase_windows(42, "STABILIZED")
        self.assertEqual(windows["source"], "event_phase_config")
        self.assertEqual(windows["demand_hours"], 12)
        self.assertEqual(windows["planning_hours"], 144)
        self.assertEqual(windows["config_id"], 99)

    def test_invalid_phase_raises_error(self) -> None:
        with self.assertRaises(phase_window_policy.PhaseWindowPolicyError):
            phase_window_policy.get_effective_phase_windows(1, "INVALID")
