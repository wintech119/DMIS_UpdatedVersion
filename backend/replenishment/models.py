"""
Django models for the DMIS Supply Replenishment Module (EP-02).

These models map to the database schema defined in EP02_SUPPLY_REPLENISHMENT_SCHEMA.sql.
They provide ORM access to the replenishment workflow tables.

Note: Legacy tables (inventory, transfer, reliefpkg, etc.) are still accessed via raw SQL
in data_access.py. This file only models the NEW tables created for EP-02.
"""

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal


# =============================================================================
# Base Model with Audit Fields
# =============================================================================

class AuditedModel(models.Model):
    """
    Abstract base model providing common audit fields.
    All EP-02 tables inherit from this for consistency.
    """
    create_by_id = models.CharField(max_length=20)
    create_dtime = models.DateTimeField(auto_now_add=True)
    update_by_id = models.CharField(max_length=20)
    update_dtime = models.DateTimeField(auto_now=True)
    version_nbr = models.IntegerField(default=1)

    class Meta:
        abstract = True


# =============================================================================
# Event Phase Management
# =============================================================================

class EventPhaseConfig(AuditedModel):
    """
    Phase-specific configuration parameters for each disaster event.
    Stores demand window, planning window, safety factors, and freshness thresholds.
    """
    PHASE_CHOICES = [
        ('SURGE', 'Surge'),
        ('STABILIZED', 'Stabilized'),
        ('BASELINE', 'Baseline'),
    ]

    config_id = models.AutoField(primary_key=True)
    event_id = models.IntegerField()  # FK to legacy event table
    phase = models.CharField(max_length=15, choices=PHASE_CHOICES)
    demand_window_hours = models.IntegerField(validators=[MinValueValidator(1)])
    planning_window_hours = models.IntegerField(validators=[MinValueValidator(1)])
    safety_buffer_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('25.00'),
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('100'))]
    )
    safety_factor = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal('1.25'),
        validators=[MinValueValidator(Decimal('1.00'))]
    )
    freshness_threshold_hours = models.IntegerField(default=2)
    stale_threshold_hours = models.IntegerField(default=6)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'event_phase_config'
        unique_together = [['event_id', 'phase']]
        ordering = ['event_id', 'phase']

    def __str__(self):
        return f"Event {self.event_id} - {self.phase}"


class EventPhaseHistory(models.Model):
    """
    Audit trail of event phase transitions.
    Automatically populated by database trigger when event.current_phase changes.
    """
    PHASE_CHOICES = EventPhaseConfig.PHASE_CHOICES

    history_id = models.AutoField(primary_key=True)
    event_id = models.IntegerField()  # FK to legacy event table
    from_phase = models.CharField(max_length=15, choices=PHASE_CHOICES, null=True, blank=True)
    to_phase = models.CharField(max_length=15, choices=PHASE_CHOICES)
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.CharField(max_length=20)
    reason_text = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = 'event_phase_history'
        ordering = ['-changed_at']

    def __str__(self):
        return f"Event {self.event_id}: {self.from_phase or 'Initial'} → {self.to_phase}"


# =============================================================================
# Needs List Workflow
# =============================================================================

class NeedsList(AuditedModel):
    """
    Main needs list header.
    Represents a system-generated replenishment recommendation for a warehouse/event/phase.
    """
    PHASE_CHOICES = EventPhaseConfig.PHASE_CHOICES
    FRESHNESS_CHOICES = [
        ('HIGH', 'High'),
        ('MEDIUM', 'Medium'),
        ('LOW', 'Low'),
    ]
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('PENDING_APPROVAL', 'Pending Approval'),
        ('UNDER_REVIEW', 'Under Review'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('RETURNED', 'Returned'),
        ('IN_PROGRESS', 'In Progress'),
        ('FULFILLED', 'Fulfilled'),
        ('CANCELLED', 'Cancelled'),
        ('SUPERSEDED', 'Superseded'),
    ]

    needs_list_id = models.AutoField(primary_key=True)
    needs_list_no = models.CharField(max_length=30, unique=True)
    event_id = models.IntegerField()  # FK to legacy event table
    warehouse_id = models.IntegerField()  # FK to legacy warehouse table
    event_phase = models.CharField(max_length=15, choices=PHASE_CHOICES)
    calculation_dtime = models.DateTimeField()
    demand_window_hours = models.IntegerField()
    planning_window_hours = models.IntegerField()
    safety_factor = models.DecimalField(max_digits=4, decimal_places=2)
    data_freshness_level = models.CharField(max_length=10, choices=FRESHNESS_CHOICES, default='HIGH')
    status_code = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    total_gap_qty = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_estimated_value = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)

    # Workflow timestamps
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.CharField(max_length=20, null=True, blank=True)
    under_review_at = models.DateTimeField(null=True, blank=True)
    under_review_by = models.CharField(max_length=20, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.CharField(max_length=20, null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.CharField(max_length=20, null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.CharField(max_length=20, null=True, blank=True)
    rejection_reason = models.CharField(max_length=255, null=True, blank=True)
    returned_at = models.DateTimeField(null=True, blank=True)
    returned_by = models.CharField(max_length=20, null=True, blank=True)
    returned_reason = models.CharField(max_length=255, null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.CharField(max_length=20, null=True, blank=True)

    superseded_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='superseded_from'
    )
    notes_text = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'needs_list'
        ordering = ['-calculation_dtime']
        indexes = [
            models.Index(fields=['event_id']),
            models.Index(fields=['warehouse_id']),
            models.Index(fields=['status_code']),
            models.Index(fields=['calculation_dtime']),
        ]

    def __str__(self):
        return f"{self.needs_list_no} ({self.status_code})"


class NeedsListItem(AuditedModel):
    """
    Individual item lines within a needs list with calculation details.
    Stores burn rate, gaps, horizon allocations, and adjustment tracking.
    """
    BURN_RATE_SOURCE_CHOICES = [
        ('CALCULATED', 'Calculated'),
        ('BASELINE', 'Baseline'),
        ('MANUAL', 'Manual'),
        ('ESTIMATED', 'Estimated'),
    ]
    SEVERITY_CHOICES = [
        ('CRITICAL', 'Critical'),
        ('WARNING', 'Warning'),
        ('WATCH', 'Watch'),
        ('OK', 'OK'),
    ]
    ADJUSTMENT_REASON_CHOICES = [
        ('DEMAND_ADJUSTED', 'Demand Adjusted'),
        ('PARTIAL_COVERAGE', 'Partial Coverage'),
        ('PRIORITY_CHANGE', 'Priority Change'),
        ('BUDGET_CONSTRAINT', 'Budget Constraint'),
        ('SUPPLIER_LIMIT', 'Supplier Limit'),
        ('OTHER', 'Other'),
    ]
    FULFILLMENT_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PARTIAL', 'Partial'),
        ('FULFILLED', 'Fulfilled'),
        ('CANCELLED', 'Cancelled'),
    ]

    needs_list_item_id = models.AutoField(primary_key=True)
    needs_list = models.ForeignKey(
        NeedsList,
        on_delete=models.CASCADE,
        related_name='items'
    )
    item_id = models.IntegerField()  # FK to legacy item table
    uom_code = models.CharField(max_length=25)

    # Calculation inputs (snapshot at calculation time)
    burn_rate = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal('0.0000'))
    burn_rate_source = models.CharField(max_length=20, choices=BURN_RATE_SOURCE_CHOICES, default='CALCULATED')
    available_stock = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    reserved_qty = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    inbound_transfer_qty = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    inbound_donation_qty = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    inbound_procurement_qty = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))

    # Calculation outputs
    required_qty = models.DecimalField(max_digits=15, decimal_places=2)
    coverage_qty = models.DecimalField(max_digits=15, decimal_places=2)
    gap_qty = models.DecimalField(max_digits=15, decimal_places=2)
    time_to_stockout_hours = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    severity_level = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='OK')

    # Three Horizons allocation
    horizon_a_qty = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    horizon_a_source_warehouse_id = models.IntegerField(null=True, blank=True)  # FK to legacy warehouse
    horizon_b_qty = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    horizon_c_qty = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))

    # Adjustments
    adjusted_qty = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    adjustment_reason = models.CharField(max_length=50, choices=ADJUSTMENT_REASON_CHOICES, null=True, blank=True)
    adjustment_notes = models.CharField(max_length=255, null=True, blank=True)
    adjusted_by = models.CharField(max_length=20, null=True, blank=True)
    adjusted_at = models.DateTimeField(null=True, blank=True)

    # Fulfillment tracking
    fulfilled_qty = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    fulfillment_status = models.CharField(max_length=20, choices=FULFILLMENT_STATUS_CHOICES, default='PENDING')

    class Meta:
        db_table = 'needs_list_item'
        unique_together = [['needs_list', 'item_id']]
        ordering = ['needs_list', 'severity_level', 'item_id']
        indexes = [
            models.Index(fields=['needs_list']),
            models.Index(fields=['item_id']),
            models.Index(fields=['severity_level']),
        ]

    def __str__(self):
        return f"{self.needs_list.needs_list_no} - Item {self.item_id}"


class NeedsListAudit(models.Model):
    """
    Immutable audit trail for all needs list actions.
    Records who did what and when for compliance and traceability.
    """
    ACTION_TYPE_CHOICES = [
        ('CREATED', 'Created'),
        ('SUBMITTED', 'Submitted'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('RETURNED', 'Returned'),
        ('QUANTITY_ADJUSTED', 'Quantity Adjusted'),
        ('STATUS_CHANGED', 'Status Changed'),
        ('HORIZON_CHANGED', 'Horizon Changed'),
        ('SUPERSEDED', 'Superseded'),
        ('CANCELLED', 'Cancelled'),
        ('FULFILLED', 'Fulfilled'),
        ('COMMENT_ADDED', 'Comment Added'),
    ]

    audit_id = models.AutoField(primary_key=True)
    needs_list = models.ForeignKey(
        NeedsList,
        on_delete=models.CASCADE,
        related_name='audit_logs'
    )
    needs_list_item = models.ForeignKey(
        NeedsListItem,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='audit_logs'
    )
    action_type = models.CharField(max_length=30, choices=ACTION_TYPE_CHOICES)
    field_name = models.CharField(max_length=50, null=True, blank=True)
    old_value = models.TextField(null=True, blank=True)
    new_value = models.TextField(null=True, blank=True)
    reason_code = models.CharField(max_length=50, null=True, blank=True)
    notes_text = models.CharField(max_length=500, null=True, blank=True)
    actor_user_id = models.CharField(max_length=20)
    action_dtime = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'needs_list_audit'
        ordering = ['-action_dtime']
        indexes = [
            models.Index(fields=['needs_list']),
            models.Index(fields=['action_dtime']),
        ]

    def __str__(self):
        return f"{self.action_type} by {self.actor_user_id} at {self.action_dtime}"


# =============================================================================
# Burn Rate Tracking
# =============================================================================

class BurnRateSnapshot(models.Model):
    """
    Historical record of burn rate calculations for trending and analysis.
    Snapshots are created each time a needs list is generated.
    """
    PHASE_CHOICES = EventPhaseConfig.PHASE_CHOICES
    SOURCE_CHOICES = [
        ('CALCULATED', 'Calculated'),
        ('BASELINE', 'Baseline'),
        ('ESTIMATED', 'Estimated'),
    ]
    FRESHNESS_CHOICES = NeedsList.FRESHNESS_CHOICES

    snapshot_id = models.AutoField(primary_key=True)
    warehouse_id = models.IntegerField()  # FK to legacy warehouse table
    item_id = models.IntegerField()  # FK to legacy item table
    event_id = models.IntegerField()  # FK to legacy event table
    event_phase = models.CharField(max_length=15, choices=PHASE_CHOICES)
    snapshot_dtime = models.DateTimeField(auto_now_add=True)
    demand_window_hours = models.IntegerField()
    fulfillment_count = models.IntegerField(default=0)
    total_fulfilled_qty = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    burn_rate = models.DecimalField(max_digits=10, decimal_places=4)
    burn_rate_source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    data_freshness_level = models.CharField(max_length=10, choices=FRESHNESS_CHOICES)
    time_to_stockout_hours = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    available_stock_at_calc = models.DecimalField(max_digits=15, decimal_places=2)

    class Meta:
        db_table = 'burn_rate_snapshot'
        ordering = ['-snapshot_dtime']
        indexes = [
            models.Index(fields=['warehouse_id', 'item_id']),
            models.Index(fields=['event_id']),
            models.Index(fields=['snapshot_dtime']),
        ]

    def __str__(self):
        return f"Snapshot {self.snapshot_id} - W{self.warehouse_id} I{self.item_id}"


# =============================================================================
# Data Freshness Tracking
# =============================================================================

class WarehouseSyncLog(models.Model):
    """
    Log of warehouse data synchronization events for freshness tracking.
    Records each time inventory data is synced from a warehouse.
    """
    SYNC_TYPE_CHOICES = [
        ('AUTO', 'Auto'),
        ('MANUAL', 'Manual'),
        ('SCHEDULED', 'Scheduled'),
    ]
    SYNC_STATUS_CHOICES = [
        ('SUCCESS', 'Success'),
        ('PARTIAL', 'Partial'),
        ('FAILED', 'Failed'),
    ]

    sync_id = models.AutoField(primary_key=True)
    warehouse_id = models.IntegerField()  # FK to legacy warehouse table
    sync_dtime = models.DateTimeField(auto_now_add=True)
    sync_type = models.CharField(max_length=20, choices=SYNC_TYPE_CHOICES, default='AUTO')
    sync_status = models.CharField(max_length=10, choices=SYNC_STATUS_CHOICES)
    items_synced = models.IntegerField(default=0)
    error_message = models.TextField(null=True, blank=True)
    triggered_by = models.CharField(max_length=20, null=True, blank=True)

    class Meta:
        db_table = 'warehouse_sync_log'
        ordering = ['-sync_dtime']
        indexes = [
            models.Index(fields=['warehouse_id']),
            models.Index(fields=['sync_dtime']),
        ]

    def __str__(self):
        return f"Sync {self.sync_id} - W{self.warehouse_id} ({self.sync_status})"


# =============================================================================
# Procurement (Horizon C)
# =============================================================================

class Supplier(AuditedModel):
    """
    Supplier/vendor master for Horizon C procurement.
    Tracks approved suppliers and framework agreements.
    """
    STATUS_CHOICES = [
        ('A', 'Active'),
        ('I', 'Inactive'),
    ]

    supplier_id = models.AutoField(primary_key=True)
    supplier_code = models.CharField(max_length=20, unique=True)
    supplier_name = models.CharField(max_length=120)
    contact_name = models.CharField(max_length=80, null=True, blank=True)
    phone_no = models.CharField(max_length=20, null=True, blank=True)
    email_text = models.EmailField(max_length=100, null=True, blank=True)
    address_text = models.CharField(max_length=255, null=True, blank=True)
    parish_code = models.CharField(max_length=2, null=True, blank=True)
    country_id = models.IntegerField(null=True, blank=True)  # FK to legacy country table
    default_lead_time_days = models.IntegerField(default=14)
    is_framework_supplier = models.BooleanField(default=False)
    framework_contract_no = models.CharField(max_length=50, null=True, blank=True)
    framework_expiry_date = models.DateField(null=True, blank=True)
    status_code = models.CharField(max_length=1, choices=STATUS_CHOICES, default='A')

    class Meta:
        db_table = 'supplier'
        ordering = ['supplier_name']

    def __str__(self):
        return f"{self.supplier_code} - {self.supplier_name}"


class Procurement(AuditedModel):
    """
    Procurement orders generated from Horizon C needs list items.
    Follows GOJ procurement regulations and approval tiers.
    """
    METHOD_CHOICES = [
        ('EMERGENCY_DIRECT', 'Emergency Direct'),
        ('SINGLE_SOURCE', 'Single Source'),
        ('RFQ', 'Request for Quotation'),
        ('RESTRICTED_BIDDING', 'Restricted Bidding'),
        ('OPEN_TENDER', 'Open Tender'),
        ('FRAMEWORK', 'Framework Agreement'),
    ]
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('PENDING_APPROVAL', 'Pending Approval'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('ORDERED', 'Ordered'),
        ('SHIPPED', 'Shipped'),
        ('PARTIAL_RECEIVED', 'Partial Received'),
        ('RECEIVED', 'Received'),
        ('CANCELLED', 'Cancelled'),
    ]
    TIER_CHOICES = [
        ('TIER_1', 'Tier 1'),
        ('TIER_2', 'Tier 2'),
        ('TIER_3', 'Tier 3'),
        ('EMERGENCY', 'Emergency'),
    ]

    procurement_id = models.AutoField(primary_key=True)
    procurement_no = models.CharField(max_length=30, unique=True)
    needs_list = models.ForeignKey(
        NeedsList,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='procurements'
    )
    event_id = models.IntegerField()  # FK to legacy event table
    target_warehouse_id = models.IntegerField()  # FK to legacy warehouse table
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='procurements'
    )
    procurement_method = models.CharField(max_length=25, choices=METHOD_CHOICES)
    po_number = models.CharField(max_length=50, null=True, blank=True)
    total_value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    currency_code = models.CharField(max_length=10, default='JMD')
    status_code = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')

    # Approval tracking
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.CharField(max_length=20, null=True, blank=True)
    approval_threshold_tier = models.CharField(max_length=10, choices=TIER_CHOICES, null=True, blank=True)

    # Fulfillment tracking
    shipped_at = models.DateTimeField(null=True, blank=True)
    expected_arrival = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    received_by = models.CharField(max_length=20, null=True, blank=True)

    notes_text = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'procurement'
        ordering = ['-create_dtime']
        indexes = [
            models.Index(fields=['event_id']),
            models.Index(fields=['target_warehouse_id']),
            models.Index(fields=['status_code']),
            models.Index(fields=['needs_list']),
        ]

    def __str__(self):
        return f"{self.procurement_no} ({self.status_code})"


class ProcurementItem(AuditedModel):
    """
    Line items within a procurement order.
    Tracks ordered vs received quantities.
    """
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PARTIAL', 'Partial'),
        ('RECEIVED', 'Received'),
        ('CANCELLED', 'Cancelled'),
    ]

    procurement_item_id = models.AutoField(primary_key=True)
    procurement = models.ForeignKey(
        Procurement,
        on_delete=models.CASCADE,
        related_name='items'
    )
    item_id = models.IntegerField()  # FK to legacy item table
    needs_list_item = models.ForeignKey(
        NeedsListItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='procurement_items'
    )
    ordered_qty = models.DecimalField(max_digits=15, decimal_places=2)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    line_total = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    uom_code = models.CharField(max_length=25)
    received_qty = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    status_code = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')

    class Meta:
        db_table = 'procurement_item'
        ordering = ['procurement', 'item_id']
        indexes = [
            models.Index(fields=['procurement']),
            models.Index(fields=['item_id']),
        ]

    def __str__(self):
        return f"{self.procurement.procurement_no} - Item {self.item_id}"


# =============================================================================
# Lead Time Configuration
# =============================================================================

class LeadTimeConfig(AuditedModel):
    """
    Configurable lead times for Three Horizons:
    - Horizon A: Warehouse routes (from_warehouse → to_warehouse)
    - Horizon B: Donations (default lead time)
    - Horizon C: Suppliers (supplier-specific lead times)
    """
    HORIZON_CHOICES = [
        ('A', 'Horizon A - Transfers'),
        ('B', 'Horizon B - Donations'),
        ('C', 'Horizon C - Procurement'),
    ]

    config_id = models.AutoField(primary_key=True)
    horizon = models.CharField(max_length=1, choices=HORIZON_CHOICES)
    from_warehouse_id = models.IntegerField(null=True, blank=True)  # FK to legacy warehouse (Horizon A only)
    to_warehouse_id = models.IntegerField(null=True, blank=True)  # FK to legacy warehouse (Horizon A only)
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='lead_times'
    )  # Horizon C only
    lead_time_hours = models.IntegerField(validators=[MinValueValidator(1)])
    is_default = models.BooleanField(default=False)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'lead_time_config'
        ordering = ['horizon', 'from_warehouse_id', 'to_warehouse_id']

    def __str__(self):
        if self.horizon == 'A':
            return f"Transfer W{self.from_warehouse_id}→W{self.to_warehouse_id}: {self.lead_time_hours}h"
        elif self.horizon == 'C' and self.supplier:
            return f"Procurement {self.supplier.supplier_code}: {self.lead_time_hours}h"
        else:
            return f"Horizon {self.horizon}: {self.lead_time_hours}h"
