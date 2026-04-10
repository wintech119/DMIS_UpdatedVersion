from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from replenishment.legacy_models import Inventory, ItemBatch
from replenishment.services.allocation_dispatch import _quantize_qty


@dataclass(frozen=True)
class AggregateSnapshot:
    inventory_id: int
    item_id: int
    batch_id: int | None
    active_status: str
    inventory_row_exists: bool
    inventory_status_code: str | None
    inventory_uom_code: str | None
    current_usable_qty: Decimal
    current_reserved_qty: Decimal
    current_defective_qty: Decimal
    current_expired_qty: Decimal
    batch_row_count: int
    batch_uom_code: str | None
    batch_usable_qty: Decimal
    batch_reserved_qty: Decimal
    batch_defective_qty: Decimal
    batch_expired_qty: Decimal
    repair_action: str

    @property
    def current_available_qty(self) -> Decimal:
        return _quantize_qty(self.current_usable_qty - self.current_reserved_qty)

    @property
    def batch_available_qty(self) -> Decimal:
        return _quantize_qty(self.batch_usable_qty - self.batch_reserved_qty)

    @property
    def repair_required(self) -> bool:
        return self.repair_action in {"create", "update"}


class Command(BaseCommand):
    help = (
        "Reconcile a legacy inventory aggregate row from active itembatch totals for a targeted "
        "(inventory_id, item_id) pair. Dry-run by default."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--inventory-id",
            type=int,
            required=True,
            help="Target inventory_id / warehouse_id, for example 3.",
        )
        parser.add_argument(
            "--item-id",
            type=int,
            required=True,
            help="Target item_id, for example 195.",
        )
        parser.add_argument(
            "--batch-id",
            type=int,
            default=None,
            help="Optional batch_id verification aid, for example 95045.",
        )
        parser.add_argument(
            "--actor",
            type=str,
            default="SYSTEM",
            help="Actor recorded on any repaired inventory row. Defaults to SYSTEM.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist changes. Without this flag, the command only previews the repair.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        inventory_id = int(options["inventory_id"])
        item_id = int(options["item_id"])
        batch_id = int(options["batch_id"]) if options.get("batch_id") else None
        actor_id = str(options.get("actor") or "SYSTEM").strip() or "SYSTEM"
        apply_changes = bool(options.get("apply"))

        snapshot = self._load_snapshot(
            inventory_id=inventory_id,
            item_id=item_id,
            batch_id=batch_id,
            lock_rows=False,
        )
        self._write_snapshot(snapshot)

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry-run only. Re-run with --apply to persist changes."))
            return

        with transaction.atomic():
            locked_snapshot = self._load_snapshot(
                inventory_id=inventory_id,
                item_id=item_id,
                batch_id=batch_id,
                lock_rows=True,
            )
            action = self._apply_snapshot(locked_snapshot, actor_id=actor_id)

        if action == "noop":
            self.stdout.write(self.style.SUCCESS("No repairs needed."))
        else:
            self.stdout.write(self.style.SUCCESS("Inventory aggregate repair applied."))
        self.stdout.write(f"- applied action: {action}")

    def _load_snapshot(
        self,
        *,
        inventory_id: int,
        item_id: int,
        batch_id: int | None,
        lock_rows: bool,
    ) -> AggregateSnapshot:
        now = timezone.now()
        active_status = str(getattr(settings, "NEEDS_INVENTORY_ACTIVE_STATUS", "A")).upper()

        inventory_queryset = Inventory.objects.filter(
            inventory_id=inventory_id,
            item_id=item_id,
        )
        batch_queryset = ItemBatch.objects.filter(
            inventory_id=inventory_id,
            item_id=item_id,
        )
        if lock_rows:
            inventory_queryset = inventory_queryset.select_for_update()
            batch_queryset = batch_queryset.select_for_update()

        active_batches = batch_queryset.filter(
            status_code__iexact=active_status,
        ).filter(
            Q(update_dtime__lte=now) | Q(update_dtime__isnull=True)
        )
        inventory = inventory_queryset.first()
        if batch_id is not None and not active_batches.filter(batch_id=batch_id).exists():
            raise CommandError(
                f"Batch {batch_id} was not found for inventory {inventory_id} / item {item_id}."
            )
        if inventory is None and not batch_queryset.exists():
            raise CommandError(
                f"No inventory aggregate or batch rows were found for inventory {inventory_id} / item {item_id}."
            )
        batch_totals = active_batches.aggregate(
            total_usable=Sum("usable_qty"),
            total_reserved=Sum("reserved_qty"),
            total_defective=Sum("defective_qty"),
            total_expired=Sum("expired_qty"),
            row_count=Count("batch_id"),
        )
        batch_usable_qty = _quantize_qty(batch_totals.get("total_usable"))
        batch_reserved_qty = _quantize_qty(batch_totals.get("total_reserved"))
        batch_defective_qty = _quantize_qty(batch_totals.get("total_defective"))
        batch_expired_qty = _quantize_qty(batch_totals.get("total_expired"))
        batch_row_count = int(batch_totals.get("row_count") or 0)
        batch_uom_code = active_batches.order_by("batch_id").values_list("uom_code", flat=True).first()
        if batch_uom_code is None:
            batch_uom_code = batch_queryset.order_by("batch_id").values_list("uom_code", flat=True).first()

        current_usable_qty = _quantize_qty(getattr(inventory, "usable_qty", 0))
        current_reserved_qty = _quantize_qty(getattr(inventory, "reserved_qty", 0))
        current_defective_qty = _quantize_qty(getattr(inventory, "defective_qty", 0))
        current_expired_qty = _quantize_qty(getattr(inventory, "expired_qty", 0))

        repair_action = "noop"
        if inventory is None and batch_row_count > 0:
            repair_action = "create"
        elif inventory is not None and (
            current_usable_qty != batch_usable_qty
            or current_reserved_qty != batch_reserved_qty
            or current_defective_qty != batch_defective_qty
            or current_expired_qty != batch_expired_qty
        ):
            repair_action = "update"

        return AggregateSnapshot(
            inventory_id=inventory_id,
            item_id=item_id,
            batch_id=batch_id,
            active_status=active_status,
            inventory_row_exists=inventory is not None,
            inventory_status_code=getattr(inventory, "status_code", None),
            inventory_uom_code=getattr(inventory, "uom_code", None),
            current_usable_qty=current_usable_qty,
            current_reserved_qty=current_reserved_qty,
            current_defective_qty=current_defective_qty,
            current_expired_qty=current_expired_qty,
            batch_row_count=batch_row_count,
            batch_uom_code=batch_uom_code,
            batch_usable_qty=batch_usable_qty,
            batch_reserved_qty=batch_reserved_qty,
            batch_defective_qty=batch_defective_qty,
            batch_expired_qty=batch_expired_qty,
            repair_action=repair_action,
        )

    def _apply_snapshot(self, snapshot: AggregateSnapshot, *, actor_id: str) -> str:
        if snapshot.repair_action == "noop":
            return "noop"

        now = timezone.now()
        if snapshot.repair_action == "create":
            Inventory.objects.create(
                inventory_id=snapshot.inventory_id,
                item_id=snapshot.item_id,
                usable_qty=snapshot.batch_usable_qty,
                reserved_qty=snapshot.batch_reserved_qty,
                defective_qty=snapshot.batch_defective_qty,
                expired_qty=snapshot.batch_expired_qty,
                uom_code=snapshot.batch_uom_code,
                status_code=snapshot.active_status,
                update_by_id=actor_id,
                update_dtime=now,
                version_nbr=1,
            )
            return "create"

        inventory = Inventory.objects.select_for_update().get(
            inventory_id=snapshot.inventory_id,
            item_id=snapshot.item_id,
        )
        inventory.usable_qty = snapshot.batch_usable_qty
        inventory.reserved_qty = snapshot.batch_reserved_qty
        inventory.defective_qty = snapshot.batch_defective_qty
        inventory.expired_qty = snapshot.batch_expired_qty
        if not inventory.uom_code and snapshot.batch_uom_code:
            inventory.uom_code = snapshot.batch_uom_code
        inventory.update_by_id = actor_id
        inventory.update_dtime = now
        inventory.version_nbr = int(inventory.version_nbr or 0) + 1
        update_fields = [
            "usable_qty",
            "reserved_qty",
            "defective_qty",
            "expired_qty",
            "update_by_id",
            "update_dtime",
            "version_nbr",
        ]
        if not snapshot.inventory_uom_code and snapshot.batch_uom_code:
            update_fields.append("uom_code")
        inventory.save(update_fields=update_fields)
        return "update"

    def _write_snapshot(self, snapshot: AggregateSnapshot) -> None:
        self.stdout.write("Inventory aggregate repair:")
        self.stdout.write(f"- inventory_id: {snapshot.inventory_id}")
        self.stdout.write(f"- item_id: {snapshot.item_id}")
        if snapshot.batch_id is not None:
            self.stdout.write(f"- batch_id verification: {snapshot.batch_id}")
        self.stdout.write(f"- active status: {snapshot.active_status}")
        self.stdout.write(
            f"- aggregate row: {'present' if snapshot.inventory_row_exists else 'missing'}"
        )
        self.stdout.write(
            "- current aggregate totals: "
            f"usable={snapshot.current_usable_qty:.4f} "
            f"reserved={snapshot.current_reserved_qty:.4f} "
            f"defective={snapshot.current_defective_qty:.4f} "
            f"expired={snapshot.current_expired_qty:.4f} "
            f"available={snapshot.current_available_qty:.4f}"
        )
        self.stdout.write(
            "- active batch totals: "
            f"rows={snapshot.batch_row_count} "
            f"usable={snapshot.batch_usable_qty:.4f} "
            f"reserved={snapshot.batch_reserved_qty:.4f} "
            f"defective={snapshot.batch_defective_qty:.4f} "
            f"expired={snapshot.batch_expired_qty:.4f} "
            f"available={snapshot.batch_available_qty:.4f}"
        )
        self.stdout.write(f"- planned action: {snapshot.repair_action}")
