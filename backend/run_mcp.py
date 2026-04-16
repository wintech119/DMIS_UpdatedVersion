"""Launcher for django-ai-boost MCP server. Sets up Django env and calls the package entry point."""
from importlib.metadata import PackageNotFoundError, version
import os
import sys

# Ensure backend is on path and cwd (django-ai-boost uses getcwd())
backend_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dmis_api.settings")
# Keep MCP aligned with normal app runtime (PostgreSQL-first).
os.environ.setdefault("DJANGO_USE_SQLITE", "0")
os.environ.setdefault("DMIS_RUNTIME_ENV", "local-harness")
os.environ.setdefault("DJANGO_DEBUG", "1")
os.environ.setdefault("AUTH_ENABLED", "0")
os.environ.setdefault("DEV_AUTH_ENABLED", "1")
os.environ.setdefault("LOCAL_AUTH_HARNESS_ENABLED", "1")
os.environ.setdefault("DMIS_LOAD_LOCAL_ENV", "1")

_MINIMUM_VERSIONS = {
    "fastmcp": (3, 2, 0),
    "authlib": (1, 6, 9),
    "cryptography": (46, 0, 6),
}


def _parse_version_tuple(raw_version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for segment in raw_version.split("."):
        if not segment.isdigit():
            break
        parts.append(int(segment))
    return tuple(parts)


def _assert_mcp_dependencies() -> None:
    for package_name, minimum_version in _MINIMUM_VERSIONS.items():
        try:
            installed_version = version(package_name)
        except PackageNotFoundError as exc:
            raise SystemExit(
                "Missing local MCP dependency set. From `backend/`, install "
                "`python -m pip install -r requirements-mcp.txt`."
            ) from exc

        if _parse_version_tuple(installed_version) < minimum_version:
            dotted_minimum = ".".join(str(part) for part in minimum_version)
            raise SystemExit(
                f"Unsafe MCP dependency detected: {package_name}=={installed_version}. "
                f"Upgrade the local MCP environment to at least {dotted_minimum} with "
                "`python -m pip install -r requirements-mcp.txt`."
            )


_assert_mcp_dependencies()

try:
    from django_ai_boost import main
except ModuleNotFoundError as exc:
    if exc.name != "django_ai_boost":
        raise
    raise SystemExit(
        "django-ai-boost is not installed in this backend environment. "
        "From `backend/`, install `python -m pip install -r requirements-mcp.txt` "
        "before running the MCP launcher."
    ) from exc

if __name__ == "__main__":
    main()
