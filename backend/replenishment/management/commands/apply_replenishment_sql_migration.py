from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from replenishment.sql_migration_templates import (
    SUPPORTED_SQL_TEMPLATE_NAMES,
    render_sql_template,
    schema_name,
    sql_template_path,
)


class Command(BaseCommand):
    help = (
        "Render and optionally apply a replenishment SQL migration template "
        "for the configured DMIS schema."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "template_name",
            choices=SUPPORTED_SQL_TEMPLATE_NAMES,
            help="Name of the SQL template in replenishment/migrations.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Execute the rendered SQL (default is dry-run output only).",
        )

    def handle(self, *args, **options):
        template_name = str(options["template_name"])
        apply_changes = bool(options.get("apply"))
        schema = schema_name()
        rendered_sql = render_sql_template(template_name, schema)

        self.stdout.write("Replenishment SQL migration:")
        self.stdout.write(f"Schema: {schema}")
        self.stdout.write(f"Template: {sql_template_path(template_name)}")

        if not apply_changes:
            preview = " ".join(rendered_sql.strip().split())
            self.stdout.write("Dry-run only. Re-run with --apply to execute SQL.")
            self.stdout.write(preview[:220])
            return

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(rendered_sql)

        self.stdout.write(
            self.style.SUCCESS(f"Applied replenishment SQL template: {template_name}")
        )
