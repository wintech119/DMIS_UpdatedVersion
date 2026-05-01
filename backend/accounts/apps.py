from django.apps import AppConfig


def _run_rbac_bridge_sync(**kwargs) -> None:
    if kwargs.get("using") not in (None, "default"):
        return

    from django.core.management import call_command

    call_command(
        "sync_rbac_to_django_auth",
        verbosity=kwargs.get("verbosity", 0),
    )


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self) -> None:
        from django.conf import settings
        from django.db.models.signals import post_migrate

        if getattr(settings, "RBAC_BRIDGE_AUTORUN_ON_MIGRATE", False):
            post_migrate.connect(
                _run_rbac_bridge_sync,
                sender=self,
                dispatch_uid="accounts.sync_rbac_to_django_auth",
            )
