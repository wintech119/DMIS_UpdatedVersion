from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection, transaction


class Command(BaseCommand):
    help = (
        "Scaffold Wave 3 MVP master tables if missing: "
        "role_scope_policy, approval_reason_code, event_severity_profile, "
        "resource_capability_ref, allocation_priority_rule, tenant_access_policy."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply table scaffolding DDL. Without this flag command runs in dry-run mode.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        apply_changes = bool(options.get("apply"))

        self.stdout.write("Wave 3 master table scaffolding:")
        self.stdout.write("- role_scope_policy")
        self.stdout.write("- approval_reason_code")
        self.stdout.write("- event_severity_profile")
        self.stdout.write("- resource_capability_ref")
        self.stdout.write("- allocation_priority_rule")
        self.stdout.write("- tenant_access_policy")
        self.stdout.write(f"- apply mode: {apply_changes}")

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING("Dry-run only. Re-run with --apply to create missing tables.")
            )
            return

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS role_scope_policy (
                        policy_id SERIAL PRIMARY KEY,
                        role_id INTEGER NOT NULL REFERENCES role(id),
                        scope_type VARCHAR(20) NOT NULL
                            CHECK (scope_type IN ('TENANT', 'WAREHOUSE', 'NATIONAL', 'SYSTEM')),
                        tenant_id INTEGER NULL REFERENCES tenant(tenant_id),
                        warehouse_id INTEGER NULL REFERENCES warehouse(warehouse_id),
                        can_read_all_tenants BOOLEAN NOT NULL DEFAULT FALSE,
                        can_act_cross_tenant BOOLEAN NOT NULL DEFAULT FALSE,
                        status_code CHAR(1) NOT NULL DEFAULT 'A' CHECK (status_code IN ('A', 'I')),
                        create_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
                        create_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        update_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
                        update_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        version_nbr INTEGER NOT NULL DEFAULT 1
                    );
                    """
                )
                cursor.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_role_scope_policy_scope
                    ON role_scope_policy (role_id, scope_type, tenant_id, warehouse_id);
                    """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS approval_reason_code (
                        reason_code VARCHAR(40) PRIMARY KEY,
                        reason_label VARCHAR(120) NOT NULL,
                        workflow_stage VARCHAR(30) NOT NULL,
                        outcome_type VARCHAR(20) NOT NULL,
                        requires_comment BOOLEAN NOT NULL DEFAULT TRUE,
                        status_code CHAR(1) NOT NULL DEFAULT 'A' CHECK (status_code IN ('A', 'I')),
                        create_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
                        create_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        update_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
                        update_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        version_nbr INTEGER NOT NULL DEFAULT 1
                    );
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO approval_reason_code (
                        reason_code, reason_label, workflow_stage, outcome_type, requires_comment
                    ) VALUES
                        ('NEEDS_CLARIFICATION', 'Needs Clarification', 'REVIEW', 'RETURN', TRUE),
                        ('POLICY_NONCOMPLIANT', 'Policy Noncompliant', 'REVIEW', 'REJECT', TRUE),
                        ('INSUFFICIENT_BUDGET', 'Insufficient Budget', 'REVIEW', 'REJECT', TRUE),
                        ('HIGH_IMPACT_ESCALATION', 'High Impact Escalation', 'REVIEW', 'ESCALATE', TRUE),
                        ('DUPLICATE_SUBMISSION', 'Duplicate Submission', 'SUBMISSION', 'CANCEL', TRUE)
                    ON CONFLICT (reason_code) DO NOTHING;
                    """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS event_severity_profile (
                        profile_id SERIAL PRIMARY KEY,
                        event_id INTEGER NOT NULL REFERENCES event(event_id),
                        severity_level VARCHAR(20) NOT NULL
                            CHECK (severity_level IN ('LOW', 'MODERATE', 'HIGH', 'SEVERE', 'EXTREME')),
                        impact_score NUMERIC(5, 2) NULL,
                        response_mode VARCHAR(30) NULL,
                        notes_text TEXT NULL,
                        is_active BOOLEAN NOT NULL DEFAULT TRUE,
                        create_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
                        create_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        update_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
                        update_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        version_nbr INTEGER NOT NULL DEFAULT 1
                    );
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_event_severity_profile_event
                    ON event_severity_profile (event_id, is_active);
                    """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS resource_capability_ref (
                        capability_code VARCHAR(40) PRIMARY KEY,
                        capability_name VARCHAR(120) NOT NULL,
                        capability_type VARCHAR(40) NOT NULL,
                        description_text TEXT NULL,
                        status_code CHAR(1) NOT NULL DEFAULT 'A' CHECK (status_code IN ('A', 'I')),
                        create_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
                        create_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        update_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
                        update_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        version_nbr INTEGER NOT NULL DEFAULT 1
                    );
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO resource_capability_ref (
                        capability_code, capability_name, capability_type, description_text
                    ) VALUES
                        ('WAREHOUSING', 'Warehousing Capacity', 'LOGISTICS', 'Storage and handling capacity'),
                        ('TRANSPORT', 'Transport Capacity', 'LOGISTICS', 'Vehicle and routing capacity'),
                        ('PROCUREMENT', 'Procurement Capacity', 'SUPPLY', 'Procurement process throughput'),
                        ('DISTRIBUTION', 'Distribution Capacity', 'OPERATIONS', 'Last-mile distribution capability')
                    ON CONFLICT (capability_code) DO NOTHING;
                    """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS allocation_priority_rule (
                        priority_rule_id SERIAL PRIMARY KEY,
                        rule_name VARCHAR(120) NOT NULL,
                        event_phase_code VARCHAR(20) NOT NULL REFERENCES ref_event_phase(phase_code),
                        criticality_weight NUMERIC(5, 2) NOT NULL DEFAULT 0,
                        urgency_weight NUMERIC(5, 2) NOT NULL DEFAULT 0,
                        population_weight NUMERIC(5, 2) NOT NULL DEFAULT 0,
                        chronology_weight NUMERIC(5, 2) NOT NULL DEFAULT 0,
                        tenant_id INTEGER NULL REFERENCES tenant(tenant_id),
                        effective_date DATE NOT NULL DEFAULT CURRENT_DATE,
                        expiry_date DATE NULL,
                        status_code CHAR(1) NOT NULL DEFAULT 'A' CHECK (status_code IN ('A', 'I')),
                        create_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
                        create_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        update_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
                        update_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        version_nbr INTEGER NOT NULL DEFAULT 1
                    );
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_allocation_priority_rule_tenant_phase
                    ON allocation_priority_rule (tenant_id, event_phase_code, effective_date);
                    """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tenant_access_policy (
                        policy_id SERIAL PRIMARY KEY,
                        tenant_id INTEGER NOT NULL REFERENCES tenant(tenant_id),
                        allow_neoc_actions BOOLEAN NOT NULL DEFAULT FALSE,
                        allow_cross_tenant_read BOOLEAN NOT NULL DEFAULT FALSE,
                        allow_cross_tenant_write BOOLEAN NOT NULL DEFAULT FALSE,
                        policy_source VARCHAR(40) NULL,
                        effective_date DATE NOT NULL DEFAULT CURRENT_DATE,
                        expiry_date DATE NULL,
                        status_code CHAR(1) NOT NULL DEFAULT 'A' CHECK (status_code IN ('A', 'I')),
                        create_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
                        create_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        update_by_id VARCHAR(20) NOT NULL DEFAULT 'SYSTEM',
                        update_dtime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        version_nbr INTEGER NOT NULL DEFAULT 1
                    );
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_tenant_access_policy_active
                    ON tenant_access_policy (tenant_id, effective_date, expiry_date, status_code);
                    """
                )

        self.stdout.write(self.style.SUCCESS("Wave 3 master table scaffolding applied."))

