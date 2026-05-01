"""DRF serializers for the inventory module. Filled in across Days 6-7."""

from __future__ import annotations

from rest_framework import serializers

from .models import (
    OpeningBalance,
    OpeningBalanceLine,
    StockEvidence,
    StockException,
    StockLedger,
    StockSourceType,
    StockStatus,
    WarehouseInventoryState,
)


class StockSourceTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockSourceType
        fields = "__all__"


class StockStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockStatus
        fields = "__all__"


class WarehouseInventoryStateSerializer(serializers.ModelSerializer):
    class Meta:
        model = WarehouseInventoryState
        fields = [
            "warehouse_id",
            "tenant_id",
            "state_code",
            "current_ob_id",
            "activated_at",
            "last_state_change_at",
        ]


class StockLedgerSerializer(serializers.ModelSerializer):
    source_type_code = serializers.CharField(source="source_type_id", read_only=True)
    from_status_code = serializers.CharField(source="from_status_id", read_only=True)
    to_status_code = serializers.CharField(source="to_status_id", read_only=True)

    class Meta:
        model = StockLedger
        fields = [
            "ledger_id",
            "source_type_code",
            "reference_type",
            "reference_id",
            "tenant_id",
            "warehouse_id",
            "location_id",
            "item_id",
            "batch_id",
            "batch_no",
            "expiry_date",
            "quantity_default_uom",
            "direction",
            "from_status_code",
            "to_status_code",
            "parent_ledger_id",
            "reason_code",
            "reason_text",
            "actor_id",
            "posted_at",
            "request_id",
            "idempotency_key",
        ]


class StockEvidenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockEvidence
        fields = "__all__"
        read_only_fields = ["evidence_id", "uploaded_at", "uploaded_by_id", "file_hash"]


class StockExceptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockException
        fields = "__all__"


class OpeningBalanceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = OpeningBalanceLine
        fields = [
            "line_id",
            "ob",
            "item_id",
            "uom_code",
            "quantity",
            "quantity_default_uom",
            "batch_no",
            "expiry_date",
            "location_id",
            "initial_status_code",
            "unit_cost_estimate",
            "line_notes",
            "posted_ledger_id",
        ]
        read_only_fields = ["line_id", "quantity_default_uom", "posted_ledger_id"]


class OpeningBalanceSerializer(serializers.ModelSerializer):
    lines = OpeningBalanceLineSerializer(many=True, read_only=True)

    class Meta:
        model = OpeningBalance
        fields = [
            "ob_id",
            "ob_number",
            "purpose",
            "tenant_id",
            "warehouse_id",
            "status_code",
            "requested_by_id",
            "submitted_at",
            "approved_by_id",
            "approved_at",
            "posted_at",
            "rejected_by_id",
            "rejection_reason",
            "notes",
            "line_count",
            "total_default_qty",
            "total_estimated_value",
            "valuation_basis",
            "approval_tier",
            "lines",
        ]
        read_only_fields = [
            "ob_id",
            "ob_number",
            "status_code",
            "requested_by_id",
            "submitted_at",
            "approved_by_id",
            "approved_at",
            "posted_at",
            "rejected_by_id",
            "line_count",
            "total_default_qty",
            "total_estimated_value",
            "valuation_basis",
            "approval_tier",
            "lines",
        ]
