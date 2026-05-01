"""
Django models for the DMIS Inventory & Stockpile module (EP-03).

Sprint 1 ships:
  * Foundation tables (built and exercised end-to-end): StockSourceType, StockStatus,
    StockStatusTransition, StockLedger, InventoryAuditLog, StockEvidence,
    StockReservation, StockIdempotency, StockException, WarehouseInventoryState.
  * Active workflow tables (built and exercised end-to-end): OpeningBalance,
    OpeningBalanceLine.
  * Scaffolded workflow tables (model + migration only — service/view/UI ship in
    later sprints): GoodsReceiptNote, GRNLine, StockCount, StockCountLine,
    StockWriteoff, QuarantineCase, FieldReturn, FieldReturnLine, DispatchReversal,
    StockAdjustment, StockTransformation, DataImportBatch, DataImportLine,
    RecordRetentionPolicy.

Cutover model (non-negotiable):
    DMIS inventory begins at zero. Legacy `inventory` and `itembatch` tables are
    NOT written to or read from for operational decisions. The `stock_ledger` is
    the single source of truth for movements; `WarehouseInventoryState` is the
    single source of truth for whether a warehouse has been onboarded.

Re-uses `replenishment.models.AuditedModel` for audit-field consistency with EP-02.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import models

from replenishment.models import AuditedModel


# =============================================================================
# Lookup / Reference Tables
# =============================================================================


class StockSourceType(models.Model):
    """
    Approved inventory source-type whitelist (FR03.25, FR03.26).

    Sprint 1 seeds all 10 codes. Only OPENING_BALANCE is operationally used in
    Sprint 1 production; the others are configured but their workflows ship in
    later sprints.
    """

    code = models.CharField(max_length=40, primary_key=True)
    description = models.CharField(max_length=255)
    increases_total_on_hand = models.BooleanField(default=True)
    increases_available_only = models.BooleanField(default=False)
    requires_approval = models.BooleanField(default=False)
    requires_grn = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = "inventory_source_type"
        ordering = ["sort_order", "code"]

    def __str__(self) -> str:
        return self.code


class StockStatus(models.Model):
    """Stock-status state-machine values (FR03.49, FR03.50)."""

    code = models.CharField(max_length=40, primary_key=True)
    description = models.CharField(max_length=255)
    is_available_for_allocation = models.BooleanField(default=False)
    is_terminal = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = "inventory_status"
        ordering = ["sort_order", "code"]

    def __str__(self) -> str:
        return self.code


class StockStatusTransition(models.Model):
    """Allowed transitions in the stock-status state machine."""

    from_status = models.ForeignKey(
        StockStatus,
        on_delete=models.PROTECT,
        related_name="transitions_from",
    )
    to_status = models.ForeignKey(
        StockStatus,
        on_delete=models.PROTECT,
        related_name="transitions_to",
    )
    required_permission = models.CharField(max_length=80, blank=True)

    class Meta:
        db_table = "inventory_status_transition"
        unique_together = [["from_status", "to_status"]]


class VarianceReasonCode(models.Model):
    """Variance reason codes used by stock counts and adjustments (FR03.60)."""

    code = models.CharField(max_length=40, primary_key=True)
    description = models.CharField(max_length=255)
    requires_root_cause = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = "variance_reason_code"
        ordering = ["sort_order", "code"]

    def __str__(self) -> str:
        return self.code


class WriteoffReasonCode(models.Model):
    """Write-off reason codes (FR03.11)."""

    code = models.CharField(max_length=40, primary_key=True)
    description = models.CharField(max_length=255)
    requires_evidence = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = "writeoff_reason_code"
        ordering = ["sort_order", "code"]

    def __str__(self) -> str:
        return self.code


class QuarantineReasonCode(models.Model):
    """Quarantine reason codes (FR03.37, FR03.64)."""

    code = models.CharField(max_length=40, primary_key=True)
    description = models.CharField(max_length=255)
    default_resolution_hours = models.IntegerField(default=72)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = "quarantine_reason_code"
        ordering = ["sort_order", "code"]

    def __str__(self) -> str:
        return self.code


class CountThreshold(models.Model):
    """Per-category count variance thresholds (FR03.10, FR03.59)."""

    category_id = models.IntegerField(primary_key=True)  # FK to legacy itemcatg
    variance_pct_warn = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("5.00"))
    variance_pct_recount = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("10.00"))
    variance_qty_recount = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal("0"))
    variance_value_recount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0"))

    class Meta:
        db_table = "count_threshold"


class ItemCategoryDefaultCost(models.Model):
    """
    Configured default unit cost per item category, used by the Opening Balance
    valuation pipeline as a fallback when line-level unit_cost_estimate is missing.

    Per the corrected SF5 valuation pipeline:
      ITEM_UNIT_COST -> CATEGORY_ESTIMATE -> SAGE_DEFERRED_EXECUTIVE_ROUTE.
    Missing cost NEVER lowers the approval tier.
    """

    category_id = models.IntegerField(primary_key=True)  # FK to legacy itemcatg
    default_unit_cost = models.DecimalField(max_digits=18, decimal_places=2)
    currency_code = models.CharField(max_length=3, default="JMD")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "item_category_default_cost"


# =============================================================================
# Foundation: ledger, audit log, evidence, reservations, idempotency, exceptions
# =============================================================================


class StockLedger(AuditedModel):
    """
    Append-only inventory ledger — the single source of truth for movements
    (FR03.27, FR03.55, FR03.73). Immutability enforced via PostgreSQL trigger
    installed by migration 0002_immutable_triggers.

    Every inventory mutation in DMIS goes through `services.ledger.post_entry`
    which inserts here; no other code path writes this table.
    """

    DIRECTION_CHOICES = [
        ("IN", "Inbound"),
        ("OUT", "Outbound"),
        ("NEUTRAL", "Neutral / status-only"),
    ]

    ledger_id = models.BigAutoField(primary_key=True)
    source_type = models.ForeignKey(StockSourceType, on_delete=models.PROTECT)
    reference_type = models.CharField(max_length=40)
    reference_id = models.CharField(max_length=64)
    tenant_id = models.IntegerField()
    warehouse_id = models.IntegerField()
    location_id = models.IntegerField(null=True, blank=True)
    item_id = models.IntegerField()
    batch_id = models.IntegerField(null=True, blank=True)
    batch_no = models.CharField(max_length=40, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    quantity_default_uom = models.DecimalField(max_digits=18, decimal_places=6)
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    from_status = models.ForeignKey(
        StockStatus,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ledger_from",
    )
    to_status = models.ForeignKey(
        StockStatus,
        on_delete=models.PROTECT,
        related_name="ledger_to",
    )
    parent_ledger_id = models.BigIntegerField(null=True, blank=True)
    reason_code = models.CharField(max_length=40, blank=True)
    reason_text = models.TextField(blank=True)
    actor_id = models.CharField(max_length=20)
    posted_at = models.DateTimeField(auto_now_add=True)
    request_id = models.CharField(max_length=36, blank=True)
    idempotency_key = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "stock_ledger"
        indexes = [
            models.Index(fields=["tenant_id", "warehouse_id", "item_id", "posted_at"]),
            models.Index(fields=["reference_type", "reference_id"]),
            models.Index(fields=["expiry_date"]),
            models.Index(fields=["batch_id"]),
            models.Index(fields=["idempotency_key"]),
        ]


class InventoryAuditLog(models.Model):
    """
    Append-only workflow-action audit trail (FR03.73). Captures CREATE / EDIT /
    SUBMIT / APPROVE / POST / REJECT / CANCEL transitions across all inventory
    workflows. Immutability enforced via PostgreSQL trigger.

    `before_state` and `after_state` JSON payloads are bounded to ~64 KB and
    PII-masked by `services.audit.serialize_audit_state` before insert
    (architecture review SF8).
    """

    audit_id = models.BigAutoField(primary_key=True)
    entity_type = models.CharField(max_length=40)
    entity_id = models.CharField(max_length=64)
    action = models.CharField(max_length=40)
    actor_id = models.CharField(max_length=20)
    tenant_id = models.IntegerField()
    request_id = models.CharField(max_length=36, blank=True)
    before_state = models.JSONField(default=dict)
    after_state = models.JSONField(default=dict)
    reason_text = models.TextField(blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inventory_audit_log"
        indexes = [
            models.Index(fields=["entity_type", "entity_id", "occurred_at"]),
            models.Index(fields=["actor_id", "occurred_at"]),
        ]


class StockEvidence(models.Model):
    """File / photo evidence attached to inventory workflows (FR03.67, FR03.74)."""

    evidence_id = models.BigAutoField(primary_key=True)
    related_entity = models.CharField(max_length=40)  # OB, GRN, COUNT, WRITEOFF, QUARANTINE, ...
    related_id = models.CharField(max_length=64)
    file_path = models.CharField(max_length=255)
    file_hash = models.CharField(max_length=64)
    file_size_bytes = models.BigIntegerField()
    mime_type = models.CharField(max_length=80)
    description = models.CharField(max_length=255, blank=True)
    uploaded_by_id = models.CharField(max_length=20)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stock_evidence"
        indexes = [models.Index(fields=["related_entity", "related_id"])]


class StockReservation(AuditedModel):
    """Active reservations preventing double-allocation (FR03.51, FR03.52)."""

    STATUS_ACTIVE = "ACTIVE"
    STATUS_RELEASED = "RELEASED"
    STATUS_CONSUMED = "CONSUMED"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_RELEASED, "Released"),
        (STATUS_CONSUMED, "Consumed"),
    ]

    reservation_id = models.AutoField(primary_key=True)
    tenant_id = models.IntegerField()
    warehouse_id = models.IntegerField()
    item_id = models.IntegerField()
    batch_id = models.IntegerField(null=True, blank=True)
    location_id = models.IntegerField(null=True, blank=True)
    quantity_default_uom = models.DecimalField(max_digits=18, decimal_places=6)
    target_type = models.CharField(max_length=40)  # PACKAGE, TRANSFER, REPLENISHMENT, DISPATCH
    target_id = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    reserved_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "stock_reservation"
        indexes = [
            models.Index(fields=["tenant_id", "warehouse_id", "item_id", "batch_id", "status"]),
            models.Index(fields=["target_type", "target_id"]),
        ]


class StockIdempotency(models.Model):
    """Idempotency-key store for critical inventory writes (24-hour retention)."""

    key_hash = models.CharField(max_length=64, primary_key=True)
    actor_id = models.CharField(max_length=20)
    endpoint = models.CharField(max_length=120)
    response_status = models.IntegerField()
    response_body = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stock_idempotency"
        indexes = [models.Index(fields=["created_at"])]


class StockException(AuditedModel):
    """Exception dashboard backing store (FR03.80)."""

    SEVERITY_LOW = "LOW"
    SEVERITY_MEDIUM = "MEDIUM"
    SEVERITY_HIGH = "HIGH"
    SEVERITY_CRITICAL = "CRITICAL"
    SEVERITY_CHOICES = [
        (SEVERITY_LOW, "Low"),
        (SEVERITY_MEDIUM, "Medium"),
        (SEVERITY_HIGH, "High"),
        (SEVERITY_CRITICAL, "Critical"),
    ]

    exception_id = models.BigAutoField(primary_key=True)
    exception_type = models.CharField(max_length=60)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES)
    tenant_id = models.IntegerField()
    warehouse_id = models.IntegerField(null=True, blank=True)
    related_entity = models.CharField(max_length=40, blank=True)
    related_id = models.CharField(max_length=64, blank=True)
    detail = models.JSONField(default=dict)
    detected_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by_id = models.CharField(max_length=20, blank=True)

    class Meta:
        db_table = "stock_exception"
        indexes = [
            models.Index(fields=["tenant_id", "resolved", "severity"]),
            models.Index(fields=["exception_type", "resolved"]),
        ]


class WarehouseInventoryState(AuditedModel):
    """
    Tracks the warehouse-level Opening Balance lifecycle. Single source of truth
    for "is this warehouse onboarded?".

    State machine:
        ZERO_BALANCE -> OPENING_BALANCE_DRAFT -> PENDING_APPROVAL -> APPROVED
        -> POSTED -> INVENTORY_ACTIVE
    PENDING_APPROVAL can revert to OPENING_BALANCE_DRAFT on rejection / return.
    Once INVENTORY_ACTIVE, the warehouse stays there permanently.
    """

    STATE_ZERO_BALANCE = "ZERO_BALANCE"
    STATE_DRAFT = "OPENING_BALANCE_DRAFT"
    STATE_PENDING = "PENDING_APPROVAL"
    STATE_APPROVED = "APPROVED"
    STATE_POSTED = "POSTED"
    STATE_ACTIVE = "INVENTORY_ACTIVE"
    STATE_CHOICES = [
        (STATE_ZERO_BALANCE, "Zero Balance"),
        (STATE_DRAFT, "Opening Balance Draft"),
        (STATE_PENDING, "Pending Approval"),
        (STATE_APPROVED, "Approved"),
        (STATE_POSTED, "Posted"),
        (STATE_ACTIVE, "Inventory Active"),
    ]

    state_id = models.AutoField(primary_key=True)
    tenant_id = models.IntegerField()
    warehouse_id = models.IntegerField(unique=True)
    state_code = models.CharField(max_length=30, choices=STATE_CHOICES, default=STATE_ZERO_BALANCE)
    current_ob_id = models.IntegerField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    last_state_change_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "warehouse_inventory_state"
        indexes = [models.Index(fields=["tenant_id", "state_code"])]


# =============================================================================
# Active Workflow: Opening Balance (Sprint 1 active)
# =============================================================================


class OpeningBalance(AuditedModel):
    """Opening Balance header (FR03.29, FR03.30)."""

    PURPOSE_GO_LIVE = "GO_LIVE"
    PURPOSE_ONBOARD_WAREHOUSE = "ONBOARD_WAREHOUSE"
    PURPOSE_MIGRATION = "MIGRATION"
    PURPOSE_CHOICES = [
        (PURPOSE_GO_LIVE, "Go-Live"),
        (PURPOSE_ONBOARD_WAREHOUSE, "Onboard Warehouse"),
        (PURPOSE_MIGRATION, "Migration"),
    ]

    STATUS_DRAFT = "DRAFT"
    STATUS_PENDING_APPROVAL = "PENDING_APPROVAL"
    STATUS_APPROVED = "APPROVED"
    STATUS_POSTED = "POSTED"
    STATUS_REJECTED = "REJECTED"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PENDING_APPROVAL, "Pending Approval"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_POSTED, "Posted"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    BASIS_ITEM_UNIT_COST = "ITEM_UNIT_COST"
    BASIS_CATEGORY_ESTIMATE = "CATEGORY_ESTIMATE"
    BASIS_SAGE_DEFERRED = "SAGE_DEFERRED_EXECUTIVE_ROUTE"
    BASIS_CHOICES = [
        (BASIS_ITEM_UNIT_COST, "Line-level unit cost"),
        (BASIS_CATEGORY_ESTIMATE, "Category default cost"),
        (BASIS_SAGE_DEFERRED, "Sage deferred — Executive route"),
    ]

    TIER_LOGISTICS = "LOGISTICS_LE_500K"
    TIER_EXECUTIVE = "EXECUTIVE_500K_2M"
    TIER_DEPUTY_DG = "DEPUTY_DG_2M_10M"
    TIER_DG = "DG_GT_10M"
    TIER_CHOICES = [
        (TIER_LOGISTICS, "Logistics (≤ 500K JMD)"),
        (TIER_EXECUTIVE, "Senior Director PEOD (500K–2M JMD)"),
        (TIER_DEPUTY_DG, "Deputy DG (2M–10M JMD)"),
        (TIER_DG, "Director General (> 10M JMD)"),
    ]

    ob_id = models.AutoField(primary_key=True)
    ob_number = models.CharField(max_length=40, unique=True)
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)
    tenant_id = models.IntegerField()
    warehouse_id = models.IntegerField()
    status_code = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    requested_by_id = models.CharField(max_length=20)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by_id = models.CharField(max_length=20, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    rejected_by_id = models.CharField(max_length=20, blank=True)
    rejection_reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    line_count = models.IntegerField(default=0)
    total_default_qty = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal("0"))
    total_estimated_value = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    valuation_basis = models.CharField(
        max_length=40, choices=BASIS_CHOICES, blank=True
    )
    approval_tier = models.CharField(
        max_length=40, choices=TIER_CHOICES, blank=True
    )

    class Meta:
        db_table = "opening_balance"
        indexes = [
            models.Index(fields=["tenant_id", "warehouse_id", "status_code"]),
            models.Index(fields=["status_code", "submitted_at"]),
        ]


class OpeningBalanceLine(AuditedModel):
    """Opening Balance line item (FR03.29, FR03.30)."""

    INITIAL_AVAILABLE = "AVAILABLE"
    INITIAL_QUARANTINE = "QUARANTINE"
    INITIAL_DAMAGED = "DAMAGED"
    INITIAL_STATUS_CHOICES = [
        (INITIAL_AVAILABLE, "Available"),
        (INITIAL_QUARANTINE, "Quarantine"),
        (INITIAL_DAMAGED, "Damaged"),
    ]

    line_id = models.AutoField(primary_key=True)
    ob = models.ForeignKey(
        OpeningBalance, on_delete=models.CASCADE, related_name="lines"
    )
    item_id = models.IntegerField()
    uom_code = models.CharField(max_length=10)
    quantity = models.DecimalField(max_digits=18, decimal_places=6)
    quantity_default_uom = models.DecimalField(max_digits=18, decimal_places=6)
    batch_no = models.CharField(max_length=40, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    location_id = models.IntegerField(null=True, blank=True)
    initial_status_code = models.CharField(
        max_length=20, choices=INITIAL_STATUS_CHOICES, default=INITIAL_AVAILABLE
    )
    unit_cost_estimate = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    line_notes = models.TextField(blank=True)
    posted_ledger_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "opening_balance_line"
        indexes = [models.Index(fields=["ob"])]


# =============================================================================
# Scaffolded Workflow Tables (Sprint 1: model + migration only;
# services/views/UI ship in later sprints)
# =============================================================================


class GoodsReceiptNote(AuditedModel):
    """Goods Receipt Note (FR03.28). SCAFFOLDED — Sprint 2+."""

    grn_id = models.AutoField(primary_key=True)
    grn_number = models.CharField(max_length=40, unique=True)
    source_type = models.ForeignKey(StockSourceType, on_delete=models.PROTECT)
    reference_id = models.CharField(max_length=64)
    tenant_id = models.IntegerField()
    warehouse_id = models.IntegerField()
    received_at = models.DateTimeField()
    received_by_id = models.CharField(max_length=20)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by_id = models.CharField(max_length=20, blank=True)
    status_code = models.CharField(max_length=40, default="DRAFT")
    has_variance = models.BooleanField(default=False)
    variance_pct = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "goods_receipt_note"
        indexes = [
            models.Index(fields=["tenant_id", "warehouse_id", "status_code"]),
            models.Index(fields=["reference_id"]),
        ]


class GRNLine(AuditedModel):
    """Goods Receipt Note line (FR03.28). SCAFFOLDED."""

    line_id = models.AutoField(primary_key=True)
    grn = models.ForeignKey(
        GoodsReceiptNote, on_delete=models.CASCADE, related_name="lines"
    )
    item_id = models.IntegerField()
    expected_qty = models.DecimalField(max_digits=18, decimal_places=6)
    received_qty = models.DecimalField(max_digits=18, decimal_places=6)
    uom_code = models.CharField(max_length=10)
    batch_no = models.CharField(max_length=40, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    condition_status = models.CharField(max_length=40)
    location_id = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "grn_line"
        indexes = [models.Index(fields=["grn"])]


class StockCount(AuditedModel):
    """Physical / cycle count header (FR03.09, .10, .56–.59). SCAFFOLDED."""

    count_id = models.AutoField(primary_key=True)
    count_number = models.CharField(max_length=40, unique=True)
    tenant_id = models.IntegerField()
    warehouse_id = models.IntegerField()
    count_type = models.CharField(max_length=20)  # FULL, ABC_CYCLE, BLIND_CYCLE
    is_blind = models.BooleanField(default=False)
    scope_filter = models.JSONField(default=dict)
    status_code = models.CharField(max_length=40, default="DRAFT")
    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by_id = models.CharField(max_length=20, blank=True)
    freeze_item_ids = models.JSONField(default=list)
    requires_recount = models.BooleanField(default=False)

    class Meta:
        db_table = "stock_count"
        indexes = [models.Index(fields=["tenant_id", "warehouse_id", "status_code"])]


class StockCountLine(AuditedModel):
    """Stock count line (FR03.09, .56–.59). SCAFFOLDED."""

    line_id = models.AutoField(primary_key=True)
    count = models.ForeignKey(
        StockCount, on_delete=models.CASCADE, related_name="lines"
    )
    item_id = models.IntegerField()
    batch_id = models.IntegerField(null=True, blank=True)
    location_id = models.IntegerField(null=True, blank=True)
    system_qty = models.DecimalField(max_digits=18, decimal_places=6)
    counted_qty = models.DecimalField(
        max_digits=18, decimal_places=6, null=True, blank=True
    )
    variance_qty = models.DecimalField(
        max_digits=18, decimal_places=6, null=True, blank=True
    )
    variance_pct = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True
    )
    variance_value = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    variance_reason_code = models.CharField(max_length=40, blank=True)
    root_cause = models.CharField(max_length=40, blank=True)
    requires_recount = models.BooleanField(default=False)

    class Meta:
        db_table = "stock_count_line"
        indexes = [models.Index(fields=["count"])]


class StockWriteoff(AuditedModel):
    """Write-off / disposal workflow (FR03.11). SCAFFOLDED."""

    writeoff_id = models.AutoField(primary_key=True)
    writeoff_number = models.CharField(max_length=40, unique=True)
    tenant_id = models.IntegerField()
    warehouse_id = models.IntegerField()
    item_id = models.IntegerField()
    batch_id = models.IntegerField(null=True, blank=True)
    quantity_default_uom = models.DecimalField(max_digits=18, decimal_places=6)
    reason_code = models.CharField(max_length=40)
    status_code = models.CharField(max_length=40, default="DRAFT")
    estimated_value = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    requested_by_id = models.CharField(max_length=20)
    approved_by_id = models.CharField(max_length=20, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    disposed_by_id = models.CharField(max_length=20, blank=True)
    disposed_at = models.DateTimeField(null=True, blank=True)
    disposal_method = models.CharField(max_length=40, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "stock_writeoff"
        indexes = [models.Index(fields=["tenant_id", "warehouse_id", "status_code"])]


class QuarantineCase(AuditedModel):
    """Quarantine case (FR03.37, .38, .64, .65). SCAFFOLDED."""

    case_id = models.AutoField(primary_key=True)
    case_number = models.CharField(max_length=40, unique=True)
    tenant_id = models.IntegerField()
    warehouse_id = models.IntegerField()
    item_id = models.IntegerField()
    batch_id = models.IntegerField(null=True, blank=True)
    quantity_default_uom = models.DecimalField(max_digits=18, decimal_places=6)
    reason_code = models.CharField(max_length=40)
    quarantine_status = models.CharField(max_length=40, default="OPEN")
    aging_status = models.CharField(max_length=20, default="OK")
    opened_at = models.DateTimeField(auto_now_add=True)
    expected_resolution_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    inspected_by_id = models.CharField(max_length=20, blank=True)
    inspection_outcome = models.CharField(max_length=40, blank=True)
    release_reason = models.TextField(blank=True)

    class Meta:
        db_table = "quarantine_case"
        indexes = [
            models.Index(fields=["tenant_id", "warehouse_id", "quarantine_status"]),
            models.Index(fields=["aging_status", "expected_resolution_at"]),
        ]


class FieldReturn(AuditedModel):
    """Field return header (FR03.33, .34). SCAFFOLDED."""

    return_id = models.AutoField(primary_key=True)
    return_number = models.CharField(max_length=40, unique=True)
    tenant_id = models.IntegerField()
    warehouse_id = models.IntegerField()
    source_dispatch_id = models.IntegerField(null=True, blank=True)
    returned_by_agency = models.CharField(max_length=80, blank=True)
    returned_at = models.DateTimeField()
    status_code = models.CharField(max_length=40, default="DRAFT")
    inspected_by_id = models.CharField(max_length=20, blank=True)
    inspected_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "field_return"
        indexes = [models.Index(fields=["tenant_id", "warehouse_id", "status_code"])]


class FieldReturnLine(AuditedModel):
    """Field return line (FR03.33, .34). SCAFFOLDED."""

    line_id = models.AutoField(primary_key=True)
    field_return = models.ForeignKey(
        FieldReturn, on_delete=models.CASCADE, related_name="lines"
    )
    item_id = models.IntegerField()
    batch_id = models.IntegerField(null=True, blank=True)
    quantity = models.DecimalField(max_digits=18, decimal_places=6)
    condition = models.CharField(max_length=40)
    target_status = models.CharField(max_length=40)

    class Meta:
        db_table = "field_return_line"
        indexes = [models.Index(fields=["field_return"])]


class DispatchReversal(AuditedModel):
    """Dispatch reversal (FR03.35, .36). SCAFFOLDED."""

    reversal_id = models.AutoField(primary_key=True)
    reversal_number = models.CharField(max_length=40, unique=True)
    tenant_id = models.IntegerField()
    source_dispatch_id = models.IntegerField()
    reversal_reason_code = models.CharField(max_length=40)
    reversal_stage = models.CharField(max_length=20)  # RESERVED, PICKED, STAGED
    status_code = models.CharField(max_length=40, default="DRAFT")
    requested_by_id = models.CharField(max_length=20)
    approved_by_id = models.CharField(max_length=20, blank=True)

    class Meta:
        db_table = "dispatch_reversal"
        indexes = [models.Index(fields=["tenant_id", "status_code"])]


class StockAdjustment(AuditedModel):
    """Stock adjustment (FR03.31, .32, .60–.62). SCAFFOLDED."""

    adjustment_id = models.AutoField(primary_key=True)
    adjustment_number = models.CharField(max_length=40, unique=True)
    tenant_id = models.IntegerField()
    warehouse_id = models.IntegerField()
    item_id = models.IntegerField()
    batch_id = models.IntegerField(null=True, blank=True)
    direction = models.CharField(max_length=10)  # POSITIVE, NEGATIVE
    quantity_default_uom = models.DecimalField(max_digits=18, decimal_places=6)
    reason_code = models.CharField(max_length=40)
    root_cause = models.CharField(max_length=40, blank=True)
    related_count_id = models.IntegerField(null=True, blank=True)
    estimated_value = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    status_code = models.CharField(max_length=40, default="DRAFT")
    requested_by_id = models.CharField(max_length=20)
    approved_by_id = models.CharField(max_length=20, blank=True)

    class Meta:
        db_table = "stock_adjustment"
        indexes = [models.Index(fields=["tenant_id", "warehouse_id", "status_code"])]


class StockTransformation(AuditedModel):
    """Stock transformation header (FR03.42, .43, .44). SCAFFOLDED.

    Note: The line side of transformations is captured in `stock_ledger` itself
    via the `parent_ledger_id` self-FK; this header table records the
    transformation event metadata (workflow, approver, type).
    """

    transformation_id = models.AutoField(primary_key=True)
    transformation_type = models.CharField(max_length=40)  # REPACK, KIT, DE_KIT, SPLIT, CONSOLIDATE
    tenant_id = models.IntegerField()
    warehouse_id = models.IntegerField()
    parent_ledger_ref = models.CharField(max_length=64)
    status_code = models.CharField(max_length=40, default="DRAFT")
    requested_by_id = models.CharField(max_length=20)
    approved_by_id = models.CharField(max_length=20, blank=True)

    class Meta:
        db_table = "stock_transformation"
        indexes = [models.Index(fields=["tenant_id", "warehouse_id", "status_code"])]


class DataImportBatch(AuditedModel):
    """Data import batch (FR03.40, .41). SCAFFOLDED."""

    batch_id = models.AutoField(primary_key=True)
    batch_number = models.CharField(max_length=40, unique=True)
    source_label = models.CharField(max_length=80)
    tenant_id = models.IntegerField()
    file_path = models.CharField(max_length=255, blank=True)
    file_hash = models.CharField(max_length=64, blank=True)
    record_count = models.IntegerField(default=0)
    valid_count = models.IntegerField(default=0)
    invalid_count = models.IntegerField(default=0)
    duplicate_count = models.IntegerField(default=0)
    status_code = models.CharField(max_length=40, default="UPLOADED")
    validation_errors = models.JSONField(default=list)
    requested_by_id = models.CharField(max_length=20)
    approved_by_id = models.CharField(max_length=20, blank=True)

    class Meta:
        db_table = "data_import_batch"
        indexes = [models.Index(fields=["tenant_id", "status_code"])]


class DataImportLine(AuditedModel):
    """Data import line (FR03.40). SCAFFOLDED."""

    line_id = models.AutoField(primary_key=True)
    batch = models.ForeignKey(
        DataImportBatch, on_delete=models.CASCADE, related_name="lines"
    )
    row_number = models.IntegerField()
    item_id = models.IntegerField(null=True, blank=True)
    raw_data = models.JSONField(default=dict)
    is_valid = models.BooleanField(default=False)
    validation_errors = models.JSONField(default=list)

    class Meta:
        db_table = "data_import_line"
        indexes = [models.Index(fields=["batch"])]


class RecordRetentionPolicy(AuditedModel):
    """Record retention policy registry (FR03.79). SCAFFOLDED config."""

    policy_id = models.AutoField(primary_key=True)
    record_type = models.CharField(max_length=40, unique=True)
    retention_years = models.IntegerField()
    retention_basis = models.CharField(max_length=80)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "record_retention_policy"
