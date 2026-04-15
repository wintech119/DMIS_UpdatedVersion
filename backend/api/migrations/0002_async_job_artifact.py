from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models, transaction
from django.utils import timezone


BATCH_SIZE = 500


def backfill_durable_async_job_artifacts(apps, schema_editor) -> None:
    AsyncJob = apps.get_model("api", "AsyncJob")
    AsyncJobArtifact = apps.get_model("api", "AsyncJobArtifact")

    now = timezone.now()
    jobs = (
        AsyncJob.objects.filter(status="SUCCEEDED")
        .filter(artifact_payload__isnull=False)
        .exclude(artifact_payload="")
        .filter(expires_at__gt=now)
    )

    artifacts = []
    for job in jobs.iterator(chunk_size=BATCH_SIZE):
        payload_text = str(job.artifact_payload or "")
        if not payload_text:
            continue
        artifacts.append(
            AsyncJobArtifact(
                job_id=job.id,
                storage_backend="DB_TEXT",
                payload_text=payload_text,
                size_bytes=len(payload_text.encode("utf-8")),
                retention_expires_at=job.expires_at,
            )
        )
        if len(artifacts) >= BATCH_SIZE:
            with transaction.atomic():
                AsyncJobArtifact.objects.bulk_create(artifacts, ignore_conflicts=True)
            artifacts.clear()

    if artifacts:
        with transaction.atomic():
            AsyncJobArtifact.objects.bulk_create(artifacts, ignore_conflicts=True)


def noop_reverse(apps, schema_editor) -> None:
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0001_async_job"),
    ]

    operations = [
        migrations.CreateModel(
            name="AsyncJobArtifact",
            fields=[
                ("artifact_id", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "storage_backend",
                    models.CharField(
                        choices=[("DB_TEXT", "Database Text")],
                        default="DB_TEXT",
                        max_length=20,
                    ),
                ),
                ("payload_text", models.TextField()),
                ("size_bytes", models.PositiveIntegerField()),
                ("retention_expires_at", models.DateTimeField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "job",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="durable_artifact",
                        to="api.asyncjob",
                    ),
                ),
            ],
            options={
                "db_table": "async_job_artifact",
            },
        ),
        migrations.RunPython(
            backfill_durable_async_job_artifacts,
            noop_reverse,
            atomic=False,
        ),
    ]
