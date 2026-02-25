"""Launcher for django-ai-boost MCP server. Sets up Django env and calls the package entry point."""
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
os.environ.setdefault("DJANGO_DEBUG", "1")

from django_ai_boost import main

if __name__ == "__main__":
    main()
