from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from operations import contract_services
from operations.constants import ROLE_SYSTEM_ADMINISTRATOR
from operations.models import OperationsPackage, OperationsPackageLock, OperationsReliefRequest


class Command(BaseCommand):
    help = (
        "Release an active fulfillment package lock for admin support or test cleanup. "
        "Dry-run by default."
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
            help="Actor identifier recorded in the release workflow. Defaults to SYSTEM.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist the lock release. Without this flag, the command only previews the current lock state.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        package_id = options.get("package_id")
        request_no = str(options.get("request_no") or "").strip() or None
        actor_id = str(options.get("actor") or "SYSTEM").strip() or "SYSTEM"
        apply_changes = bool(options.get("apply"))

        if bool(package_id) == bool(request_no):
            raise CommandError("Provide exactly one of --package-id or --request-no.")

        request_record, package_record = self._resolve_target(
            package_id=package_id,
            request_no=request_no,
        )

        self.stdout.write("Package lock release:")
        if request_record is not None:
            self.stdout.write(f"- request_no: {request_record.request_no}")
            self.stdout.write(f"- reliefrqst_id: {int(request_record.relief_request_id)}")
        self.stdout.write(f"- actor: {actor_id}")

        if package_record is None:
            self.stdout.write("- package: none")
            self.stdout.write(self.style.SUCCESS("No current package exists for the supplied target."))
            return

        lock = OperationsPackageLock.objects.filter(package_id=int(package_record.package_id)).first()
        self.stdout.write(f"- package_id: {int(package_record.package_id)}")
        self.stdout.write(f"- package_no: {package_record.package_no}")
        self.stdout.write(f"- lock_found: {'yes' if lock is not None else 'no'}")
        self.stdout.write(
            f"- active_lock: {'yes' if contract_services._is_package_lock_active(lock) else 'no'}"
        )
        self.stdout.write(f"- lock_status: {lock.lock_status if lock is not None else 'NONE'}")
        self.stdout.write(
            f"- lock_owner_user_id: {lock.lock_owner_user_id if lock is not None else 'NONE'}"
        )
        self.stdout.write(
            f"- lock_owner_role_code: {lock.lock_owner_role_code if lock is not None else 'NONE'}"
        )
        self.stdout.write(
            f"- lock_expires_at: {contract_services.legacy_service._as_iso(lock.lock_expires_at) if lock is not None else None}"
        )

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry-run only. Re-run with --apply to persist changes."))
            return

        result = contract_services._release_package_lock_for_record(
            package_record,
            request_record=request_record,
            actor_id=actor_id,
            actor_roles=[ROLE_SYSTEM_ADMINISTRATOR],
            force=True,
        )
        if result["released"]:
            self.stdout.write(self.style.SUCCESS("Package lock released."))
        else:
            self.stdout.write(self.style.SUCCESS(result["message"]))
        self.stdout.write(f"- released: {result['released']}")
        self.stdout.write(f"- lock_status: {result['lock_status']}")
        self.stdout.write(f"- released_at: {result['released_at']}")
        self.stdout.write(f"- previous_lock_owner_user_id: {result['previous_lock_owner_user_id']}")
        self.stdout.write(f"- previous_lock_owner_role_code: {result['previous_lock_owner_role_code']}")

    def _resolve_target(
        self,
        *,
        package_id: int | None,
        request_no: str | None,
    ) -> tuple[OperationsReliefRequest | None, OperationsPackage | None]:
        if package_id is not None:
            package_record = (
                OperationsPackage.objects.select_related("relief_request")
                .filter(package_id=int(package_id))
                .first()
            )
            if package_record is None:
                raise CommandError(f"No package found for package_id={package_id}.")
            return package_record.relief_request, package_record

        request_record = OperationsReliefRequest.objects.filter(request_no=request_no).first()
        if request_record is None:
            raise CommandError(f"No relief request found for request_no={request_no}.")
        package_records = list(
            OperationsPackage.objects.filter(relief_request_id=int(request_record.relief_request_id))
            .order_by("package_id")
        )
        if not package_records:
            raise CommandError(f"No package found for request_no={request_no}.")
        if len(package_records) > 1:
            raise CommandError(
                f"Multiple packages found for request_no={request_no}. Specify --package-id."
            )
        return request_record, package_records[0]
