from __future__ import annotations

from django.db import models
from django.utils import timezone


class AuditedModel(models.Model):
    create_by_id = models.CharField(max_length=50)
    create_dtime = models.DateTimeField(default=timezone.now)
    update_by_id = models.CharField(max_length=50)
    update_dtime = models.DateTimeField(default=timezone.now)
    version_nbr = models.PositiveIntegerField(default=1)

    class Meta:
        abstract = True


class TenantHierarchy(AuditedModel):
    hierarchy_id = models.BigAutoField(primary_key=True)
    parent_tenant_id = models.IntegerField(db_index=True)
    child_tenant_id = models.IntegerField(db_index=True)
    relationship_type = models.CharField(max_length=50)
    can_parent_request_on_behalf_flag = models.BooleanField(default=False)
    effective_date = models.DateField()
    expiry_date = models.DateField(blank=True, null=True)
    status_code = models.CharField(max_length=20, default="ACTIVE")

    class Meta:
        db_table = "tenant_hierarchy"
        indexes = [
            models.Index(fields=["parent_tenant_id", "child_tenant_id"]),
            models.Index(fields=["child_tenant_id", "status_code"]),
        ]


class TenantRequestPolicy(AuditedModel):
    policy_id = models.BigAutoField(primary_key=True)
    tenant_id = models.IntegerField(db_index=True)
    can_self_request_flag = models.BooleanField(default=True)
    request_authority_tenant_id = models.IntegerField(blank=True, null=True)
    can_create_needs_list_flag = models.BooleanField(default=True)
    can_apply_needs_list_to_relief_request_flag = models.BooleanField(default=True)
    can_export_needs_list_for_donation_flag = models.BooleanField(default=True)
    can_broadcast_needs_list_for_donation_flag = models.BooleanField(default=True)
    allow_odpem_bridge_flag = models.BooleanField(default=False)
    effective_date = models.DateField()
    expiry_date = models.DateField(blank=True, null=True)
    status_code = models.CharField(max_length=20, default="ACTIVE")

    class Meta:
        db_table = "tenant_request_policy"
        indexes = [
            models.Index(fields=["tenant_id", "status_code"]),
            models.Index(fields=["request_authority_tenant_id", "status_code"]),
        ]


class TenantControlScope(AuditedModel):
    control_scope_id = models.BigAutoField(primary_key=True)
    controller_tenant_id = models.IntegerField(db_index=True)
    controlled_tenant_id = models.IntegerField(db_index=True)
    control_type = models.CharField(max_length=50)
    effective_date = models.DateField()
    expiry_date = models.DateField(blank=True, null=True)
    status_code = models.CharField(max_length=20, default="ACTIVE")

    class Meta:
        db_table = "tenant_control_scope"
        indexes = [
            models.Index(fields=["controller_tenant_id", "controlled_tenant_id"]),
            models.Index(fields=["controlled_tenant_id", "status_code"]),
        ]


class OperationsReliefRequest(AuditedModel):
    relief_request_id = models.IntegerField(primary_key=True)
    request_no = models.CharField(max_length=30, unique=True)
    requesting_tenant_id = models.IntegerField(db_index=True)
    requesting_agency_id = models.IntegerField(blank=True, null=True)
    beneficiary_tenant_id = models.IntegerField(blank=True, null=True, db_index=True)
    beneficiary_agency_id = models.IntegerField(blank=True, null=True)
    origin_mode = models.CharField(max_length=30)
    source_needs_list_id = models.IntegerField(blank=True, null=True)
    event_id = models.IntegerField(blank=True, null=True)
    request_date = models.DateField()
    urgency_code = models.CharField(max_length=10)
    notes_text = models.TextField(blank=True, null=True)
    status_code = models.CharField(max_length=40, db_index=True)
    submitted_by_id = models.CharField(max_length=50, blank=True, null=True)
    submitted_at = models.DateTimeField(blank=True, null=True)
    reviewed_by_id = models.CharField(max_length=50, blank=True, null=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)
    fulfilled_at = models.DateTimeField(blank=True, null=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "operations_relief_request"
        indexes = [
            models.Index(fields=["status_code", "request_date"]),
            models.Index(fields=["requesting_tenant_id", "status_code"]),
            models.Index(fields=["beneficiary_tenant_id", "status_code"]),
        ]


class OperationsEligibilityDecision(models.Model):
    decision_id = models.BigAutoField(primary_key=True)
    relief_request = models.OneToOneField(
        OperationsReliefRequest,
        on_delete=models.CASCADE,
        related_name="eligibility_decision",
    )
    decision_code = models.CharField(max_length=20)
    decision_reason = models.TextField(blank=True, null=True)
    decided_by_user_id = models.CharField(max_length=50)
    decided_by_role_code = models.CharField(max_length=50)
    decided_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "operations_eligibility_decision"
        indexes = [
            models.Index(fields=["decision_code", "decided_at"]),
        ]


class OperationsPackage(AuditedModel):
    package_id = models.IntegerField(primary_key=True)
    package_no = models.CharField(max_length=30, unique=True)
    relief_request = models.ForeignKey(
        OperationsReliefRequest,
        on_delete=models.CASCADE,
        related_name="packages",
    )
    source_warehouse_id = models.IntegerField(blank=True, null=True)
    fulfillment_mode = models.CharField(max_length=40, default="DIRECT")
    staging_warehouse_id = models.IntegerField(blank=True, null=True, db_index=True)
    recommended_staging_warehouse_id = models.IntegerField(blank=True, null=True)
    staging_selection_basis = models.CharField(max_length=40, blank=True, null=True)
    staging_override_reason = models.TextField(blank=True, null=True)
    consolidation_status = models.CharField(max_length=40, blank=True, null=True, db_index=True)
    partial_release_requested_by_id = models.CharField(max_length=50, blank=True, null=True)
    partial_release_requested_at = models.DateTimeField(blank=True, null=True)
    partial_release_request_reason = models.TextField(blank=True, null=True)
    partial_release_approved_by_id = models.CharField(max_length=50, blank=True, null=True)
    partial_release_approved_at = models.DateTimeField(blank=True, null=True)
    partial_release_approval_reason = models.TextField(blank=True, null=True)
    split_from_package = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="split_children",
        blank=True,
        null=True,
    )
    split_reason = models.TextField(blank=True, null=True)
    split_at = models.DateTimeField(blank=True, null=True)
    destination_tenant_id = models.IntegerField(blank=True, null=True, db_index=True)
    destination_agency_id = models.IntegerField(blank=True, null=True)
    status_code = models.CharField(max_length=40, db_index=True)
    override_status_code = models.CharField(max_length=40, blank=True, null=True)
    committed_at = models.DateTimeField(blank=True, null=True)
    dispatched_at = models.DateTimeField(blank=True, null=True)
    received_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "operations_package"
        indexes = [
            models.Index(fields=["relief_request", "status_code"]),
            models.Index(fields=["destination_tenant_id", "status_code"]),
        ]

    @property
    def effective_dispatch_source_warehouse_id(self) -> int | None:
        if self.fulfillment_mode in {"PICKUP_AT_STAGING", "DELIVER_FROM_STAGING"}:
            return self.staging_warehouse_id or self.source_warehouse_id
        return self.source_warehouse_id


class OperationsPackageLock(models.Model):
    package_lock_id = models.BigAutoField(primary_key=True)
    package = models.OneToOneField(
        OperationsPackage,
        on_delete=models.CASCADE,
        related_name="lock_record",
    )
    lock_owner_user_id = models.CharField(max_length=50)
    lock_owner_role_code = models.CharField(max_length=50)
    lock_started_at = models.DateTimeField(default=timezone.now)
    lock_expires_at = models.DateTimeField(blank=True, null=True)
    lock_status = models.CharField(max_length=20, default="ACTIVE")

    class Meta:
        db_table = "operations_package_lock"
        indexes = [
            models.Index(fields=["lock_status", "lock_expires_at"]),
        ]


class OperationsAllocationLine(AuditedModel):
    """Per-item allocation line with its own source warehouse.

    Replaces the legacy ``reliefpkg_item.fr_inventory_id`` pattern with a
    Django-managed model.  During the transition both this table **and** the
    legacy ``reliefpkg_item`` table are written to (dual-write).
    """

    line_id = models.BigAutoField(primary_key=True)
    package = models.ForeignKey(
        OperationsPackage,
        on_delete=models.CASCADE,
        related_name="allocation_lines",
    )
    item_id = models.IntegerField()
    source_warehouse_id = models.IntegerField()
    batch_id = models.IntegerField()
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    source_type = models.CharField(max_length=20, default="ON_HAND")
    source_record_id = models.IntegerField(blank=True, null=True)
    uom_code = models.CharField(max_length=25, blank=True, null=True)
    reason_text = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = "operations_allocation_line"
        indexes = [
            models.Index(fields=["package", "item_id"]),
            models.Index(fields=["source_warehouse_id", "item_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["package", "source_warehouse_id", "batch_id", "item_id"],
                name="uq_ops_alloc_pkg_wh_batch_item",
            ),
        ]


class OperationsConsolidationLeg(AuditedModel):
    leg_id = models.BigAutoField(primary_key=True)
    package = models.ForeignKey(
        OperationsPackage,
        on_delete=models.CASCADE,
        related_name="consolidation_legs",
    )
    leg_sequence = models.PositiveIntegerField()
    source_warehouse_id = models.IntegerField()
    staging_warehouse_id = models.IntegerField()
    status_code = models.CharField(max_length=30, db_index=True)
    shadow_transfer_id = models.IntegerField(blank=True, null=True)
    driver_name = models.CharField(max_length=120, blank=True, null=True)
    driver_license_no = models.CharField(max_length=50, blank=True, null=True)
    vehicle_id = models.CharField(max_length=50, blank=True, null=True)
    vehicle_registration = models.CharField(max_length=50, blank=True, null=True)
    vehicle_type = models.CharField(max_length=50, blank=True, null=True)
    transport_mode = models.CharField(max_length=50, blank=True, null=True)
    transport_notes = models.TextField(blank=True, null=True)
    dispatched_by_id = models.CharField(max_length=50, blank=True, null=True)
    dispatched_at = models.DateTimeField(blank=True, null=True)
    expected_arrival_at = models.DateTimeField(blank=True, null=True)
    received_by_user_id = models.CharField(max_length=50, blank=True, null=True)
    received_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "operations_consolidation_leg"
        indexes = [
            models.Index(fields=["package", "status_code"]),
            models.Index(fields=["source_warehouse_id", "status_code"]),
            models.Index(fields=["staging_warehouse_id", "status_code"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["package", "leg_sequence"],
                name="uq_ops_consolidation_leg_package_sequence",
            ),
        ]


class OperationsConsolidationLegItem(AuditedModel):
    leg_item_id = models.BigAutoField(primary_key=True)
    leg = models.ForeignKey(
        OperationsConsolidationLeg,
        on_delete=models.CASCADE,
        related_name="items",
    )
    item_id = models.IntegerField()
    batch_id = models.IntegerField()
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    source_type = models.CharField(max_length=20, default="ON_HAND")
    source_record_id = models.IntegerField(blank=True, null=True)
    staging_batch_id = models.IntegerField(blank=True, null=True)
    uom_code = models.CharField(max_length=25, blank=True, null=True)

    class Meta:
        db_table = "operations_consolidation_leg_item"
        indexes = [
            models.Index(fields=["leg", "item_id"]),
            models.Index(fields=["item_id", "batch_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["leg", "item_id", "batch_id", "source_type"],
                name="uq_ops_consolidation_leg_item",
            ),
        ]


class OperationsConsolidationWaybill(models.Model):
    waybill_id = models.BigAutoField(primary_key=True)
    leg = models.ForeignKey(
        OperationsConsolidationLeg,
        on_delete=models.CASCADE,
        related_name="waybills",
    )
    waybill_no = models.CharField(max_length=50, unique=True)
    artifact_payload_json = models.JSONField()
    artifact_version = models.PositiveIntegerField(default=1)
    generated_by_id = models.CharField(max_length=50)
    generated_at = models.DateTimeField(default=timezone.now)
    is_final_flag = models.BooleanField(default=True)

    class Meta:
        db_table = "operations_consolidation_waybill"
        indexes = [
            models.Index(fields=["leg", "generated_at"]),
        ]


class OperationsConsolidationReceipt(models.Model):
    receipt_id = models.BigAutoField(primary_key=True)
    leg = models.OneToOneField(
        OperationsConsolidationLeg,
        on_delete=models.CASCADE,
        related_name="receipt_record",
    )
    received_by_user_id = models.CharField(max_length=50, blank=True, null=True)
    received_by_name = models.CharField(max_length=120, blank=True, null=True)
    received_at = models.DateTimeField(blank=True, null=True)
    receipt_notes = models.TextField(blank=True, null=True)
    receipt_artifact_json = models.JSONField(blank=True, null=True)

    class Meta:
        db_table = "operations_consolidation_receipt"


class OperationsPickupRelease(models.Model):
    pickup_release_id = models.BigAutoField(primary_key=True)
    package = models.OneToOneField(
        OperationsPackage,
        on_delete=models.CASCADE,
        related_name="pickup_release_record",
    )
    staging_warehouse_id = models.IntegerField(blank=True, null=True)
    tenant_id = models.IntegerField(blank=True, null=True)
    collected_by_name = models.CharField(max_length=120, blank=True, null=True)
    collected_by_id_ref = models.CharField(max_length=50, blank=True, null=True)
    released_by_user_id = models.CharField(max_length=50)
    released_by_name = models.CharField(max_length=120, blank=True, null=True)
    released_at = models.DateTimeField(default=timezone.now)
    release_notes = models.TextField(blank=True, null=True)
    release_artifact_json = models.JSONField(blank=True, null=True)

    class Meta:
        db_table = "operations_pickup_release"


class OperationsDispatch(AuditedModel):
    dispatch_id = models.BigAutoField(primary_key=True)
    package = models.OneToOneField(
        OperationsPackage,
        on_delete=models.CASCADE,
        related_name="dispatch_record",
    )
    dispatch_no = models.CharField(max_length=30, unique=True)
    status_code = models.CharField(max_length=30, db_index=True)
    dispatch_at = models.DateTimeField(blank=True, null=True)
    dispatched_by_id = models.CharField(max_length=50, blank=True, null=True)
    source_warehouse_id = models.IntegerField(blank=True, null=True)
    destination_tenant_id = models.IntegerField(blank=True, null=True, db_index=True)
    destination_agency_id = models.IntegerField(blank=True, null=True)

    class Meta:
        db_table = "operations_dispatch"
        indexes = [
            models.Index(fields=["status_code", "dispatch_at"]),
            models.Index(fields=["destination_tenant_id", "status_code"]),
        ]


class OperationsDispatchTransport(models.Model):
    dispatch_transport_id = models.BigAutoField(primary_key=True)
    dispatch = models.OneToOneField(
        OperationsDispatch,
        on_delete=models.CASCADE,
        related_name="transport_record",
    )
    driver_name = models.CharField(max_length=120)
    driver_license_no = models.CharField(max_length=50, blank=True, null=True)
    vehicle_id = models.CharField(max_length=50, blank=True, null=True)
    vehicle_registration = models.CharField(max_length=50, blank=True, null=True)
    vehicle_type = models.CharField(max_length=50, blank=True, null=True)
    transport_mode = models.CharField(max_length=50, blank=True, null=True)
    departure_dtime = models.DateTimeField(blank=True, null=True)
    estimated_arrival_dtime = models.DateTimeField(blank=True, null=True)
    transport_notes = models.TextField(blank=True, null=True)
    route_override_reason = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "operations_dispatch_transport"


class OperationsWaybill(models.Model):
    waybill_id = models.BigAutoField(primary_key=True)
    dispatch = models.ForeignKey(
        OperationsDispatch,
        on_delete=models.CASCADE,
        related_name="waybills",
    )
    waybill_no = models.CharField(max_length=50, unique=True)
    artifact_payload_json = models.JSONField()
    artifact_version = models.PositiveIntegerField(default=1)
    generated_by_id = models.CharField(max_length=50)
    generated_at = models.DateTimeField(default=timezone.now)
    is_final_flag = models.BooleanField(default=True)

    class Meta:
        db_table = "operations_waybill"
        indexes = [
            models.Index(fields=["dispatch", "generated_at"]),
        ]


class OperationsReceipt(models.Model):
    receipt_id = models.BigAutoField(primary_key=True)
    dispatch = models.OneToOneField(
        OperationsDispatch,
        on_delete=models.CASCADE,
        related_name="receipt_record",
    )
    receipt_status_code = models.CharField(max_length=30, db_index=True)
    received_by_user_id = models.CharField(max_length=50, blank=True, null=True)
    received_by_name = models.CharField(max_length=120, blank=True, null=True)
    received_at = models.DateTimeField(blank=True, null=True)
    receipt_notes = models.TextField(blank=True, null=True)
    receipt_artifact_json = models.JSONField(blank=True, null=True)
    beneficiary_delivery_ref = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        db_table = "operations_receipt"

    def _resolve_dispatch(self) -> OperationsDispatch | None:
        cached_dispatch = self._state.fields_cache.get("dispatch")
        if cached_dispatch is not None:
            return cached_dispatch
        if self.dispatch_id is None:
            return None
        try:
            return self.dispatch
        except OperationsDispatch.DoesNotExist:
            return None

    @property
    def package(self) -> OperationsPackage | None:
        """Derive the package through the one-to-one dispatch relationship, or None if no dispatch."""
        dispatch = self._resolve_dispatch()
        return dispatch.package if dispatch is not None else None

    @property
    def package_id(self) -> int | None:
        """Derive the package ID through the one-to-one dispatch relationship."""
        dispatch = self._resolve_dispatch()
        return dispatch.package_id if dispatch is not None else None


class OperationsNotification(models.Model):
    notification_id = models.BigAutoField(primary_key=True)
    event_code = models.CharField(max_length=50, db_index=True)
    entity_type = models.CharField(max_length=50)
    entity_id = models.IntegerField()
    recipient_user_id = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    recipient_role_code = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    recipient_tenant_id = models.IntegerField(blank=True, null=True, db_index=True)
    message_text = models.TextField()
    queue_code = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    read_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "operations_notification"
        indexes = [
            models.Index(fields=["entity_type", "entity_id", "created_at"]),
        ]


class OperationsQueueAssignment(models.Model):
    queue_assignment_id = models.BigAutoField(primary_key=True)
    queue_code = models.CharField(max_length=50, db_index=True)
    entity_type = models.CharField(max_length=50)
    entity_id = models.IntegerField()
    assigned_role_code = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    assigned_tenant_id = models.IntegerField(blank=True, null=True, db_index=True)
    assigned_user_id = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    assignment_status = models.CharField(max_length=20, default="OPEN", db_index=True)
    assigned_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "operations_queue_assignment"
        indexes = [
            models.Index(fields=["entity_type", "entity_id", "assignment_status"]),
        ]


class OperationsStatusHistory(models.Model):
    status_history_id = models.BigAutoField(primary_key=True)
    entity_type = models.CharField(max_length=50, db_index=True)
    entity_id = models.IntegerField(db_index=True)
    from_status_code = models.CharField(max_length=40, blank=True, null=True)
    to_status_code = models.CharField(max_length=40)
    changed_by_id = models.CharField(max_length=50)
    changed_at = models.DateTimeField(default=timezone.now)
    reason_text = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "operations_status_history"
        indexes = [
            models.Index(fields=["entity_type", "entity_id", "changed_at"]),
        ]
