import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """
    Lightweight .env loader to keep local Postgres settings in one place without
    requiring an external dependency in backend requirements.
    """
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.lower().startswith("export "):
            key = key[7:].strip()
        if not key:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-insecure-key")
DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"
ENABLE_TEST_ROLES = os.getenv("ENABLE_TEST_ROLES", "0") == "1"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",")
    if host.strip()
]

if not DEBUG:
    if SECRET_KEY == "dev-only-insecure-key":
        raise RuntimeError("DEBUG is False but DJANGO_SECRET_KEY is still the dev default.")
    if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
        raise RuntimeError("DEBUG is False but DJANGO_ALLOWED_HOSTS is empty or contains '*'.")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "api",
    "replenishment",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "dmis_api.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "dmis_api.wsgi.application"
ASGI_APPLICATION = "dmis_api.asgi.application"

# DB changes require explicit approval; do not run migrate.
# PostgreSQL is the default/required runtime for replenishment RBAC and workflow.
use_sqlite = os.getenv("DJANGO_USE_SQLITE", "0") == "1"
allow_sqlite = os.getenv("DJANGO_ALLOW_SQLITE", "0") == "1"
if use_sqlite and not allow_sqlite:
    raise RuntimeError(
        "SQLite backend is disabled by default. "
        "Set DJANGO_ALLOW_SQLITE=1 only for temporary local tooling."
    )

if use_sqlite:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", ""),
            "USER": os.getenv("DB_USER", ""),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": os.getenv("DB_HOST", ""),
            "PORT": os.getenv("DB_PORT", "5432"),
        }
    }

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# AuthN/AuthZ configuration (env-driven; no claim-name assumptions).
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "0") == "1"
AUTH_ISSUER = os.getenv("AUTH_ISSUER", "")
AUTH_AUDIENCE = os.getenv("AUTH_AUDIENCE", "")
AUTH_JWKS_URL = os.getenv("AUTH_JWKS_URL", "")
AUTH_ALGORITHMS = [
    alg.strip()
    for alg in os.getenv("AUTH_ALGORITHMS", "RS256").split(",")
    if alg.strip()
]
AUTH_USER_ID_CLAIM = os.getenv("AUTH_USER_ID_CLAIM", "")
AUTH_USERNAME_CLAIM = os.getenv("AUTH_USERNAME_CLAIM", "")
AUTH_ROLES_CLAIM = os.getenv("AUTH_ROLES_CLAIM", "")

if "AUTH_USE_DB_RBAC" in os.environ:
    AUTH_USE_DB_RBAC = os.getenv("AUTH_USE_DB_RBAC", "0") == "1"
else:
    AUTH_USE_DB_RBAC = DATABASES["default"]["ENGINE"].endswith("postgresql")

if AUTH_ENABLED:
    missing = []
    if not AUTH_ISSUER:
        missing.append("AUTH_ISSUER")
    if not AUTH_AUDIENCE:
        missing.append("AUTH_AUDIENCE")
    if not AUTH_JWKS_URL:
        missing.append("AUTH_JWKS_URL")
    if not AUTH_USER_ID_CLAIM:
        missing.append("AUTH_USER_ID_CLAIM")
    if not AUTH_ALGORITHMS:
        missing.append("AUTH_ALGORITHMS")
    if not AUTH_USE_DB_RBAC and not AUTH_ROLES_CLAIM:
        missing.append("AUTH_ROLES_CLAIM")
    if missing:
        raise RuntimeError(
            "AUTH_ENABLED is true but required settings are missing: "
            + ", ".join(missing)
        )

DEV_AUTH_ENABLED = os.getenv("DEV_AUTH_ENABLED", "0") == "1"
DEV_AUTH_USER_ID = os.getenv("DEV_AUTH_USER_ID", "dev-user")
DEV_AUTH_ROLES = [role.strip() for role in os.getenv("DEV_AUTH_ROLES", "").split(",") if role.strip()]
DEV_AUTH_PERMISSIONS = [
    perm.strip()
    for perm in os.getenv(
        "DEV_AUTH_PERMISSIONS",
        (
            "replenishment.needs_list.preview,"
            "replenishment.needs_list.create_draft,"
            "replenishment.needs_list.edit_lines,"
            "replenishment.needs_list.submit"
        ),
    ).split(",")
    if perm.strip()
]

# Needs List Preview settings (TBD finalize from PRD/appendices).
def _get_csv_env(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if value is None:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]

def _get_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"Invalid {name} value: {raw!r}") from exc


def _get_int_env(name: str, default: int | None) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Invalid {name} value: {raw!r}") from exc


NEEDS_SAFETY_FACTOR = _get_float_env("NEEDS_SAFETY_FACTOR", 1.25)
NEEDS_HORIZON_A_DAYS = _get_int_env("NEEDS_HORIZON_A_DAYS", 7)
NEEDS_HORIZON_B_DAYS = _get_int_env("NEEDS_HORIZON_B_DAYS", None)
NEEDS_STRICT_INBOUND_DONATION_STATUSES = _get_csv_env(
    "NEEDS_STRICT_INBOUND_DONATION_STATUSES", ["V", "P"]
)
NEEDS_STRICT_INBOUND_TRANSFER_STATUSES = _get_csv_env(
    "NEEDS_STRICT_INBOUND_TRANSFER_STATUSES", ["V", "P"]
)
NEEDS_INVENTORY_ACTIVE_STATUS = os.getenv("NEEDS_INVENTORY_ACTIVE_STATUS", "A")
NEEDS_BURN_SOURCE = os.getenv("NEEDS_BURN_SOURCE", "reliefpkg")
NEEDS_BURN_FALLBACK = os.getenv("NEEDS_BURN_FALLBACK", "reliefrqst")
