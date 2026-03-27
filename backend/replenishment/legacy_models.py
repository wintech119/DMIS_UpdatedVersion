from __future__ import annotations

from django.db import models


class Warehouse(models.Model):
    warehouse_id = models.IntegerField(primary_key=True)
    warehouse_name = models.CharField(max_length=255)
    status_code = models.CharField(max_length=1, blank=True, null=True)

    class Meta:
        managed = False
        db_table = "warehouse"

    def __str__(self) -> str:  # pragma: no cover - simple display helper
        return self.warehouse_name or f"Warehouse {self.warehouse_id}"


class Agency(models.Model):
    agency_id = models.IntegerField(primary_key=True)
    agency_name = models.CharField(max_length=255, blank=True, null=True)
    status_code = models.CharField(max_length=1, blank=True, null=True)

    class Meta:
        managed = False
        db_table = "agency"

    def __str__(self) -> str:  # pragma: no cover - simple display helper
        return self.agency_name or f"Agency {self.agency_id}"


class Item(models.Model):
    item_id = models.IntegerField(primary_key=True)
    item_code = models.CharField(max_length=16, blank=True, null=True)
    item_name = models.CharField(max_length=60, blank=True, null=True)
    default_uom_code = models.CharField(max_length=25, blank=True, null=True)
    can_expire_flag = models.BooleanField(default=False)
    issuance_order = models.CharField(max_length=20, blank=True, null=True)
    status_code = models.CharField(max_length=1, blank=True, null=True)

    class Meta:
        managed = False
        db_table = "item"

    def __str__(self) -> str:  # pragma: no cover - simple display helper
        return self.item_name or self.item_code or f"Item {self.item_id}"


class Inventory(models.Model):
    inventory_id = models.IntegerField(primary_key=True)
    item_id = models.IntegerField()
    usable_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reserved_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    defective_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    expired_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    uom_code = models.CharField(max_length=25, blank=True, null=True)
    status_code = models.CharField(max_length=1, blank=True, null=True)
    update_by_id = models.CharField(max_length=20, blank=True, null=True)
    update_dtime = models.DateTimeField(blank=True, null=True)
    version_nbr = models.IntegerField(default=1)

    class Meta:
        managed = False
        db_table = "inventory"
        unique_together = (("inventory_id", "item_id"),)

    def __str__(self) -> str:  # pragma: no cover - simple display helper
        return f"Inventory W{self.inventory_id} / Item {self.item_id}"

    @property
    def available_qty(self):
        return (self.usable_qty or 0) - (self.reserved_qty or 0)


class ItemBatch(models.Model):
    batch_id = models.IntegerField(primary_key=True)
    inventory_id = models.IntegerField()
    item_id = models.IntegerField()
    batch_no = models.CharField(max_length=20, blank=True, null=True)
    batch_date = models.DateField(blank=True, null=True)
    expiry_date = models.DateField(blank=True, null=True)
    usable_qty = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    reserved_qty = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    defective_qty = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    expired_qty = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    uom_code = models.CharField(max_length=25, blank=True, null=True)
    status_code = models.CharField(max_length=1, blank=True, null=True)
    update_by_id = models.CharField(max_length=20, blank=True, null=True)
    update_dtime = models.DateTimeField(blank=True, null=True)
    version_nbr = models.IntegerField(default=1)

    class Meta:
        managed = False
        db_table = "itembatch"
        unique_together = (("inventory_id", "batch_id", "item_id"),)

    def __str__(self) -> str:  # pragma: no cover - simple display helper
        return f"Batch {self.batch_id} / Item {self.item_id}"

    @property
    def available_qty(self):
        return (self.usable_qty or 0) - (self.reserved_qty or 0)


class ReliefRqst(models.Model):
    reliefrqst_id = models.IntegerField(primary_key=True)
    agency_id = models.IntegerField()
    request_date = models.DateField(blank=True, null=True)
    tracking_no = models.CharField(max_length=30, blank=True, null=True)
    eligible_event_id = models.IntegerField(blank=True, null=True)
    urgency_ind = models.CharField(max_length=1, blank=True, null=True)
    rqst_notes_text = models.TextField(blank=True, null=True)
    review_notes_text = models.TextField(blank=True, null=True)
    status_code = models.IntegerField(blank=True, null=True)
    status_reason_desc = models.CharField(max_length=255, blank=True, null=True)
    create_by_id = models.CharField(max_length=20, blank=True, null=True)
    create_dtime = models.DateTimeField(blank=True, null=True)
    review_by_id = models.CharField(max_length=20, blank=True, null=True)
    review_dtime = models.DateTimeField(blank=True, null=True)
    action_by_id = models.CharField(max_length=20, blank=True, null=True)
    action_dtime = models.DateTimeField(blank=True, null=True)
    version_nbr = models.IntegerField(default=1)

    class Meta:
        managed = False
        db_table = "reliefrqst"

    def __str__(self) -> str:  # pragma: no cover - simple display helper
        return self.tracking_no or f"ReliefRqst {self.reliefrqst_id}"


class ReliefRqstItem(models.Model):
    reliefrqst_id = models.IntegerField(primary_key=True)
    item_id = models.IntegerField()
    request_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    issue_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    urgency_ind = models.CharField(max_length=1, blank=True, null=True)
    rqst_reason_desc = models.CharField(max_length=255, blank=True, null=True)
    required_by_date = models.DateField(blank=True, null=True)
    status_code = models.CharField(max_length=1, blank=True, null=True)
    status_reason_desc = models.CharField(max_length=255, blank=True, null=True)
    action_by_id = models.CharField(max_length=20, blank=True, null=True)
    action_dtime = models.DateTimeField(blank=True, null=True)
    version_nbr = models.IntegerField(default=1)

    class Meta:
        managed = False
        db_table = "reliefrqst_item"
        unique_together = (("reliefrqst_id", "item_id"),)


class ReliefPkg(models.Model):
    reliefpkg_id = models.IntegerField(primary_key=True)
    agency_id = models.IntegerField()
    tracking_no = models.CharField(max_length=30, blank=True, null=True)
    eligible_event_id = models.IntegerField(blank=True, null=True)
    to_inventory_id = models.IntegerField(blank=True, null=True)
    reliefrqst_id = models.IntegerField()
    start_date = models.DateField(blank=True, null=True)
    dispatch_dtime = models.DateTimeField(blank=True, null=True)
    transport_mode = models.CharField(max_length=255, blank=True, null=True)
    comments_text = models.CharField(max_length=255, blank=True, null=True)
    status_code = models.CharField(max_length=1, blank=True, null=True)
    create_by_id = models.CharField(max_length=20, blank=True, null=True)
    create_dtime = models.DateTimeField(blank=True, null=True)
    update_by_id = models.CharField(max_length=20, blank=True, null=True)
    update_dtime = models.DateTimeField(blank=True, null=True)
    verify_by_id = models.CharField(max_length=20, blank=True, null=True)
    verify_dtime = models.DateTimeField(blank=True, null=True)
    received_by_id = models.CharField(max_length=20, blank=True, null=True)
    received_dtime = models.DateTimeField(blank=True, null=True)
    version_nbr = models.IntegerField(default=1)

    class Meta:
        managed = False
        db_table = "reliefpkg"

    def __str__(self) -> str:  # pragma: no cover - simple display helper
        return self.tracking_no or f"ReliefPkg {self.reliefpkg_id}"


class ReliefPkgItem(models.Model):
    reliefpkg_id = models.IntegerField(primary_key=True)
    fr_inventory_id = models.IntegerField()
    batch_id = models.IntegerField()
    item_id = models.IntegerField()
    item_qty = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    uom_code = models.CharField(max_length=25, blank=True, null=True)
    reason_text = models.CharField(max_length=255, blank=True, null=True)
    create_by_id = models.CharField(max_length=20, blank=True, null=True)
    create_dtime = models.DateTimeField(blank=True, null=True)
    update_by_id = models.CharField(max_length=20, blank=True, null=True)
    update_dtime = models.DateTimeField(blank=True, null=True)
    version_nbr = models.IntegerField(default=1)

    class Meta:
        managed = False
        db_table = "reliefpkg_item"
        unique_together = (("reliefpkg_id", "fr_inventory_id", "batch_id", "item_id"),)


class Transfer(models.Model):
    transfer_id = models.IntegerField(primary_key=True)
    fr_inventory_id = models.IntegerField()
    to_inventory_id = models.IntegerField()
    eligible_event_id = models.IntegerField(blank=True, null=True)
    transfer_date = models.DateField(blank=True, null=True)
    reason_text = models.CharField(max_length=255, blank=True, null=True)
    status_code = models.CharField(max_length=1, blank=True, null=True)
    create_by_id = models.CharField(max_length=20, blank=True, null=True)
    create_dtime = models.DateTimeField(blank=True, null=True)
    update_by_id = models.CharField(max_length=20, blank=True, null=True)
    update_dtime = models.DateTimeField(blank=True, null=True)
    verify_by_id = models.CharField(max_length=20, blank=True, null=True)
    verify_dtime = models.DateTimeField(blank=True, null=True)
    version_nbr = models.IntegerField(default=1)

    class Meta:
        managed = False
        db_table = "transfer"


class TransferItem(models.Model):
    transfer_id = models.IntegerField(primary_key=True)
    item_id = models.IntegerField()
    batch_id = models.IntegerField(blank=True, null=True)
    inventory_id = models.IntegerField()
    item_qty = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    uom_code = models.CharField(max_length=25, blank=True, null=True)
    reason_text = models.CharField(max_length=255, blank=True, null=True)
    create_by_id = models.CharField(max_length=20, blank=True, null=True)
    create_dtime = models.DateTimeField(blank=True, null=True)
    update_by_id = models.CharField(max_length=20, blank=True, null=True)
    update_dtime = models.DateTimeField(blank=True, null=True)
    version_nbr = models.IntegerField(default=1)

    class Meta:
        managed = False
        db_table = "transfer_item"
        unique_together = (("transfer_id", "item_id", "batch_id", "inventory_id"),)


class DonationIntakeItem(models.Model):
    donation_id = models.IntegerField(primary_key=True)
    inventory_id = models.IntegerField()
    item_id = models.IntegerField()
    batch_no = models.CharField(max_length=20, blank=True, null=True)
    batch_date = models.DateField(blank=True, null=True)
    expiry_date = models.DateField(blank=True, null=True)
    uom_code = models.CharField(max_length=25, blank=True, null=True)
    avg_unit_value = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    ext_item_cost = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    usable_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    defective_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    expired_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status_code = models.CharField(max_length=1, blank=True, null=True)
    comments_text = models.CharField(max_length=255, blank=True, null=True)
    create_by_id = models.CharField(max_length=20, blank=True, null=True)
    create_dtime = models.DateTimeField(blank=True, null=True)
    update_by_id = models.CharField(max_length=20, blank=True, null=True)
    update_dtime = models.DateTimeField(blank=True, null=True)
    version_nbr = models.IntegerField(default=1)

    class Meta:
        managed = False
        db_table = "dnintake_item"
        unique_together = (("donation_id", "inventory_id", "item_id", "batch_no"),)

