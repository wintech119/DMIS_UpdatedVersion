"""
Management command: reload_ifrc_taxonomy
Clears the in-memory taxonomy cache and re-parses the MD file.
Run this after updating masterdata/data/ifrc_catalogue_taxonomy.md on a live server.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Reload the IFRC taxonomy from ifrc_catalogue_taxonomy.md without restarting the server"

    def handle(self, *args, **options):
        from masterdata.ifrc_catalogue_loader import reload_taxonomy

        self.stdout.write("Reloading IFRC taxonomy...")
        taxonomy = reload_taxonomy()
        self.stdout.write(
            self.style.SUCCESS(
                f"Taxonomy reloaded: "
                f"{len(taxonomy.groups)} groups, "
                f"{sum(len(g.families) for g in taxonomy.groups.values())} families, "
                f"{sum(len(f.items) for g in taxonomy.groups.values() for f in g.families.values())} items."
            )
        )
