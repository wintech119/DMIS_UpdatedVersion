from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
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
        parser.add_argument(
            "--batch-size",
            type=int,
            default=None,
            help=(
                "When provided with --apply, delete expired rows in bounded batches "
                "instead of one large transaction."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        apply_changes = bool(options.get("apply"))
        batch_size = options.get("batch_size")
        now = timezone.now()

        if batch_size is not None and batch_size <= 0:
            raise CommandError("--batch-size must be greater than zero.")

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

        if batch_size is None:
            with transaction.atomic():
                expired_artifact_qs.delete()
                expired_inline_qs.update(artifact_payload=None)
        else:
            while True:
                artifact_batch = list(
                    expired_artifact_qs.values_list("artifact_id", flat=True)[:batch_size]
                )
                if not artifact_batch:
                    break
                with transaction.atomic():
                    AsyncJobArtifact.objects.filter(artifact_id__in=artifact_batch).delete()

            while True:
                inline_batch = list(
                    expired_inline_qs.values_list("job_id", flat=True)[:batch_size]
                )
                if not inline_batch:
                    break
                with transaction.atomic():
                    AsyncJob.objects.filter(job_id__in=inline_batch).update(
                        artifact_payload=None
                    )

        self.stdout.write(
            self.style.SUCCESS(
                "Expired async job artifacts were purged and legacy inline payloads were cleared."
            )
        )
