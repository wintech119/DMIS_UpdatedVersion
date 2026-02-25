#!/usr/bin/env python
import os
import sys
from pathlib import Path

# Some embedded Python distributions run in isolated/safe-path mode and
# omit the script directory from sys.path. Ensure local project imports
# (e.g. dmis_api.settings) still resolve.
BACKEND_DIR = str(Path(__file__).resolve().parent)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dmis_api.settings")
    if os.environ.get("DJANGO_DEVELOPMENT", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        os.environ.setdefault("NEEDS_WORKFLOW_DEV_STORE", "1")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are the backend requirements installed?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
