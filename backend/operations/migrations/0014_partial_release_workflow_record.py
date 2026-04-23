from __future__ import annotations

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0013_consolidation_receipt_variance"),
    ]

    operations = [
        migrations.CreateModel(
            name="OperationsPartialReleaseRequest",
            fields=[
                ("create_by_id", models.CharField(max_length=50)),
                ("create_dtime", models.DateTimeField(default=django.utils.timezone.now)),
                ("update_by_id", models.CharField(max_length=50)),
                ("update_dtime", models.DateTimeField(default=django.utils.timezone.now)),
                ("version_nbr", models.PositiveIntegerField(default=1)),
                ("partial_release_request_id", models.BigAutoField(primary_key=True, serialize=False)),
                ("requested_by_user_id", models.CharField(max_length=50)),
                ("requested_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("request_reason", models.CharField(max_length=500)),
                ("approval_status_code", models.CharField(db_index=True, max_length=40)),
                ("approved_by_user_id", models.CharField(blank=True, max_length=50, null=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("approval_reason", models.CharField(blank=True, max_length=500, null=True)),
                ("artifact_json", models.JSONField(blank=True, default=dict)),
                (
                    "package",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="partial_release_requests",
                        to="operations.operationspackage",
                    ),
                ),
                (
                    "released_child_package",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="released_by_partial_release_requests",
                        to="operations.operationspackage",
                    ),
                ),
                (
                    "residual_child_package",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="residual_by_partial_release_requests",
                        to="operations.operationspackage",
                    ),
                ),
            ],
            options={
                "db_table": "operations_partial_release_request",
                "indexes": [
                    models.Index(fields=["package", "requested_at"], name="ops_partial_req_pkg_time"),
                    models.Index(fields=["approval_status_code", "requested_at"], name="ops_partial_req_status_time"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(approval_status_code="PENDING_APPROVAL"),
                        fields=["package"],
                        name="ops_partial_unique_pending_pkg",
                    ),
                ],
            },
        ),
    ]
