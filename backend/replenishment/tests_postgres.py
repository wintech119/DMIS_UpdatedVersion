import os
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import django
from django.apps import apps
from django.utils import timezone

if not apps.ready:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dmis_api.settings")
    django.setup()

from replenishment.services import data_access  # noqa: E402


@unittest.skipUnless(
    os.getenv("DJANGO_USE_POSTGRES_TEST") == "1",
    "Postgres integration test disabled (set DJANGO_USE_POSTGRES_TEST=1).",
)
class PostgresIntegrationSmokeTest(unittest.TestCase):
    def test_inventory_query_smoke(self) -> None:
        if os.getenv("DJANGO_USE_SQLITE", "0") == "1":
            self.skipTest("DJANGO_USE_SQLITE=1; Postgres integration test requires Postgres.")

        available, warnings, inventory_as_of = data_access.get_available_by_item(
            warehouse_id=1,
            as_of_dt=timezone.now(),
        )

        self.assertIsInstance(available, dict)
        self.assertIsInstance(warnings, list)
        self.assertNotIn("db_unavailable_preview_stub", warnings)
        self.assertTrue(inventory_as_of is None or hasattr(inventory_as_of, "isoformat"))
