import logging
import hashlib
import os
import sys
import warnings
from importlib import import_module
from pathlib import Path
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parent.parent


def _detect_testing(argv: list[str] | tuple[str, ...] | None = None, env: dict[str, str] | None = None) -> bool:
    runtime_argv = list(sys.argv[1:] if argv is None else argv)
    runtime_env = os.environ if env is None else env
    return (
        any(arg == "test" or arg.startswith("test") for arg in runtime_argv)
        or any("pytest" in arg.lower() for arg in runtime_argv)
        or str(runtime_env.get("RUNNING_TESTS", "0")) == "1"
    )


TESTING = _detect_testing()

if TESTING:
    # Reduce noisy request logging and known test-only datetime warnings
    # so large suites are less likely to overwhelm local terminals/worktrees.
    LOGGING = {
        'version': 1,
        'disable_existing_loggers': False,
        'handlers': {
            'null': {'class': 'logging.NullHandler'},
        },
        'loggers': {
            'dmis': {'handlers': ['null'], 'level': 'CRITICAL', 'propagate': False},
            'django.request': {'handlers': ['null'], 'level': 'CRITICAL', 'propagate': False},
            'django.server': {'handlers': ['null'], 'level': 'CRITICAL', 'propagate': False},
        },
    }
    warnings.filterwarnings(
        'ignore',
        message=r'DateTimeField .* received a naive datetime .* while time zone support is active\.',
        category=RuntimeWarning,
    )


def _load_env_file(path: Path, *, override: bool = False) -> None:
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
        if override:
            os.environ[key] = value
        else:
            os.environ.setdefault(key, value)


def _get_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _get_int_env(name: str, default: int | None) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Invalid {name} value: {raw!r}") from exc


def _get_csv_env(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if value is None:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def _build_debug_secret_key() -> str:
    seed = "|".join(
        [
            str(BASE_DIR),
            sys.executable,
            os.getenv("USERNAME", os.getenv("USER", "")),
            os.getenv("COMPUTERNAME", os.getenv("HOSTNAME", "")),
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"debug-{digest}{digest[:24]}"


_LOCAL_ENV_COMMANDS = {"runserver", "shell", "dbshell"}
_RUNTIME_ENVIRONMENTS = {
    "local-harness",
    "prod-like-local",
    "shared-dev",
    "staging",
    "production",
}
_REAL_AUTH_ONLY_RUNTIME_ENVIRONMENTS = {
    "prod-like-local",
    "shared-dev",
    "staging",
    "production",
}
_REDIS_REQUIRED_RUNTIME_ENVIRONMENTS = {
    "prod-like-local",
    "shared-dev",
    "staging",
    "production",
}
_WORKER_REQUIRED_RUNTIME_ENVIRONMENTS = {
    "prod-like-local",
    "shared-dev",
    "staging",
    "production",
}
_SUPPORTED_REDIS_URL_SCHEMES = {"redis", "rediss", "unix"}
_REDIS_CACHE_BACKEND = "django_redis.cache.RedisCache"
_LOCMEM_CACHE_BACKEND = "django.core.cache.backends.locmem.LocMemCache"
_LOCAL_ONLY_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1", "0.0.0.0"}
_PLACEHOLDER_SECRET_KEYS = {
    "",
    "<generate-secure-random-key>",
    "changeme",
    "change-me",
    "replace-me",
    "replace_me",
    "replace-with-a-long-random-secret",
    "your-secret-key",
    "your_secret_key",
}
_EXPECTED_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
_RUNTIME_SECURITY_PROFILES = {
    "local-harness": {
        "require_explicit_secret_key": False,
        "require_explicit_allowed_hosts": False,
        "require_non_loopback_allowed_hosts": False,
        "secure_ssl_redirect_default": False,
        "session_cookie_secure_default": False,
        "csrf_cookie_secure_default": False,
        "secure_hsts_seconds_default": 0,
        "secure_hsts_include_subdomains_default": False,
        "secure_hsts_preload_default": False,
        "x_frame_options_default": "DENY",
        "secure_referrer_policy_default": "same-origin",
        "required_secure_ssl_redirect": None,
        "required_session_cookie_secure": None,
        "required_csrf_cookie_secure": None,
        "required_secure_hsts_seconds": None,
        "required_secure_hsts_include_subdomains": None,
        "required_secure_hsts_preload": None,
        "allow_hsts_preload_opt_in": False,
        "required_x_frame_options": None,
        "required_secure_referrer_policy": None,
        "required_proxy_ssl_header": None,
    },
    "prod-like-local": {
        "require_explicit_secret_key": True,
        "require_explicit_allowed_hosts": True,
        "require_non_loopback_allowed_hosts": False,
        "secure_ssl_redirect_default": False,
        "session_cookie_secure_default": False,
        "csrf_cookie_secure_default": False,
        "secure_hsts_seconds_default": 0,
        "secure_hsts_include_subdomains_default": False,
        "secure_hsts_preload_default": False,
        "x_frame_options_default": "DENY",
        "secure_referrer_policy_default": "same-origin",
        "required_secure_ssl_redirect": None,
        "required_session_cookie_secure": None,
        "required_csrf_cookie_secure": None,
        "required_secure_hsts_seconds": None,
        "required_secure_hsts_include_subdomains": None,
        "required_secure_hsts_preload": None,
        "allow_hsts_preload_opt_in": False,
        "required_x_frame_options": None,
        "required_secure_referrer_policy": None,
        "required_proxy_ssl_header": None,
    },
    "shared-dev": {
        "require_explicit_secret_key": True,
        "require_explicit_allowed_hosts": True,
        "require_non_loopback_allowed_hosts": True,
        "secure_ssl_redirect_default": True,
        "session_cookie_secure_default": True,
        "csrf_cookie_secure_default": True,
        "secure_hsts_seconds_default": 3600,
        "secure_hsts_include_subdomains_default": False,
        "secure_hsts_preload_default": False,
        "x_frame_options_default": "DENY",
        "secure_referrer_policy_default": "strict-origin-when-cross-origin",
        "required_secure_ssl_redirect": True,
        "required_session_cookie_secure": True,
        "required_csrf_cookie_secure": True,
        "required_secure_hsts_seconds": 3600,
        "required_secure_hsts_include_subdomains": False,
        "required_secure_hsts_preload": False,
        "allow_hsts_preload_opt_in": False,
        "required_x_frame_options": "DENY",
        "required_secure_referrer_policy": "strict-origin-when-cross-origin",
        "required_proxy_ssl_header": _EXPECTED_PROXY_SSL_HEADER,
    },
    "staging": {
        "require_explicit_secret_key": True,
        "require_explicit_allowed_hosts": True,
        "require_non_loopback_allowed_hosts": True,
        "secure_ssl_redirect_default": True,
        "session_cookie_secure_default": True,
        "csrf_cookie_secure_default": True,
        "secure_hsts_seconds_default": 86400,
        "secure_hsts_include_subdomains_default": False,
        "secure_hsts_preload_default": False,
        "x_frame_options_default": "DENY",
        "secure_referrer_policy_default": "strict-origin-when-cross-origin",
        "required_secure_ssl_redirect": True,
        "required_session_cookie_secure": True,
        "required_csrf_cookie_secure": True,
        "required_secure_hsts_seconds": 86400,
        "required_secure_hsts_include_subdomains": False,
        "required_secure_hsts_preload": False,
        "allow_hsts_preload_opt_in": False,
        "required_x_frame_options": "DENY",
        "required_secure_referrer_policy": "strict-origin-when-cross-origin",
        "required_proxy_ssl_header": _EXPECTED_PROXY_SSL_HEADER,
    },
    "production": {
        "require_explicit_secret_key": True,
        "require_explicit_allowed_hosts": True,
        "require_non_loopback_allowed_hosts": True,
        "secure_ssl_redirect_default": True,
        "session_cookie_secure_default": True,
        "csrf_cookie_secure_default": True,
        "secure_hsts_seconds_default": 31536000,
        "secure_hsts_include_subdomains_default": True,
        "secure_hsts_preload_default": False,
        "x_frame_options_default": "DENY",
        "secure_referrer_policy_default": "strict-origin-when-cross-origin",
        "required_secure_ssl_redirect": True,
        "required_session_cookie_secure": True,
        "required_csrf_cookie_secure": True,
        "required_secure_hsts_seconds": 31536000,
        "required_secure_hsts_include_subdomains": True,
        "required_secure_hsts_preload": None,
        "allow_hsts_preload_opt_in": True,
        "required_x_frame_options": "DENY",
        "required_secure_referrer_policy": "strict-origin-when-cross-origin",
        "required_proxy_ssl_header": _EXPECTED_PROXY_SSL_HEADER,
    },
}


def _get_runtime_security_profile(runtime_env: str) -> dict[str, object]:
    if runtime_env == "test":
        return _RUNTIME_SECURITY_PROFILES["local-harness"]
    return _RUNTIME_SECURITY_PROFILES[runtime_env]


def _is_placeholder_secret_key(secret_key: str) -> bool:
    normalized = secret_key.strip().lower()
    return normalized in _PLACEHOLDER_SECRET_KEYS or secret_key.startswith("debug-")


def _is_url_shaped_allowed_host(host: str) -> bool:
    normalized = host.strip().lower()
    return "://" in normalized or "/" in normalized


def _is_loopback_allowed_host(host: str) -> bool:
    return host.strip().lower() in _LOCAL_ONLY_ALLOWED_HOSTS


def _normalize_proxy_ssl_header(value) -> tuple[str, str] | None:
    if not value:
        return None
    if isinstance(value, tuple) and len(value) == 2:
        return value
    if isinstance(value, list) and len(value) == 2:
        return (str(value[0]), str(value[1]))
    return None


def _should_load_local_env() -> bool:
    if _get_bool_env("DMIS_SKIP_LOCAL_ENV", False):
        return False
    if _get_bool_env("DMIS_LOAD_LOCAL_ENV", False):
        return True
    return any(arg in _LOCAL_ENV_COMMANDS for arg in sys.argv[1:])


def _normalize_runtime_environment(*, testing: bool) -> str:
    raw = os.getenv("DMIS_RUNTIME_ENV", "").strip().lower()
    if testing:
        return raw if raw in _RUNTIME_ENVIRONMENTS else "test"
    if raw not in _RUNTIME_ENVIRONMENTS:
        allowed = ", ".join(sorted(_RUNTIME_ENVIRONMENTS))
        raise RuntimeError(
            "DMIS_RUNTIME_ENV must be set to one of: "
            + allowed
            + ". Shared dev, staging, and production must declare their runtime posture explicitly."
        )
    return raw


def validate_runtime_auth_configuration(
    *,
    runtime_env: str,
    debug: bool,
    auth_enabled: bool,
    dev_auth_enabled: bool,
    local_auth_harness_enabled: bool,
    testing: bool,
) -> None:
    if testing:
        return

    if runtime_env == "local-harness":
        if auth_enabled:
            raise RuntimeError(
                "DMIS_RUNTIME_ENV=local-harness requires AUTH_ENABLED=0."
            )
        if not dev_auth_enabled:
            raise RuntimeError(
                "DMIS_RUNTIME_ENV=local-harness requires DEV_AUTH_ENABLED=1."
            )
        if not local_auth_harness_enabled:
            raise RuntimeError(
                "DMIS_RUNTIME_ENV=local-harness requires LOCAL_AUTH_HARNESS_ENABLED=1."
            )
        if not debug:
            raise RuntimeError(
                "DMIS_RUNTIME_ENV=local-harness requires DJANGO_DEBUG=1."
            )
        return

    if runtime_env in _REAL_AUTH_ONLY_RUNTIME_ENVIRONMENTS:
        if not auth_enabled:
            raise RuntimeError(
                f"DMIS_RUNTIME_ENV={runtime_env} requires AUTH_ENABLED=1."
            )
        if dev_auth_enabled:
            raise RuntimeError(
                f"DMIS_RUNTIME_ENV={runtime_env} requires DEV_AUTH_ENABLED=0."
            )
        if local_auth_harness_enabled:
            raise RuntimeError(
                f"DMIS_RUNTIME_ENV={runtime_env} requires LOCAL_AUTH_HARNESS_ENABLED=0."
            )
        if debug:
            raise RuntimeError(
                f"DMIS_RUNTIME_ENV={runtime_env} requires DJANGO_DEBUG=0."
            )


def default_auth_enabled_for_runtime_env(*, runtime_env: str, testing: bool) -> bool:
    if testing:
        return False
    return runtime_env in _REAL_AUTH_ONLY_RUNTIME_ENVIRONMENTS


def redis_required_for_runtime_env(*, runtime_env: str, testing: bool) -> bool:
    if testing or runtime_env == "test":
        return False
    return runtime_env in _REDIS_REQUIRED_RUNTIME_ENVIRONMENTS


def worker_required_for_runtime_env(*, runtime_env: str, testing: bool) -> bool:
    if testing or runtime_env == "test":
        return False
    return runtime_env in _WORKER_REQUIRED_RUNTIME_ENVIRONMENTS


def default_async_eager_for_runtime_env(*, runtime_env: str, testing: bool) -> bool:
    if testing or runtime_env == "test":
        return True
    return runtime_env == "local-harness"


def default_durable_export_retention_seconds_for_runtime_env(
    *,
    runtime_env: str,
    testing: bool,
) -> int:
    if testing or runtime_env in {"test", "local-harness"}:
        return 86400
    return 7776000


def _validate_redis_url(redis_url: str, *, runtime_env: str) -> None:
    parsed = urlparse(redis_url)
    if parsed.scheme not in _SUPPORTED_REDIS_URL_SCHEMES:
        allowed = ", ".join(sorted(_SUPPORTED_REDIS_URL_SCHEMES))
        raise RuntimeError(
            f"DMIS_RUNTIME_ENV={runtime_env} requires REDIS_URL to use one of the supported schemes: {allowed}."
        )
    if parsed.scheme == "unix":
        if not parsed.path:
            raise RuntimeError(
                f"DMIS_RUNTIME_ENV={runtime_env} requires REDIS_URL to include a unix socket path."
            )
        return
    if not parsed.hostname:
        raise RuntimeError(
            f"DMIS_RUNTIME_ENV={runtime_env} requires REDIS_URL to include a hostname."
        )


def validate_runtime_redis_configuration(
    *,
    runtime_env: str,
    redis_url: str,
    cache_backend: str,
    testing: bool,
) -> None:
    if testing or runtime_env == "test":
        return

    normalized_redis_url = redis_url.strip()
    redis_required = redis_required_for_runtime_env(
        runtime_env=runtime_env,
        testing=testing,
    )

    if not normalized_redis_url:
        if redis_required:
            raise RuntimeError(
                f"DMIS_RUNTIME_ENV={runtime_env} requires REDIS_URL because Redis is a mandatory runtime dependency."
            )
        if runtime_env == "local-harness" and cache_backend != _LOCMEM_CACHE_BACKEND:
            raise RuntimeError(
                "DMIS_RUNTIME_ENV=local-harness without REDIS_URL requires the default cache backend to remain LocMemCache."
            )
        return

    _validate_redis_url(normalized_redis_url, runtime_env=runtime_env)

    if cache_backend != _REDIS_CACHE_BACKEND:
        raise RuntimeError(
            f"DMIS_RUNTIME_ENV={runtime_env} with REDIS_URL configured requires the default cache backend to be {_REDIS_CACHE_BACKEND}."
        )

    try:
        import_module("django_redis.cache")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"DMIS_RUNTIME_ENV={runtime_env} with REDIS_URL configured requires the django-redis package to be installed."
        ) from exc


def validate_runtime_async_configuration(
    *,
    runtime_env: str,
    async_eager: bool,
    worker_required: bool,
    redis_url: str,
    broker_url: str,
    result_backend: str,
    testing: bool,
) -> None:
    if testing or runtime_env == "test":
        return

    normalized_redis_url = redis_url.strip()
    normalized_broker_url = broker_url.strip()
    normalized_result_backend = result_backend.strip()

    if worker_required and async_eager:
        raise RuntimeError(
            f"DMIS_RUNTIME_ENV={runtime_env} requires DMIS_ASYNC_EAGER=0 so a real worker plane is active."
        )

    if worker_required and not normalized_redis_url:
        raise RuntimeError(
            f"DMIS_RUNTIME_ENV={runtime_env} requires REDIS_URL because Redis-backed async queueing is mandatory."
        )

    if async_eager:
        return

    if not normalized_broker_url:
        raise RuntimeError(
            f"DMIS_RUNTIME_ENV={runtime_env} requires CELERY_BROKER_URL or REDIS_URL when DMIS_ASYNC_EAGER=0."
        )
    if not normalized_result_backend:
        raise RuntimeError(
            f"DMIS_RUNTIME_ENV={runtime_env} requires CELERY_RESULT_BACKEND or REDIS_URL when DMIS_ASYNC_EAGER=0."
        )

    _validate_redis_url(normalized_broker_url, runtime_env=runtime_env)
    _validate_redis_url(normalized_result_backend, runtime_env=runtime_env)

    try:
        import_module("celery")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"DMIS_RUNTIME_ENV={runtime_env} with DMIS_ASYNC_EAGER=0 requires the celery package to be installed."
        ) from exc


def validate_runtime_security_configuration(
    *,
    runtime_env: str,
    debug: bool,
    secret_key: str,
    secret_key_explicit: bool,
    allowed_hosts: list[str],
    allowed_hosts_explicit: bool,
    secure_ssl_redirect: bool,
    session_cookie_secure: bool,
    csrf_cookie_secure: bool,
    secure_hsts_seconds: int,
    secure_hsts_include_subdomains: bool,
    secure_hsts_preload: bool,
    x_frame_options: str,
    secure_referrer_policy: str,
    csrf_trusted_origins: list[str],
    secure_proxy_ssl_header,
    use_x_forwarded_host: bool,
    testing: bool,
) -> None:
    if testing or runtime_env == "test":
        return

    profile = _get_runtime_security_profile(runtime_env)

    if profile["require_explicit_secret_key"]:
        if not secret_key_explicit:
            raise RuntimeError(
                f"DMIS_RUNTIME_ENV={runtime_env} requires DJANGO_SECRET_KEY to be set explicitly."
            )
        if _is_placeholder_secret_key(secret_key):
            raise RuntimeError(
                f"DMIS_RUNTIME_ENV={runtime_env} requires DJANGO_SECRET_KEY to be a real non-placeholder secret."
            )

    if profile["require_explicit_allowed_hosts"]:
        if not allowed_hosts_explicit:
            raise RuntimeError(
                f"DMIS_RUNTIME_ENV={runtime_env} requires DJANGO_ALLOWED_HOSTS to be set explicitly."
            )
        if not allowed_hosts:
            raise RuntimeError(
                f"DMIS_RUNTIME_ENV={runtime_env} requires DJANGO_ALLOWED_HOSTS to list one or more hosts."
            )

    if allowed_hosts:
        if any(host == "*" or host.startswith(".") for host in allowed_hosts):
            raise RuntimeError(
                f"DMIS_RUNTIME_ENV={runtime_env} does not allow wildcard DJANGO_ALLOWED_HOSTS entries."
            )
        if any(_is_url_shaped_allowed_host(host) for host in allowed_hosts):
            raise RuntimeError(
                f"DMIS_RUNTIME_ENV={runtime_env} requires DJANGO_ALLOWED_HOSTS entries without scheme or path."
            )
        if profile["require_non_loopback_allowed_hosts"] and not any(
            not _is_loopback_allowed_host(host) for host in allowed_hosts
        ):
            raise RuntimeError(
                f"DMIS_RUNTIME_ENV={runtime_env} requires DJANGO_ALLOWED_HOSTS to include at least one non-loopback host."
            )

    if secure_hsts_seconds < 0:
        raise RuntimeError("DJANGO_SECURE_HSTS_SECONDS cannot be negative.")

    if runtime_env != "local-harness" and any(
        not origin.strip().lower().startswith("https://")
        for origin in csrf_trusted_origins
    ):
        raise RuntimeError(
            f"DMIS_RUNTIME_ENV={runtime_env} requires DJANGO_CSRF_TRUSTED_ORIGINS to use https:// origins only."
        )

    if use_x_forwarded_host:
        raise RuntimeError(
            f"DMIS_RUNTIME_ENV={runtime_env} requires USE_X_FORWARDED_HOST=0."
        )

    required_proxy_ssl_header = profile["required_proxy_ssl_header"]
    normalized_proxy_ssl_header = _normalize_proxy_ssl_header(secure_proxy_ssl_header)
    if required_proxy_ssl_header is not None and normalized_proxy_ssl_header != required_proxy_ssl_header:
        raise RuntimeError(
            f"DMIS_RUNTIME_ENV={runtime_env} requires SECURE_PROXY_SSL_HEADER={required_proxy_ssl_header!r}."
        )

    required_secure_ssl_redirect = profile["required_secure_ssl_redirect"]
    if required_secure_ssl_redirect is not None and secure_ssl_redirect != required_secure_ssl_redirect:
        raise RuntimeError(
            f"DMIS_RUNTIME_ENV={runtime_env} requires DJANGO_SECURE_SSL_REDIRECT={int(required_secure_ssl_redirect)}."
        )

    required_session_cookie_secure = profile["required_session_cookie_secure"]
    if (
        required_session_cookie_secure is not None
        and session_cookie_secure != required_session_cookie_secure
    ):
        raise RuntimeError(
            f"DMIS_RUNTIME_ENV={runtime_env} requires DJANGO_SESSION_COOKIE_SECURE={int(required_session_cookie_secure)}."
        )

    required_csrf_cookie_secure = profile["required_csrf_cookie_secure"]
    if required_csrf_cookie_secure is not None and csrf_cookie_secure != required_csrf_cookie_secure:
        raise RuntimeError(
            f"DMIS_RUNTIME_ENV={runtime_env} requires DJANGO_CSRF_COOKIE_SECURE={int(required_csrf_cookie_secure)}."
        )

    if profile["allow_hsts_preload_opt_in"] and secure_hsts_preload:
        if secure_hsts_seconds < 31536000 or not secure_hsts_include_subdomains:
            raise RuntimeError(
                "DMIS_RUNTIME_ENV=production allows DJANGO_SECURE_HSTS_PRELOAD=1 only when "
                "DJANGO_SECURE_HSTS_SECONDS>=31536000 and DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=1."
            )

    required_secure_hsts_seconds = profile["required_secure_hsts_seconds"]
    if required_secure_hsts_seconds is not None and secure_hsts_seconds != required_secure_hsts_seconds:
        raise RuntimeError(
            f"DMIS_RUNTIME_ENV={runtime_env} requires DJANGO_SECURE_HSTS_SECONDS={required_secure_hsts_seconds}."
        )

    required_secure_hsts_include_subdomains = profile["required_secure_hsts_include_subdomains"]
    if (
        required_secure_hsts_include_subdomains is not None
        and secure_hsts_include_subdomains != required_secure_hsts_include_subdomains
    ):
        raise RuntimeError(
            "DMIS_RUNTIME_ENV="
            f"{runtime_env} requires DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS="
            f"{int(required_secure_hsts_include_subdomains)}."
        )

    required_secure_hsts_preload = profile["required_secure_hsts_preload"]
    if required_secure_hsts_preload is not None and secure_hsts_preload != required_secure_hsts_preload:
        raise RuntimeError(
            f"DMIS_RUNTIME_ENV={runtime_env} requires DJANGO_SECURE_HSTS_PRELOAD={int(required_secure_hsts_preload)}."
        )

    required_x_frame_options = profile["required_x_frame_options"]
    if required_x_frame_options is not None and x_frame_options != required_x_frame_options:
        raise RuntimeError(
            f"DMIS_RUNTIME_ENV={runtime_env} requires DJANGO_X_FRAME_OPTIONS={required_x_frame_options}."
        )

    required_secure_referrer_policy = profile["required_secure_referrer_policy"]
    if (
        required_secure_referrer_policy is not None
        and secure_referrer_policy != required_secure_referrer_policy
    ):
        raise RuntimeError(
            "DMIS_RUNTIME_ENV="
            f"{runtime_env} requires DJANGO_SECURE_REFERRER_POLICY={required_secure_referrer_policy}."
        )


_load_env_file(BASE_DIR / ".env")
if _should_load_local_env():
    _load_env_file(BASE_DIR / ".env.local", override=True)

_env_secret_key_raw = os.getenv("DJANGO_SECRET_KEY")
_env_secret_key = (_env_secret_key_raw or "").strip()
SECRET_KEY = _env_secret_key or _build_debug_secret_key()
DMIS_SECRET_KEY_EXPLICIT = _env_secret_key_raw is not None
DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"
DMIS_RUNTIME_ENV = _normalize_runtime_environment(testing=TESTING)
_runtime_security_profile = _get_runtime_security_profile(DMIS_RUNTIME_ENV)
ENABLE_TEST_ROLES = os.getenv("ENABLE_TEST_ROLES", "0") == "1"
_allowed_hosts_env = os.getenv("DJANGO_ALLOWED_HOSTS")
ALLOWED_HOSTS = [
    host.strip()
    for host in (_allowed_hosts_env or "localhost,127.0.0.1,[::1]").split(",")
    if host.strip()
]
DMIS_ALLOWED_HOSTS_EXPLICIT = _allowed_hosts_env is not None

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "api",
    "operations",
    "replenishment",
    "masterdata",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "api.apps.DmisRequestContextMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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
REST_FRAMEWORK = {
    "EXCEPTION_HANDLER": "api.apps.dmis_exception_handler",
    # DMIS uses `?format=` for domain export contracts (for example CSV previews/exports),
    # so DRF's query-param renderer override would incorrectly short-circuit those requests.
    "URL_FORMAT_OVERRIDE": None,
}
SECURE_CONTENT_TYPE_NOSNIFF = _get_bool_env("DJANGO_SECURE_CONTENT_TYPE_NOSNIFF", True)
SECURE_SSL_REDIRECT = _get_bool_env(
    "DJANGO_SECURE_SSL_REDIRECT",
    bool(_runtime_security_profile["secure_ssl_redirect_default"]),
)
SESSION_COOKIE_SECURE = _get_bool_env(
    "DJANGO_SESSION_COOKIE_SECURE",
    bool(_runtime_security_profile["session_cookie_secure_default"]),
)
CSRF_COOKIE_SECURE = _get_bool_env(
    "DJANGO_CSRF_COOKIE_SECURE",
    bool(_runtime_security_profile["csrf_cookie_secure_default"]),
)
SECURE_HSTS_SECONDS = _get_int_env(
    "DJANGO_SECURE_HSTS_SECONDS",
    int(_runtime_security_profile["secure_hsts_seconds_default"]),
) or 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = _get_bool_env(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS",
    bool(_runtime_security_profile["secure_hsts_include_subdomains_default"]),
)
SECURE_HSTS_PRELOAD = _get_bool_env(
    "DJANGO_SECURE_HSTS_PRELOAD",
    bool(_runtime_security_profile["secure_hsts_preload_default"]),
)
X_FRAME_OPTIONS = os.getenv(
    "DJANGO_X_FRAME_OPTIONS",
    str(_runtime_security_profile["x_frame_options_default"]),
).upper()
SECURE_REFERRER_POLICY = os.getenv(
    "DJANGO_SECURE_REFERRER_POLICY",
    str(_runtime_security_profile["secure_referrer_policy_default"]),
).strip().lower()
CSRF_TRUSTED_ORIGINS = _get_csv_env("DJANGO_CSRF_TRUSTED_ORIGINS", [])
SECURE_PROXY_SSL_HEADER = _runtime_security_profile["required_proxy_ssl_header"]
USE_X_FORWARDED_HOST = False

if TESTING and not _get_bool_env("DJANGO_TEST_ENABLE_SECURE_SETTINGS", False):
    # Keep local and CI tests aligned with Django's default test client behavior.
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_HSTS_SECONDS = 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False

# Cache posture: Redis-backed whenever REDIS_URL is configured; LocMemCache is
# only allowed for explicit local-harness degraded mode.
_redis_url = os.getenv("REDIS_URL", "").strip()
_running_tests = TESTING
_test_redis_cache_enabled = os.getenv("TEST_REDIS_CACHE_ENABLED", "0") == "1"
_use_redis_cache = bool(_redis_url) and (not _running_tests or _test_redis_cache_enabled)
if _use_redis_cache:
    CACHES = {
        "default": {
            "BACKEND": _REDIS_CACHE_BACKEND,
            "LOCATION": _redis_url,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
            },
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": _LOCMEM_CACHE_BACKEND,
        }
    }
DMIS_REDIS_URL = _redis_url
DMIS_REDIS_REQUIRED = redis_required_for_runtime_env(
    runtime_env=DMIS_RUNTIME_ENV,
    testing=TESTING,
)
DMIS_REDIS_CONFIGURED = bool(_redis_url)
DMIS_DEFAULT_CACHE_BACKEND = str(CACHES["default"]["BACKEND"])
DMIS_ASYNC_EAGER = _get_bool_env(
    "DMIS_ASYNC_EAGER",
    default_async_eager_for_runtime_env(runtime_env=DMIS_RUNTIME_ENV, testing=TESTING),
)
DMIS_WORKER_REQUIRED = worker_required_for_runtime_env(
    runtime_env=DMIS_RUNTIME_ENV,
    testing=TESTING,
)
_default_durable_export_retention_seconds = default_durable_export_retention_seconds_for_runtime_env(
    runtime_env=DMIS_RUNTIME_ENV,
    testing=TESTING,
)
# Treat only None as "unset" so an explicit 0 remains visible to downstream
# validation; api.tasks still enforces a 60-second minimum retention floor.
_configured_async_artifact_ttl_seconds = _get_int_env(
    "DMIS_ASYNC_ARTIFACT_TTL_SECONDS",
    None,
)
DMIS_ASYNC_ARTIFACT_TTL_SECONDS = (
    _default_durable_export_retention_seconds
    if _configured_async_artifact_ttl_seconds is None
    else _configured_async_artifact_ttl_seconds
)
_configured_durable_export_retention_seconds = _get_int_env(
    "DMIS_DURABLE_EXPORT_RETENTION_SECONDS",
    None,
)
DMIS_DURABLE_EXPORT_RETENTION_SECONDS = (
    DMIS_ASYNC_ARTIFACT_TTL_SECONDS
    if _configured_durable_export_retention_seconds is None
    else _configured_durable_export_retention_seconds
)
DMIS_ASYNC_INLINE_ARTIFACT_MAX_BYTES = (
    _get_int_env("DMIS_ASYNC_INLINE_ARTIFACT_MAX_BYTES", 524288) or 524288
)
DMIS_WORKER_HEARTBEAT_KEY = os.getenv(
    "DMIS_WORKER_HEARTBEAT_KEY",
    "dmis:worker:heartbeat",
).strip() or "dmis:worker:heartbeat"
DMIS_WORKER_HEARTBEAT_TTL_SECONDS = (
    _get_int_env("DMIS_WORKER_HEARTBEAT_TTL_SECONDS", 90) or 90
)
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", DMIS_REDIS_URL).strip()
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", DMIS_REDIS_URL).strip()
CELERY_TASK_ALWAYS_EAGER = DMIS_ASYNC_EAGER
CELERY_TASK_EAGER_PROPAGATES = bool(TESTING or DMIS_ASYNC_EAGER)
CELERY_TASK_IGNORE_RESULT = False
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = _get_int_env("CELERY_TASK_TIME_LIMIT", 600) or 600
CELERY_TASK_SOFT_TIME_LIMIT = _get_int_env("CELERY_TASK_SOFT_TIME_LIMIT", 540) or 540
CELERY_TASK_ACKS_LATE = not DMIS_ASYNC_EAGER
CELERY_TASK_REJECT_ON_WORKER_LOST = not DMIS_ASYNC_EAGER
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
DMIS_ASYNC_VISIBILITY_TIMEOUT_SECONDS = (
    _get_int_env(
        "DMIS_ASYNC_VISIBILITY_TIMEOUT_SECONDS",
        max(CELERY_TASK_TIME_LIMIT + 300, 900),
    )
    or max(CELERY_TASK_TIME_LIMIT + 300, 900)
)
if DMIS_ASYNC_VISIBILITY_TIMEOUT_SECONDS < CELERY_TASK_TIME_LIMIT:
    raise RuntimeError(
        "DMIS_ASYNC_VISIBILITY_TIMEOUT_SECONDS must be greater than or equal to CELERY_TASK_TIME_LIMIT."
    )
CELERY_BROKER_TRANSPORT_OPTIONS = {
    "visibility_timeout": DMIS_ASYNC_VISIBILITY_TIMEOUT_SECONDS,
}
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# AuthN/AuthZ configuration (env-driven; no claim-name assumptions).
AUTH_ENABLED = _get_bool_env(
    "AUTH_ENABLED",
    default_auth_enabled_for_runtime_env(runtime_env=DMIS_RUNTIME_ENV, testing=TESTING),
)
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
TEST_DEV_AUTH_ENABLED = os.getenv("TEST_DEV_AUTH_ENABLED", "0") == "1"
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
LOCAL_AUTH_HARNESS_ENABLED = os.getenv("LOCAL_AUTH_HARNESS_ENABLED", "0") == "1"
LOCAL_AUTH_HARNESS_USERNAMES = [
    value.strip()
    for value in os.getenv("LOCAL_AUTH_HARNESS_USERNAMES", "").split(",")
    if value.strip()
]
validate_runtime_auth_configuration(
    runtime_env=DMIS_RUNTIME_ENV,
    debug=DEBUG,
    auth_enabled=AUTH_ENABLED,
    dev_auth_enabled=DEV_AUTH_ENABLED,
    local_auth_harness_enabled=LOCAL_AUTH_HARNESS_ENABLED,
    testing=TESTING,
)
validate_runtime_security_configuration(
    runtime_env=DMIS_RUNTIME_ENV,
    debug=DEBUG,
    secret_key=SECRET_KEY,
    secret_key_explicit=DMIS_SECRET_KEY_EXPLICIT,
    allowed_hosts=ALLOWED_HOSTS,
    allowed_hosts_explicit=DMIS_ALLOWED_HOSTS_EXPLICIT,
    secure_ssl_redirect=SECURE_SSL_REDIRECT,
    session_cookie_secure=SESSION_COOKIE_SECURE,
    csrf_cookie_secure=CSRF_COOKIE_SECURE,
    secure_hsts_seconds=SECURE_HSTS_SECONDS,
    secure_hsts_include_subdomains=SECURE_HSTS_INCLUDE_SUBDOMAINS,
    secure_hsts_preload=SECURE_HSTS_PRELOAD,
    x_frame_options=X_FRAME_OPTIONS,
    secure_referrer_policy=SECURE_REFERRER_POLICY,
    csrf_trusted_origins=CSRF_TRUSTED_ORIGINS,
    secure_proxy_ssl_header=SECURE_PROXY_SSL_HEADER,
    use_x_forwarded_host=USE_X_FORWARDED_HOST,
    testing=TESTING,
)
validate_runtime_redis_configuration(
    runtime_env=DMIS_RUNTIME_ENV,
    redis_url=DMIS_REDIS_URL,
    cache_backend=DMIS_DEFAULT_CACHE_BACKEND,
    testing=TESTING,
)
validate_runtime_async_configuration(
    runtime_env=DMIS_RUNTIME_ENV,
    async_eager=DMIS_ASYNC_EAGER,
    worker_required=DMIS_WORKER_REQUIRED,
    redis_url=DMIS_REDIS_URL,
    broker_url=CELERY_BROKER_URL,
    result_backend=CELERY_RESULT_BACKEND,
    testing=TESTING,
)

# Tenant-scope rollout control.
# Default is disabled for backward compatibility until tenant mappings are complete.
# Tests are isolated from local .env tenant-scope settings unless explicitly opted in.
if TESTING:
    TENANT_SCOPE_ENFORCEMENT = os.getenv("TEST_TENANT_SCOPE_ENFORCEMENT", "0") == "1"
else:
    TENANT_SCOPE_ENFORCEMENT = os.getenv("TENANT_SCOPE_ENFORCEMENT", "0") == "1"
# Needs List Preview settings (TBD finalize from PRD/appendices).
def _get_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"Invalid {name} value: {raw!r}") from exc


# Only these national tenants may manage event phase demand/planning windows.
# Values are tenant_code entries and are compared case-insensitively.
NATIONAL_PHASE_WINDOW_ADMIN_CODES = _get_csv_env(
    "NATIONAL_PHASE_WINDOW_ADMIN_CODES",
    ["OFFICE-OF-DISASTER-P", "ODPEM-NEOC"],
)

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
ODPEM_TENANT_ID = _get_int_env("ODPEM_TENANT_ID", None)


# IFRC Item Code Assistant configuration.
IFRC_AGENT = {
    "IFRC_ENABLED": _get_bool_env("IFRC_ENABLED", True),
    "LLM_ENABLED": _get_bool_env("IFRC_LLM_ENABLED", False),
    # Path to the taxonomy reference MD file.
    # Override via IFRC_TAXONOMY_FILE env var to support different deployment layouts.
    "TAXONOMY_FILE": os.environ.get(
        "IFRC_TAXONOMY_FILE",
        str(BASE_DIR / "masterdata" / "data" / "ifrc_catalogue_taxonomy.md"),
    ),
    "OLLAMA_BASE_URL": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
    "OLLAMA_MODEL_ID": os.getenv("OLLAMA_MODEL_ID", "qwen3.5:0.8b"),
    "OLLAMA_TIMEOUT_SECONDS": _get_int_env("OLLAMA_TIMEOUT_SECONDS", 10) or 10,
    "AUTO_FILL_CONFIDENCE_THRESHOLD": _get_float_env("IFRC_AUTO_FILL_THRESHOLD", 0.85),
    "MIN_INPUT_LENGTH": _get_int_env("IFRC_MIN_INPUT_LENGTH", 3) or 3,
    "MAX_INPUT_LENGTH": _get_int_env("IFRC_MAX_INPUT_LENGTH", 120) or 120,
    "CB_FAILURE_THRESHOLD": _get_int_env("IFRC_CB_FAILURE_THRESHOLD", 5) or 5,
    "CB_RESET_TIMEOUT_SECONDS": _get_int_env("IFRC_CB_RESET_TIMEOUT", 120) or 120,
    "CB_REDIS_KEY": os.getenv("IFRC_CB_REDIS_KEY", "ifrc:circuit_breaker"),
    "RATE_LIMIT_PER_MINUTE": _get_int_env("IFRC_RATE_LIMIT_PER_MINUTE", 30) or 30,
}


if not TESTING:
    _dmis_log_level = os.getenv("DMIS_LOG_LEVEL", "INFO").strip().upper() or "INFO"
    _dmis_root_log_level = os.getenv("DMIS_ROOT_LOG_LEVEL", "WARNING").strip().upper() or "WARNING"
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_context": {
                "()": "api.apps.RequestContextLogFilter",
            }
        },
        "formatters": {
            "structured": {
                "format": (
                    "%(asctime)s level=%(levelname)s logger=%(name)s event=%(event)s "
                    "runtime_env=%(runtime_env)s request_id=%(request_id)s "
                    "method=%(request_method)s path=%(request_path)s status=%(status_code)s "
                    "dependency=%(dependency)s auth_mode=%(auth_mode)s "
                    "exception=%(exception_class)s message=%(message)s"
                )
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "filters": ["request_context"],
                "formatter": "structured",
            }
        },
        "loggers": {
            "dmis": {
                "handlers": ["console"],
                "level": _dmis_log_level,
                "propagate": False,
            },
            "django.request": {
                "handlers": ["console"],
                "level": "ERROR",
                "propagate": False,
            },
            "django.server": {
                "handlers": ["console"],
                "level": "WARNING",
                "propagate": False,
            },
            "django.security.DisallowedHost": {
                "handlers": ["console"],
                "level": "ERROR",
                "propagate": False,
            },
        },
        "root": {
            "handlers": ["console"],
            "level": _dmis_root_log_level,
        },
    }

