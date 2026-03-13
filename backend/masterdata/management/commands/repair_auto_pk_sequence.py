from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from masterdata.services.data_access import (
    TABLE_REGISTRY,
    inspect_auto_pk_sequence,
    resync_auto_pk_sequence,
)


class Command(BaseCommand):
    help = "Inspect or repair PostgreSQL sequence drift for masterdata auto-PK tables."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "table_key",
            nargs="?",
            default="items",
            choices=sorted(TABLE_REGISTRY.keys()),
            help="Registered masterdata table key to inspect or repair. Defaults to items.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply sequence repair so the next insert uses MAX(pk) + 1.",
        )

    def handle(self, *args, **options):
        table_key = str(options["table_key"])
        apply_repair = bool(options.get("apply"))

        info, warnings = inspect_auto_pk_sequence(table_key)
        if info is None:
            raise CommandError(
                f"Unable to inspect auto-PK sequence for {table_key}: {', '.join(warnings) or 'unknown error'}"
            )

        self.stdout.write(f"Table key: {table_key}")
        self.stdout.write(f"Schema: {info['schema']}")
        self.stdout.write(f"Table: {info['table_name']}")
        self.stdout.write(f"PK field: {info['pk_field']}")
        self.stdout.write(f"Sequence: {info['sequence_name']}")
        self.stdout.write(f"Max PK: {info['max_pk']}")
        self.stdout.write(f"Sequence last_value: {info['last_value']}")
        self.stdout.write(f"Sequence is_called: {info['is_called']}")
        self.stdout.write(f"Next sequence value: {info['next_value']}")

        if warnings:
            self.stdout.write(f"Warnings: {', '.join(warnings)}")

        if not apply_repair:
            return

        success, repaired_info, repair_warnings = resync_auto_pk_sequence(table_key)
        if not success or repaired_info is None:
            raise CommandError(
                f"Unable to repair auto-PK sequence for {table_key}: {', '.join(repair_warnings) or 'unknown error'}"
            )

        self.stdout.write(self.style.SUCCESS("Sequence repaired."))
        self.stdout.write(f"Applied value: {repaired_info['last_value']}")
        self.stdout.write(f"Next insert value: {repaired_info['next_value']}")
        if repair_warnings:
            self.stdout.write(f"Warnings: {', '.join(repair_warnings)}")
