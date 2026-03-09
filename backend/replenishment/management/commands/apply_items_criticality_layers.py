from django.core.management.base import BaseCommand
from django.db import connection, transaction

from replenishment.sql_migration_templates import (
    render_sql_template,
    schema_name,
    sql_template_path,
)


_SQL_TEMPLATE_NAME = "20260308_items_criticality_layers.sql"


class Command(BaseCommand):
    help = (
        "Render and optionally apply the item criticality governance SQL "
        "template for the configured DMIS schema."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Execute the rendered SQL (default is dry-run output only).",
        )

    def handle(self, *args, **options):
        apply_changes = bool(options.get("apply"))
        schema = schema_name()
        rendered_sql = render_sql_template(_SQL_TEMPLATE_NAME, schema)

        self.stdout.write("Item criticality governance migration:")
        self.stdout.write(f"Schema: {schema}")
        self.stdout.write(f"Template: {sql_template_path(_SQL_TEMPLATE_NAME)}")

        if not apply_changes:
            preview = " ".join(rendered_sql.strip().split())
            self.stdout.write("Dry-run only. Re-run with --apply to execute SQL.")
            self.stdout.write(preview[:220])
            return

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(rendered_sql)

        self.stdout.write(
            self.style.SUCCESS("Applied item criticality governance SQL.")
        )
