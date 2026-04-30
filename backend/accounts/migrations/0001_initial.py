import accounts.managers
import django.contrib.auth.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="DmisUser",
                    fields=[
                        ("user_id", models.IntegerField(primary_key=True, serialize=False)),
                        ("email", models.EmailField(max_length=200, unique=True)),
                        ("password", models.CharField(db_column="password_hash", max_length=256, verbose_name="password")),
                        ("first_name", models.CharField(blank=True, max_length=100, null=True)),
                        ("last_name", models.CharField(blank=True, max_length=100, null=True)),
                        ("full_name", models.CharField(blank=True, max_length=200, null=True)),
                        ("is_active", models.BooleanField(default=True)),
                        ("organization", models.CharField(blank=True, max_length=200, null=True)),
                        ("job_title", models.CharField(blank=True, max_length=200, null=True)),
                        ("phone", models.CharField(blank=True, max_length=50, null=True)),
                        ("timezone", models.CharField(default="America/Jamaica", max_length=50)),
                        ("language", models.CharField(default="en", max_length=10)),
                        ("notification_preferences", models.TextField(blank=True, null=True)),
                        ("assigned_warehouse_id", models.IntegerField(blank=True, null=True)),
                        ("last_login", models.DateTimeField(blank=True, db_column="last_login_at", null=True, verbose_name="last login")),
                        ("create_dtime", models.DateTimeField()),
                        ("update_dtime", models.DateTimeField()),
                        (
                            "username",
                            models.CharField(
                                blank=True,
                                max_length=60,
                                null=True,
                                unique=True,
                                validators=[django.contrib.auth.validators.UnicodeUsernameValidator()],
                            ),
                        ),
                        ("user_name", models.CharField(max_length=20)),
                        ("password_algo", models.CharField(default="argon2id", editable=False, max_length=20)),
                        ("mfa_enabled", models.BooleanField(default=False)),
                        ("mfa_secret", models.CharField(blank=True, editable=False, max_length=64, null=True)),
                        ("failed_login_count", models.SmallIntegerField(default=0, editable=False)),
                        ("lock_until_at", models.DateTimeField(blank=True, editable=False, null=True)),
                        ("password_changed_at", models.DateTimeField(blank=True, editable=False, null=True)),
                        ("agency_id", models.IntegerField(blank=True, null=True)),
                        ("status_code", models.CharField(default="A", max_length=1)),
                        ("version_nbr", models.IntegerField(default=1)),
                        ("login_count", models.IntegerField(default=0)),
                        (
                            "groups",
                            models.ManyToManyField(
                                blank=True,
                                help_text="The groups this user belongs to. A user will get all permissions granted to each of their groups.",
                                related_name="user_set",
                                related_query_name="user",
                                to="auth.group",
                                verbose_name="groups",
                            ),
                        ),
                        (
                            "user_permissions",
                            models.ManyToManyField(
                                blank=True,
                                help_text="Specific permissions for this user.",
                                related_name="user_set",
                                related_query_name="user",
                                to="auth.permission",
                                verbose_name="user permissions",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "DMIS user",
                        "verbose_name_plural": "DMIS users",
                        "db_table": '"user"',
                        "managed": False,
                    },
                    managers=[
                        ("objects", accounts.managers.DmisUserManager()),
                    ],
                ),
            ],
            database_operations=[],
        ),
    ]
