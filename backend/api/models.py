from __future__ import annotations

from datetime import datetime

from django.db import models
from django.utils import timezone


class AsyncJob(models.Model):
    class JobType(models.TextChoices):
        NEEDS_LIST_DONATION_EXPORT = (
            "needs_list_donation_export",
            "Needs List Donation Export",
        )
        NEEDS_LIST_PROCUREMENT_EXPORT = (
            "needs_list_procurement_export",
            "Needs List Procurement Export",
        )

    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        RUNNING = "RUNNING", "Running"
        RETRYING = "RETRYING", "Retrying"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"

    class SourceType(models.TextChoices):
        NEEDS_LIST = "NEEDS_LIST", "Needs List"

    job_id = models.CharField(max_length=36, unique=True, db_index=True)
    job_type = models.CharField(max_length=80, choices=JobType.choices, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, db_index=True)
    queued_at = models.DateTimeField(default=timezone.now, db_index=True)
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    actor_user_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    actor_username = models.CharField(max_length=150, blank=True, null=True)
    tenant_id = models.IntegerField(blank=True, null=True, db_index=True)
    tenant_code = models.CharField(max_length=64, blank=True, null=True)
    request_id = models.CharField(max_length=128, blank=True, null=True, db_index=True)
    source_resource_type = models.CharField(
        max_length=40,
        choices=SourceType.choices,
        db_index=True,
    )
    source_resource_id = models.CharField(max_length=100, db_index=True)
    source_snapshot_version = models.CharField(max_length=255, blank=True, null=True)
    retry_count = models.PositiveIntegerField(default=0)
    max_retries = models.PositiveIntegerField(default=3)
    error_message = models.TextField(blank=True, null=True)
    celery_task_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    active_dedupe_key = models.CharField(max_length=255, blank=True, null=True, unique=True)
    artifact_filename = models.CharField(max_length=255, blank=True, null=True)
    artifact_content_type = models.CharField(max_length=100, blank=True, null=True)
    artifact_sha256 = models.CharField(max_length=64, blank=True, null=True)
    artifact_payload = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "async_job"
        indexes = [
            models.Index(fields=["job_type", "status"], name="async_job_type_status"),
            models.Index(
                fields=["source_resource_type", "source_resource_id"],
                name="async_job_source_lookup",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.job_type}:{self.job_id} [{self.status}]"

    @property
    def is_terminal(self) -> bool:
        return self.status in {self.Status.SUCCEEDED, self.Status.FAILED}

    def durable_artifact_or_none(self):
        try:
            return self.durable_artifact
        except self.__class__.durable_artifact.RelatedObjectDoesNotExist:
            return None

    @property
    def artifact_payload_text(self) -> str | None:
        durable_artifact = self.durable_artifact_or_none()
        if durable_artifact is not None:
            return durable_artifact.payload_text
        return self.artifact_payload

    @property
    def artifact_ready(self) -> bool:
        if self.status != self.Status.SUCCEEDED:
            return False
        if self.expires_at and timezone.now() >= self.expires_at:
            return False
        return bool(self.artifact_payload_text)

    def clear_artifact(self) -> None:
        durable_artifact = self.durable_artifact_or_none()
        if durable_artifact is not None:
            durable_artifact.delete()
        self.artifact_filename = None
        self.artifact_content_type = None
        self.artifact_sha256 = None
        self.artifact_payload = None
        self.expires_at = None

    def mark_running(self, *, celery_task_id: str | None = None, retry_count: int = 0) -> None:
        self.status = self.Status.RUNNING
        self.retry_count = max(retry_count, 0)
        self.started_at = timezone.now()
        self.finished_at = None
        self.error_message = None
        if celery_task_id:
            self.celery_task_id = celery_task_id

    def mark_retrying(self, *, error_message: str, retry_count: int) -> None:
        self.status = self.Status.RETRYING
        self.retry_count = max(retry_count, 0)
        self.error_message = error_message
        self.finished_at = None

    def mark_failed(self, *, error_message: str) -> None:
        self.status = self.Status.FAILED
        self.error_message = error_message
        self.finished_at = timezone.now()
        self.active_dedupe_key = None
        self.clear_artifact()

    def mark_succeeded(
        self,
        *,
        artifact_filename: str,
        artifact_content_type: str,
        artifact_sha256: str,
        artifact_expires_at: datetime,
    ) -> None:
        if timezone.is_naive(artifact_expires_at):
            raise ValueError("artifact_expires_at must be timezone-aware.")
        if artifact_expires_at <= timezone.now():
            raise ValueError("artifact_expires_at must be in the future.")
        self.status = self.Status.SUCCEEDED
        self.error_message = None
        self.finished_at = timezone.now()
        self.active_dedupe_key = None
        self.artifact_filename = artifact_filename
        self.artifact_content_type = artifact_content_type
        self.artifact_sha256 = artifact_sha256
        self.artifact_payload = None
        self.expires_at = artifact_expires_at


class AsyncJobArtifact(models.Model):
    class StorageBackend(models.TextChoices):
        DB_TEXT = "DB_TEXT", "Database Text"

    artifact_id = models.BigAutoField(primary_key=True)
    job = models.OneToOneField(
        AsyncJob,
        on_delete=models.CASCADE,
        related_name="durable_artifact",
    )
    storage_backend = models.CharField(
        max_length=20,
        choices=StorageBackend.choices,
        default=StorageBackend.DB_TEXT,
    )
    payload_text = models.TextField()
    size_bytes = models.PositiveIntegerField()
    retention_expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "async_job_artifact"

    def __str__(self) -> str:
        return f"{self.job.job_type}:{self.job.job_id} [{self.storage_backend}]"
