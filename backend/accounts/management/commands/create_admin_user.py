from __future__ import annotations

import getpass
from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError


class Command(BaseCommand):
    help = (
        "Create a DMIS system administrator in the existing user table with a "
        "required primary tenant membership."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("username", type=str)
        parser.add_argument("--email", required=True, type=str)
        parser.add_argument("--tenant-id", type=int, default=None)
        parser.add_argument("--tenant-code", type=str, default=None)
        parser.add_argument("--password", type=str, default=None)
        parser.add_argument("--actor", type=str, default="system")

    def handle(self, *args: Any, **options: Any) -> None:
        username = str(options["username"] or "").strip()
        email = str(options["email"] or "").strip()
        tenant_id = options.get("tenant_id")
        tenant_code = str(options.get("tenant_code") or "").strip()
        password = options.get("password")

        if not username:
            raise CommandError("username is required.")
        if not email:
            raise CommandError("--email is required.")
        if tenant_id in (None, "") and not tenant_code:
            raise CommandError("--tenant-id or --tenant-code is required.")
        if password is None:
            password = getpass.getpass("Password: ")
            confirm_password = getpass.getpass("Password (again): ")
            if password != confirm_password:
                raise CommandError("Passwords do not match.")
        if not password:
            raise CommandError("Password cannot be blank.")

        extra_fields: dict[str, Any] = {
            "actor_id": str(options.get("actor") or "system").strip() or "system",
        }
        if tenant_id not in (None, ""):
            extra_fields["tenant_id"] = tenant_id
        else:
            extra_fields["tenant_code"] = tenant_code

        UserModel = get_user_model()
        try:
            user = UserModel.objects.create_superuser(
                username,
                email,
                password,
                **extra_fields,
            )
        except (ImproperlyConfigured, IntegrityError, ValueError) as exc:
            raise CommandError(f"Unable to create administrator user: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Created DMIS administrator user_id={user.user_id} username={user.username}."
            )
        )
