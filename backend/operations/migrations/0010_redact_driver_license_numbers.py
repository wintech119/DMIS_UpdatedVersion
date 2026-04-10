from __future__ import annotations

from django.db import migrations, models


def redact_driver_license_numbers(apps, schema_editor) -> None:
    OperationsConsolidationLeg = apps.get_model("operations", "OperationsConsolidationLeg")
    OperationsDispatchTransport = apps.get_model("operations", "OperationsDispatchTransport")

    leg_updates: list[object] = []
    for leg in OperationsConsolidationLeg.objects.exclude(driver_license_no__isnull=True).only(
        "leg_id",
        "driver_license_no",
        "driver_license_last4",
    ):
        trimmed = (leg.driver_license_no or "").strip()
        leg.driver_license_last4 = trimmed[-4:] if trimmed else None
        leg.driver_license_no = None
        leg_updates.append(leg)
    if leg_updates:
        OperationsConsolidationLeg.objects.bulk_update(
            leg_updates,
            ["driver_license_last4", "driver_license_no"],
        )

    transport_updates: list[object] = []
    for transport in OperationsDispatchTransport.objects.exclude(driver_license_no__isnull=True).only(
        "dispatch_transport_id",
        "driver_license_no",
        "driver_license_last4",
    ):
        trimmed = (transport.driver_license_no or "").strip()
        transport.driver_license_last4 = trimmed[-4:] if trimmed else None
        transport.driver_license_no = None
        transport_updates.append(transport)
    if transport_updates:
        OperationsDispatchTransport.objects.bulk_update(
            transport_updates,
            ["driver_license_last4", "driver_license_no"],
        )


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0009_expand_pickup_release_contract"),
    ]

    operations = [
        migrations.AddField(
            model_name="operationsconsolidationleg",
            name="driver_license_last4",
            field=models.CharField(blank=True, max_length=4, null=True),
        ),
        migrations.AddField(
            model_name="operationsdispatchtransport",
            name="driver_license_last4",
            field=models.CharField(blank=True, max_length=4, null=True),
        ),
        migrations.RunPython(redact_driver_license_numbers, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="operationsconsolidationleg",
            name="driver_license_no",
        ),
        migrations.RemoveField(
            model_name="operationsdispatchtransport",
            name="driver_license_no",
        ),
    ]
