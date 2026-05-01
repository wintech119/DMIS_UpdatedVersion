from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_create_dmis_user_auth_m2m"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="RbacBridgeGroup",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "group",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dmis_rbac_bridge_marker",
                        to="auth.group",
                    ),
                ),
            ],
            options={
                "verbose_name": "DMIS RBAC bridge group marker",
                "verbose_name_plural": "DMIS RBAC bridge group markers",
                "db_table": "accounts_rbac_bridge_group",
            },
        ),
    ]
