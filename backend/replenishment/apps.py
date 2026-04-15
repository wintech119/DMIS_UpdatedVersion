import logging

from django.apps import AppConfig
from django.db.models.signals import post_migrate


logger = logging.getLogger("dmis.audit")


def _bootstrap_workflow_metadata_table(**kwargs) -> None:
    app_config = kwargs.get("app_config")
    if app_config is None or app_config.name != "replenishment":
        return
    using = kwargs.get("using")

    from . import workflow_store_db

    workflow_store_db._ensure_workflow_metadata_table(using=using)
    logger.info(
        "workflow_metadata.bootstrap_complete",
        extra={
            "event": "workflow_metadata.bootstrap_complete",
            "database": using or "default",
        },
    )


class ReplenishmentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "replenishment"

    def ready(self) -> None:
        post_migrate.connect(
            _bootstrap_workflow_metadata_table,
            sender=self,
            dispatch_uid="replenishment.bootstrap_workflow_metadata_table",
        )
