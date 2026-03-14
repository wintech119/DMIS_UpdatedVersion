from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from masterdata.item_master_taxonomy import (
    build_ifrc_taxonomy_seed_payload,
    resolve_schema_name,
    sync_item_master_taxonomy,
)


class Command(BaseCommand):
    help = (
        "Synchronize governed Level 1 categories and IFRC family/reference seed "
        "data for the unified item master."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview the deterministic seed counts without writing to the database.",
        )

    def handle(self, *args, **options):
        schema = resolve_schema_name()
        if bool(options.get("dry_run")):
            payload = build_ifrc_taxonomy_seed_payload()
            self.stdout.write("Item master taxonomy sync dry-run:")
            self.stdout.write(f"Schema: {schema}")
            self.stdout.write(f"Level 1 categories: {len(payload['categories'])}")
            self.stdout.write(f"IFRC families: {len(payload['families'])}")
            self.stdout.write(f"IFRC item references: {len(payload['references'])}")
            return

        with transaction.atomic():
            summary = sync_item_master_taxonomy(connection, schema=schema)

        self.stdout.write(self.style.SUCCESS("Unified item master taxonomy synchronized."))
        self.stdout.write(f"Schema: {schema}")
        self.stdout.write(f"Level 1 categories: {summary['categories']}")
        self.stdout.write(f"IFRC families: {summary['families']}")
        self.stdout.write(f"IFRC item references: {summary['references']}")
