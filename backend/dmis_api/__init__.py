"""
Django project package for the migration API.
"""

try:
    from .celery import app as celery_app
except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional local env setup.
    if exc.name != "celery":
        raise
    celery_app = None

__all__ = ("celery_app",)
