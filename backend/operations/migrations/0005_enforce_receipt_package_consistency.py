from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0004_make_reliefpkg_destination_nullable"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="operationsreceipt",
            constraint=models.UniqueConstraint(
                fields=("package",),
                name="operations_receipt_unique_package",
            ),
        ),
    ]
