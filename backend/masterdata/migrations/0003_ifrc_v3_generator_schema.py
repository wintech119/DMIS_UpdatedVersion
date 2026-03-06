from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("masterdata", "0002_ifrc_catalogue_and_audit_log"),
    ]

    operations = [
        migrations.DeleteModel(
            name="IfrcCatalogueItem",
        ),
        migrations.RenameField(
            model_name="itemifrcsuggestlog",
            old_name="rationale",
            new_name="construction_rationale",
        ),
        migrations.AlterField(
            model_name="itemifrcsuggestlog",
            name="construction_rationale",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.RemoveField(
            model_name="itemifrcsuggestlog",
            name="llm_used",
        ),
        migrations.AlterField(
            model_name="itemifrcsuggestlog",
            name="match_type",
            field=models.CharField(
                blank=False,
                choices=[
                    ("generated", "Generated (code constructed)"),
                    ("fallback", "Fallback (rule-based, LLM unavailable)"),
                    ("none", "No code generated"),
                ],
                default="none",
                max_length=20,
            ),
        ),
    ]

