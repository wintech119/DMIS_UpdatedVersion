from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0012_fr0508_override_action_audit"),
    ]

    operations = [
        migrations.AddField(
            model_name="operationsconsolidationlegitem",
            name="received_qty",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=15, null=True),
        ),
        migrations.AddField(
            model_name="operationsconsolidationlegitem",
            name="shortage_qty",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=15, null=True),
        ),
        migrations.AddField(
            model_name="operationsconsolidationlegitem",
            name="overage_qty",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=15, null=True),
        ),
        migrations.AddField(
            model_name="operationsconsolidationlegitem",
            name="damaged_qty",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=15, null=True),
        ),
        migrations.AddField(
            model_name="operationsconsolidationlegitem",
            name="variance_reason_text",
            field=models.TextField(blank=True, null=True),
        ),
    ]
