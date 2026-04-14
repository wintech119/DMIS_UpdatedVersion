from __future__ import annotations

import hashlib
import logging
from typing import Callable

from celery import shared_task
from celery.signals import heartbeat_sent, worker_ready
from django.conf import settings
from django.core.cache import caches
from django.db import DatabaseError, transaction
from django.utils import timezone

from api.apps import build_log_extra, clear_request_log_context, set_request_log_context
from api.models import AsyncJob
from replenishment import workflow_store_db
from replenishment.services import needs_list as needs_list_service

job_logger = logging.getLogger("dmis.jobs")


class AsyncJobPermanentError(RuntimeError):
    """Raised when an async job should fail without retry."""


def _touch_worker_heartbeat() -> None:
    if getattr(settings, "DMIS_ASYNC_EAGER", False):
        return
    if not getattr(settings, "DMIS_REDIS_CONFIGURED", False):
        return
    cache_backend = str(getattr(settings, "DMIS_DEFAULT_CACHE_BACKEND", "")).strip()
    if cache_backend != "django_redis.cache.RedisCache":
        return
    caches["default"].set(
        settings.DMIS_WORKER_HEARTBEAT_KEY,
        timezone.now().isoformat(),
        timeout=int(getattr(settings, "DMIS_WORKER_HEARTBEAT_TTL_SECONDS", 90)),
    )


@worker_ready.connect
def _handle_worker_ready(**_kwargs) -> None:
    _touch_worker_heartbeat()


@heartbeat_sent.connect
def _handle_worker_heartbeat(**_kwargs) -> None:
    _touch_worker_heartbeat()


def _job_log_extra(job: AsyncJob, *, event: str, **extra) -> dict[str, object]:
    return build_log_extra(
        event=event,
        job_id=job.job_id,
        job_type=job.job_type,
        request_id=job.request_id,
        tenant_id=job.tenant_id,
        tenant_code=job.tenant_code,
        actor_user_id=job.actor_user_id,
        actor_username=job.actor_username,
        source_resource_type=job.source_resource_type,
        source_resource_id=job.source_resource_id,
        retry_count=job.retry_count,
        **extra,
    )


def _load_job_for_update(job_id: str) -> AsyncJob:
    return AsyncJob.objects.select_for_update().get(job_id=job_id)


def _with_job_context(job: AsyncJob, callback: Callable[[], None]) -> None:
    set_request_log_context(
        request_id=job.request_id or job.job_id,
        request_method="TASK",
        request_path=f"/jobs/{job.job_id}",
    )
    try:
        callback()
    finally:
        clear_request_log_context()


def _build_needs_list_export_artifact(job: AsyncJob) -> tuple[str, str, str, str]:
    workflow_store_db.store_enabled_or_raise()
    record = workflow_store_db.get_record(job.source_resource_id)
    if not record:
        raise AsyncJobPermanentError(
            f"Source needs list {job.source_resource_id} was not found."
        )

    snapshot = workflow_store_db.apply_overrides(record)
    if job.job_type == AsyncJob.JobType.NEEDS_LIST_DONATION_EXPORT:
        export_kind = "donation"
    elif job.job_type == AsyncJob.JobType.NEEDS_LIST_PROCUREMENT_EXPORT:
        export_kind = "procurement"
    else:
        raise AsyncJobPermanentError(f"Unsupported async job type: {job.job_type}.")

    filename, csv_payload = needs_list_service.build_needs_list_export_csv(
        snapshot=snapshot,
        export_kind=export_kind,
        reference=record.get("needs_list_no"),
        fallback_reference=job.source_resource_id,
    )
    payload_bytes = csv_payload.encode("utf-8")
    max_bytes = int(getattr(settings, "DMIS_ASYNC_INLINE_ARTIFACT_MAX_BYTES", 524288))
    if len(payload_bytes) > max_bytes:
        raise AsyncJobPermanentError(
            f"Export artifact exceeded inline storage limit ({len(payload_bytes)} bytes)."
        )
    checksum = hashlib.sha256(payload_bytes).hexdigest()
    return filename, "text/csv", checksum, csv_payload


def _mark_job_running(
    job_id: str,
    *,
    celery_task_id: str | None,
    retry_count: int,
) -> tuple[AsyncJob, dict[str, object]]:
    with transaction.atomic():
        job = _load_job_for_update(job_id)
        if job.is_terminal:
            return job, {"recovered_from_worker_loss": False}

        previous_status = job.status
        previous_celery_task_id = job.celery_task_id
        previous_started_at = job.started_at.isoformat() if job.started_at else None
        recovered_from_worker_loss = (
            previous_status == AsyncJob.Status.RUNNING
            and bool(previous_celery_task_id)
            and bool(celery_task_id)
            and previous_celery_task_id != celery_task_id
        )
        job.mark_running(celery_task_id=celery_task_id, retry_count=retry_count)
        job.save(
            update_fields=[
                "status",
                "retry_count",
                "started_at",
                "finished_at",
                "error_message",
                "celery_task_id",
            ]
        )
        return job, {
            "recovered_from_worker_loss": recovered_from_worker_loss,
            "previous_celery_task_id": previous_celery_task_id,
            "previous_started_at": previous_started_at,
        }


def _mark_job_retrying(job_id: str, *, error_message: str, retry_count: int) -> AsyncJob:
    with transaction.atomic():
        job = _load_job_for_update(job_id)
        job.mark_retrying(error_message=error_message, retry_count=retry_count)
        job.save(
            update_fields=[
                "status",
                "retry_count",
                "error_message",
                "finished_at",
            ]
        )
        return job


def _mark_job_failed(job_id: str, *, error_message: str) -> AsyncJob:
    with transaction.atomic():
        job = _load_job_for_update(job_id)
        job.mark_failed(error_message=error_message)
        job.save(
            update_fields=[
                "status",
                "error_message",
                "finished_at",
                "active_dedupe_key",
                "artifact_filename",
                "artifact_content_type",
                "artifact_sha256",
                "artifact_payload",
                "expires_at",
            ]
        )
        return job


def _mark_job_succeeded(
    job_id: str,
    *,
    artifact_filename: str,
    artifact_content_type: str,
    artifact_sha256: str,
    artifact_payload: str,
) -> AsyncJob:
    with transaction.atomic():
        job = _load_job_for_update(job_id)
        job.mark_succeeded(
            artifact_filename=artifact_filename,
            artifact_content_type=artifact_content_type,
            artifact_sha256=artifact_sha256,
            artifact_payload=artifact_payload,
            artifact_ttl_seconds=int(
                getattr(settings, "DMIS_ASYNC_ARTIFACT_TTL_SECONDS", 86400)
            ),
        )
        job.save(
            update_fields=[
                "status",
                "error_message",
                "finished_at",
                "active_dedupe_key",
                "artifact_filename",
                "artifact_content_type",
                "artifact_sha256",
                "artifact_payload",
                "expires_at",
            ]
        )
        return job


def _retry_delay_seconds(current_retry_count: int) -> int:
    return min(30 * (2 ** max(current_retry_count - 1, 0)), 300)


@shared_task(bind=True, name="api.run_async_job")
def run_async_job(self, job_id: str) -> str:
    _touch_worker_heartbeat()
    job, recovery_context = _mark_job_running(
        job_id,
        celery_task_id=getattr(self.request, "id", None),
        retry_count=int(getattr(self.request, "retries", 0)),
    )
    if job.is_terminal:
        return job.status

    if recovery_context.get("recovered_from_worker_loss"):
        previous_celery_task_id = recovery_context.get("previous_celery_task_id")
        previous_started_at = recovery_context.get("previous_started_at")

        def _log_recovered() -> None:
            job_logger.warning(
                "job.recovered",
                extra=_job_log_extra(
                    job,
                    event="job.recovered",
                    previous_celery_task_id=previous_celery_task_id,
                    previous_started_at=previous_started_at,
                ),
            )

        _with_job_context(job, _log_recovered)

    def _run_logged() -> None:
        job_logger.info("job.started", extra=_job_log_extra(job, event="job.started"))

    _with_job_context(job, _run_logged)

    try:
        artifact_filename, artifact_content_type, artifact_sha256, artifact_payload = (
            _build_needs_list_export_artifact(job)
        )
        job = _mark_job_succeeded(
            job_id,
            artifact_filename=artifact_filename,
            artifact_content_type=artifact_content_type,
            artifact_sha256=artifact_sha256,
            artifact_payload=artifact_payload,
        )

        def _log_success() -> None:
            job_logger.info(
                "job.succeeded",
                extra=_job_log_extra(
                    job,
                    event="job.succeeded",
                    artifact_filename=artifact_filename,
                ),
            )

        _with_job_context(job, _log_success)
        return job.status
    except AsyncJobPermanentError as exc:
        error_message = str(exc)
        job = _mark_job_failed(job_id, error_message=error_message)

        def _log_failed() -> None:
            job_logger.error(
                "job.failed",
                extra=_job_log_extra(job, event="job.failed", error_message=error_message),
            )

        _with_job_context(job, _log_failed)
        return job.status
    except Exception as exc:  # noqa: BLE001 - job reliability requires bounded retry on unexpected failures.
        current_retries = int(getattr(self.request, "retries", 0))
        next_retry_count = current_retries + 1
        error_message = f"{exc.__class__.__name__}: {exc}"
        if next_retry_count <= max(job.max_retries, 0):
            job = _mark_job_retrying(
                job_id,
                error_message=error_message,
                retry_count=next_retry_count,
            )

            def _log_retry() -> None:
                job_logger.warning(
                    "job.retrying",
                    extra=_job_log_extra(
                        job,
                        event="job.retrying",
                        error_message=error_message,
                        retry_in_seconds=_retry_delay_seconds(next_retry_count),
                    ),
                )

            _with_job_context(job, _log_retry)
            raise self.retry(
                exc=exc,
                countdown=_retry_delay_seconds(next_retry_count),
                max_retries=job.max_retries,
            )

        job = _mark_job_failed(job_id, error_message=error_message)

        def _log_failed() -> None:
            job_logger.error(
                "job.failed",
                extra=_job_log_extra(job, event="job.failed", error_message=error_message),
            )

        _with_job_context(job, _log_failed)
        return job.status
