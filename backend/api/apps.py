from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self) -> None:
        # Register Django system checks for auth-boundary guardrails.
        from . import checks  # noqa: F401
