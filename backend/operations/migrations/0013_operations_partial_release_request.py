from __future__ import annotations

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0012_fr0508_override_action_audit"),
    ]

    operations = [
        migrations.CreateModel(
            name="OperationsPartialReleaseRequest",
            fields=[
                (
                    "partial_release_request_id",
                    models.BigAutoField(primary_key=True, serialize=False),
                ),
                ("request_reason", models.TextField()),
                (
                    "approval_status_code",
                    models.CharField(db_index=True, max_length=20),
                ),
                ("requested_by_user_id", models.CharField(max_length=50)),
                (
                    "requested_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                (
                    "approved_by_user_id",
                    models.CharField(blank=True, max_length=50, null=True),
                ),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
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
                    models.Index(
                        fields=["package", "approval_status_code"],
                        name="ops_partial_pkg_status",
                    ),
                    models.Index(
                        fields=["requested_at"],
                        name="ops_partial_requested",
                    ),
                ],
            },
        ),
    ]
