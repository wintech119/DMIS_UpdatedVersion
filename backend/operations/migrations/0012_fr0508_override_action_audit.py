from __future__ import annotations

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def backfill_override_pending_state(apps, schema_editor) -> None:
    OperationsPackage = apps.get_model("operations", "OperationsPackage")
    OperationsPackage.objects.filter(
        override_status_code="PENDING_OVERRIDE_APPROVAL",
    ).update(override_status_code="PENDING_APPROVAL")


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0011_redact_pickup_release_collector_ids"),
    ]

    operations = [
        migrations.CreateModel(
            name="OperationsActionAudit",
            fields=[
                ("action_audit_id", models.BigAutoField(primary_key=True, serialize=False)),
                ("entity_type", models.CharField(db_index=True, max_length=50)),
                ("entity_id", models.IntegerField(db_index=True)),
                ("tenant_id", models.IntegerField(blank=True, db_index=True, null=True)),
                ("warehouse_id", models.IntegerField(blank=True, db_index=True, null=True)),
                ("action_code", models.CharField(db_index=True, max_length=80)),
                ("action_reason", models.TextField(blank=True, null=True)),
                ("artifact_reference", models.CharField(blank=True, max_length=255, null=True)),
                ("acted_by_user_id", models.CharField(max_length=50)),
                ("acted_by_role_code", models.CharField(max_length=50)),
                ("acted_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "consolidation_leg",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="action_audits",
                        to="operations.operationsconsolidationleg",
                    ),
                ),
                (
                    "package",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="action_audits",
                        to="operations.operationspackage",
                    ),
                ),
            ],
            options={
                "db_table": "operations_action_audit",
                "indexes": [
                    models.Index(fields=["entity_type", "entity_id", "acted_at"], name="ops_action_entity_time"),
                    models.Index(fields=["package", "action_code"], name="ops_action_pkg_code"),
                    models.Index(fields=["consolidation_leg", "action_code"], name="ops_action_leg_code"),
                ],
            },
        ),
        migrations.RunPython(
            backfill_override_pending_state,
            migrations.RunPython.noop,
        ),
    ]
