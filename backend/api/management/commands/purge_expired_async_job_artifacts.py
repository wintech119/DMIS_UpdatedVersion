from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from api.models import AsyncJob, AsyncJobArtifact


class Command(BaseCommand):
    help = (
        "Delete expired durable async job artifacts and clear expired legacy inline "
        "artifact payloads. Dry-run by default."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist deletions. Without this flag, the command only previews the cleanup.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        apply_changes = bool(options.get("apply"))
        now = timezone.now()

        expired_artifact_qs = AsyncJobArtifact.objects.filter(
            retention_expires_at__lte=now
        ).order_by("artifact_id")
        expired_inline_qs = (
            AsyncJob.objects.filter(expires_at__isnull=False, expires_at__lte=now)
            .filter(artifact_payload__isnull=False)
            .exclude(artifact_payload="")
            .order_by("job_id")
        )

        expired_artifact_count = expired_artifact_qs.count()
        expired_inline_count = expired_inline_qs.count()

        self.stdout.write("Async job artifact cleanup:")
        self.stdout.write(f"- expired durable artifacts: {expired_artifact_count}")
        self.stdout.write(f"- expired legacy inline payloads: {expired_inline_count}")

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING(
                    "Dry-run only. Re-run with --apply to delete expired artifacts."
                )
            )
            return

        with transaction.atomic():
            expired_artifact_qs.delete()
            expired_inline_qs.update(artifact_payload=None)

        self.stdout.write(
            self.style.SUCCESS(
                "Expired async job artifacts were purged and legacy inline payloads were cleared."
            )
        )
