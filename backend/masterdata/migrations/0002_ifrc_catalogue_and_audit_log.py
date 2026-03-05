from django.db import migrations, models
import django.utils.timezone


def _create_postgres_fts_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ifrc_catalogue_desc_fts
        ON ifrc_catalogue_item
        USING gin(to_tsvector('english', description));
        """
    )


def _drop_postgres_fts_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP INDEX IF EXISTS idx_ifrc_catalogue_desc_fts;")


class Migration(migrations.Migration):
    dependencies = [
        ("masterdata", "0001_item_code_varchar_30"),
    ]

    operations = [
        migrations.CreateModel(
            name="IfrcCatalogueItem",
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
                (
                    "ifrc_code",
                    models.CharField(
                        db_index=True,
                        help_text="IFRC item code (uppercase).",
                        max_length=30,
                    ),
                ),
                (
                    "description",
                    models.CharField(
                        help_text="Official IFRC item description.",
                        max_length=120,
                    ),
                ),
                (
                    "category",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Optional IFRC category label.",
                        max_length=60,
                    ),
                ),
                (
                    "source_url",
                    models.URLField(
                        blank=True,
                        default="",
                        help_text="Catalogue source URL.",
                        max_length=255,
                    ),
                ),
                (
                    "synced_at",
                    models.DateTimeField(
                        db_index=True,
                        default=django.utils.timezone.now,
                        help_text="Timestamp when this entry was synced.",
                    ),
                ),
            ],
            options={
                "verbose_name": "IFRC Catalogue Item",
                "verbose_name_plural": "IFRC Catalogue Items",
                "db_table": "ifrc_catalogue_item",
            },
        ),
        migrations.CreateModel(
            name="ItemIfrcSuggestLog",
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
                (
                    "item_name_input",
                    models.CharField(
                        help_text="Raw user input used for IFRC suggestion.",
                        max_length=120,
                    ),
                ),
                (
                    "suggested_code",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Suggested IFRC code returned by the assistant.",
                        max_length=30,
                    ),
                ),
                (
                    "suggested_desc",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Suggested IFRC description returned by the assistant.",
                        max_length=120,
                    ),
                ),
                (
                    "confidence",
                    models.DecimalField(
                        blank=True,
                        decimal_places=3,
                        help_text="Confidence score between 0.000 and 1.000.",
                        max_digits=4,
                        null=True,
                    ),
                ),
                (
                    "match_type",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("exact", "Exact"),
                            ("close", "Close"),
                            ("uncertain", "Uncertain"),
                            ("fallback", "Fallback"),
                            ("none", "No Match"),
                        ],
                        default="",
                        help_text="Match classification for the suggestion.",
                        max_length=20,
                    ),
                ),
                (
                    "rationale",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text=(
                            "Short reasoning string returned by the suggestion pipeline."
                        ),
                        max_length=200,
                    ),
                ),
                (
                    "llm_used",
                    models.BooleanField(
                        default=False,
                        help_text="Whether an LLM decision step was used.",
                    ),
                ),
                (
                    "selected_code",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Item code the user actually saved.",
                        max_length=30,
                    ),
                ),
                (
                    "user_id",
                    models.CharField(
                        db_index=True,
                        help_text=(
                            "Authenticated user id associated with the suggestion request."
                        ),
                        max_length=50,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        db_index=True,
                        help_text="Timestamp when the suggestion was created.",
                    ),
                ),
            ],
            options={
                "verbose_name": "IFRC Suggest Log",
                "verbose_name_plural": "IFRC Suggest Logs",
                "db_table": "item_ifrc_suggest_log",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="ifrccatalogueitem",
            constraint=models.UniqueConstraint(
                fields=("ifrc_code", "description"),
                name="uq_ifrc_catalogue_code_desc",
            ),
        ),
        migrations.RunPython(_create_postgres_fts_index, _drop_postgres_fts_index),
    ]
