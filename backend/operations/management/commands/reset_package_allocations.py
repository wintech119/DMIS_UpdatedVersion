from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from operations import contract_services
from operations.exceptions import OperationValidationError
from operations.models import OperationsPackage, OperationsReliefRequest
from replenishment.legacy_models import ReliefPkgItem

import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Clear package allocation rows and release any active package lock so fulfillment "
        "UAT can restart from the same package shell. Dry-run by default."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--package-id",
            type=int,
            default=None,
            help="Target package ID, for example 95027.",
        )
        parser.add_argument(
            "--request-no",
            type=str,
            default=None,
            help="Target request number, for example RQ95009.",
        )
        parser.add_argument(
            "--actor",
            type=str,
            default="SYSTEM",
            help="Actor identifier recorded in the cleanup workflow. Defaults to SYSTEM.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist the cleanup. Without this flag, the command only previews current state.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        package_id = options.get("package_id")
        request_no = str(options.get("request_no") or "").strip() or None
        actor_id = str(options.get("actor") or "SYSTEM").strip() or "SYSTEM"
        apply_changes = bool(options.get("apply"))

        if (package_id is None) == (request_no is None):
            raise CommandError("Provide exactly one of --package-id or --request-no.")

        request_record, package_record = self._resolve_target(
            package_id=package_id,
            request_no=request_no,
        )

        self.stdout.write("Package allocation reset:")
        self.stdout.write(f"- actor: {actor_id}")
        if request_record is not None:
            self.stdout.write(f"- request_no: {request_record.request_no}")
            self.stdout.write(f"- reliefrqst_id: {int(request_record.relief_request_id)}")

        if package_record is None:
            self.stdout.write("- package: none")
            self.stdout.write(self.style.SUCCESS("No current package exists for the supplied target."))
            return

        lock = getattr(package_record, "lock_record", None)
        self.stdout.write(f"- package_id: {int(package_record.package_id)}")
        self.stdout.write(f"- package_no: {package_record.package_no}")
        self.stdout.write(f"- package_status: {package_record.status_code}")
        self.stdout.write(
            f"- operations_allocation_lines: {package_record.allocation_lines.count()}"
        )
        self.stdout.write(
            f"- legacy_allocation_lines: {self._legacy_allocation_line_count(int(package_record.package_id))}"
        )
        self.stdout.write(f"- active_lock: {'yes' if lock is not None and lock.lock_status == 'ACTIVE' else 'no'}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry-run only. Re-run with --apply to persist changes."))
            return

        try:
            result = contract_services.reset_package_allocations(
                int(package_record.package_id),
                actor_id=actor_id,
            )
        except OperationValidationError as exc:
            messages = [
                str(message).strip()
                for value in exc.errors.values()
                for message in (value if isinstance(value, list) else [value])
                if str(message).strip()
            ]
            raise CommandError(", ".join(messages) or "Package allocation reset failed.") from exc
        self.stdout.write(self.style.SUCCESS("Package allocations reset."))
        self.stdout.write(f"- status: {result['status']}")
        self.stdout.write(
            f"- operations_allocation_lines_deleted: {result['operations_allocation_lines_deleted']}"
        )
        self.stdout.write(
            f"- legacy_allocation_lines_deleted: {result['legacy_allocation_lines_deleted']}"
        )
        released_summary = result.get("released_stock_summary") or {}
        self.stdout.write(
            f"- released_stock_lines: {released_summary.get('line_count', 0)}"
        )
        self.stdout.write(
            f"- released_stock_total_qty: {released_summary.get('total_qty', '0.0000')}"
        )

    def _resolve_target(
        self,
        *,
        package_id: int | None,
        request_no: str | None,
    ) -> tuple[OperationsReliefRequest | None, OperationsPackage | None]:
        if package_id is not None:
            package_record = (
                OperationsPackage.objects.select_related("relief_request", "lock_record")
                .prefetch_related("allocation_lines")
                .filter(package_id=int(package_id))
                .first()
            )
            if package_record is None:
                raise CommandError(f"No package found for package_id={package_id}.")
            return package_record.relief_request, package_record

        request_record = OperationsReliefRequest.objects.filter(request_no=request_no).first()
        if request_record is None:
            raise CommandError(f"No relief request found for request_no={request_no}.")
        package_record = (
            OperationsPackage.objects.select_related("relief_request", "lock_record")
            .prefetch_related("allocation_lines")
            .filter(relief_request_id=int(request_record.relief_request_id))
            .order_by("-package_id")
            .first()
        )
        return request_record, package_record

    def _legacy_allocation_line_count(self, reliefpkg_id: int) -> int:
        try:
            return ReliefPkgItem.objects.filter(reliefpkg_id=reliefpkg_id).count()
        except DatabaseError:
            logger.exception("Error counting ReliefPkgItem for reliefpkg_id=%s", reliefpkg_id)
            raise
