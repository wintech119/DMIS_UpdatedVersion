from django.test import TestCase

from dmis_api.settings import validate_runtime_module_configuration


class ModuleGatingValidatorTests(TestCase):
    def test_validator_rejects_replenishment_enabled_in_staging(self):
        with self.assertRaises(RuntimeError):
            validate_runtime_module_configuration(
                runtime_env="staging",
                replenishment_enabled=True,
                operations_enabled=False,
                testing=False,
            )

    def test_validator_allows_local_harness(self):
        validate_runtime_module_configuration(
            runtime_env="local-harness",
            replenishment_enabled=True,
            operations_enabled=True,
            testing=False,
        )

    def test_validator_skipped_when_testing(self):
        validate_runtime_module_configuration(
            runtime_env="staging",
            replenishment_enabled=True,
            operations_enabled=True,
            testing=True,
        )
