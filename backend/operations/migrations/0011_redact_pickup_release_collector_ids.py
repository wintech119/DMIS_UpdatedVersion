from __future__ import annotations

from django.db import migrations, models


def _collector_id_last4(value: object) -> str | None:
    if value in (None, ""):
        return None
    trimmed = str(value).strip()
    return trimmed[-4:] if trimmed else None


def redact_pickup_release_collector_ids(apps, schema_editor) -> None:
    OperationsPickupRelease = apps.get_model("operations", "OperationsPickupRelease")

    updates: list[object] = []
    for pickup_release in OperationsPickupRelease.objects.only(
        "pickup_release_id",
        "collected_by_id_ref",
        "collected_by_id_last4",
        "release_artifact_json",
    ):
        legacy_value = pickup_release.collected_by_id_ref
        redacted_value = _collector_id_last4(legacy_value)
        release_artifact = dict(pickup_release.release_artifact_json or {})

        if "collected_by_id_ref" in release_artifact:
            redacted_value = _collector_id_last4(release_artifact.get("collected_by_id_ref")) or redacted_value
            release_artifact.pop("collected_by_id_ref", None)
        release_artifact["collected_by_id_last4"] = redacted_value

        pickup_release.collected_by_id_last4 = redacted_value
        pickup_release.release_artifact_json = release_artifact
        updates.append(pickup_release)

    if updates:
        OperationsPickupRelease.objects.bulk_update(
            updates,
            ["collected_by_id_last4", "release_artifact_json"],
        )


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0010_redact_driver_license_numbers"),
    ]

    operations = [
        migrations.AddField(
            model_name="operationspickuprelease",
            name="collected_by_id_last4",
            field=models.CharField(blank=True, max_length=4, null=True),
        ),
        migrations.RunPython(
            redact_pickup_release_collector_ids,
            migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name="operationspickuprelease",
            name="collected_by_id_ref",
        ),
    ]
