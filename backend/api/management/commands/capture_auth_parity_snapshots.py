from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test import Client, override_settings


SNAPSHOT_USERS: dict[str, str] = {
    "SYSTEM_ADMINISTRATOR": "local_system_admin_tst",
    "EXECUTIVE": "local_odpem_deputy_director_tst",
    "LOGISTICS_OFFICER": "local_odpem_logistics_officer_tst",
    "AGENCY_DISTRIBUTOR": "relief_jrc_requester_tst",
}


class Command(BaseCommand):
    help = (
        "Capture current LegacyCompatAuthentication /auth/whoami/ JSON snapshots "
        "for Phase 2 auth parity assertions."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--output-dir",
            type=str,
            default=None,
            help="Directory for whoami_<username>.json files.",
        )
        parser.add_argument(
            "--username",
            action="append",
            default=None,
            help="Specific local harness username to capture. May be repeated.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        requested_usernames = options.get("username") or []
        usernames = self._dedupe(requested_usernames or SNAPSHOT_USERS.values())
        if not usernames:
            raise CommandError("At least one username is required.")

        output_dir = self._output_dir(options.get("output_dir"))
        output_dir.mkdir(parents=True, exist_ok=True)
        output_paths = self._output_paths(output_dir, usernames)

        previous_runtime_env = os.environ.get("DMIS_RUNTIME_ENV")
        os.environ["DMIS_RUNTIME_ENV"] = "local-harness"
        try:
            client = Client()
            written_files: list[Path] = []
            with override_settings(
                AUTH_ENABLED=False,
                DEV_AUTH_ENABLED=True,
                TEST_DEV_AUTH_ENABLED=True,
                DMIS_RUNTIME_ENV="local-harness",
                LOCAL_AUTH_HARNESS_ENABLED=True,
                LOCAL_AUTH_HARNESS_USERNAMES=usernames,
                DEBUG=True,
                ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"],
            ):
                for username in usernames:
                    response = client.get(
                        "/api/v1/auth/whoami/",
                        HTTP_X_DMIS_LOCAL_USER=username,
                    )
                    if response.status_code != 200:
                        body = response.content.decode("utf-8", errors="replace")
                        raise CommandError(
                            f"whoami capture failed for {username}: "
                            f"HTTP {response.status_code}: {body}"
                        )
                    payload = response.json()
                    output_path = output_paths[username]
                    output_path.write_text(
                        json.dumps(payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    written_files.append(output_path)
        finally:
            if previous_runtime_env is None:
                os.environ.pop("DMIS_RUNTIME_ENV", None)
            else:
                os.environ["DMIS_RUNTIME_ENV"] = previous_runtime_env

        self.stdout.write(self.style.SUCCESS(f"Wrote {len(written_files)} auth parity snapshots."))
        for path in written_files:
            self.stdout.write(f"- {path}")

    def _output_dir(self, raw_output_dir: Any) -> Path:
        if raw_output_dir:
            return Path(str(raw_output_dir)).expanduser().resolve()
        return Path(settings.BASE_DIR) / "api" / "tests_auth_parity_fixtures"

    def _dedupe(self, values: Any) -> list[str]:
        usernames: list[str] = []
        seen: set[str] = set()
        for value in values:
            username = str(value or "").strip()
            key = username.lower()
            if not username or key in seen:
                continue
            seen.add(key)
            usernames.append(username)
        return usernames

    def _safe_username(self, username: str) -> str:
        safe_username = re.sub(r"[^A-Za-z0-9._-]", "_", username).lstrip(".")
        return safe_username or "unknown"

    def _output_paths(self, output_dir: Path, usernames: list[str]) -> dict[str, Path]:
        output_paths: dict[str, Path] = {}
        usernames_by_filename: dict[str, str] = {}
        for username in usernames:
            filename = f"whoami_{self._safe_username(username)}.json"
            filename_key = filename.casefold()
            previous_username = usernames_by_filename.get(filename_key)
            if previous_username is not None:
                raise CommandError(
                    f"Usernames {previous_username!r} and {username!r} sanitize "
                    f"to the same snapshot filename {filename!r}."
                )
            usernames_by_filename[filename_key] = username
            output_paths[username] = output_dir / filename
        return output_paths
