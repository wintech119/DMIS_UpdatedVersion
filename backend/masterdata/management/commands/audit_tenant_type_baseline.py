from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection

from masterdata.services.data_access import BASELINE_TENANT_TYPE_CODES, _schema_name


_MLSS_TERMS = (
    "MLSS",
    "MINISTRY_OF_LABOUR",
    "LABOUR_AND_SOCIAL_SECURITY",
    "SOCIAL_SECURITY",
)
_NGO_TERMS = (
    "NGO",
    "NON_GOVERNMENT",
    "RED_CROSS",
    "JRC",
    "SALVATION",
    "FOOD_FOR_THE_POOR",
    "HUMANITARIAN",
)


def _normalized(value: object) -> str:
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text


def _haystack(*values: object) -> str:
    return " ".join(_normalized(value) for value in values if str(value or "").strip())


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _map_tenant_type(row: dict[str, Any]) -> tuple[str, str, str]:
    current = _normalized(row.get("old_tenant_type"))
    context = _haystack(row.get("tenant_code"), row.get("tenant_name"))

    if current in BASELINE_TENANT_TYPE_CODES:
        return current, "baseline", "Already on approved baseline tenant type."
    if current in {"NEOC", "NATIONAL_LEVEL"}:
        return "NATIONAL", "high", "Legacy national/NEOC type maps to NATIONAL."
    if current == "INFRASTRUCTURE":
        return "UTILITY", "high", "Legacy infrastructure type maps to UTILITY."
    if current == "SHELTER":
        return "SHELTER_OPERATOR", "high", "Legacy shelter type maps to SHELTER_OPERATOR."
    if current in {"AGENCY", "OTHER", "PUBLIC"}:
        return "PARTNER", "high", "Legacy agency/other/public tenant type maps to PARTNER."
    if current == "MINISTRY":
        if _contains_any(context, _MLSS_TERMS):
            return "SOCIAL_SERVICES", "high", "MLSS ministry row maps to SOCIAL_SERVICES."
        return "PARTNER", "medium", "Non-MLSS ministry row maps to PARTNER; review if this is social services."
    if current == "EXTERNAL":
        if _contains_any(context, _NGO_TERMS):
            return "NGO", "medium", "External row has NGO indicator in code/name."
        return "PARTNER", "medium", "External row has no NGO indicator; review partner classification."
    return "PARTNER", "low", "Unrecognized non-baseline tenant type; manual review recommended."


class Command(BaseCommand):
    help = "Audit tenant rows against the approved baseline ref_tenant_type taxonomy."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--csv-out",
            type=str,
            default="",
            help="Optional path for the CSV review. Defaults to stdout.",
        )
        parser.add_argument(
            "--include-baseline",
            action="store_true",
            help="Include tenants already using one of the approved baseline types.",
        )

    def handle(self, *args, **options):
        schema = _schema_name()
        schema_sql = connection.ops.quote_name(schema)
        include_baseline = bool(options.get("include_baseline"))
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        tenant_id,
                        tenant_code,
                        tenant_name,
                        tenant_type
                    FROM {schema_sql}.tenant
                    ORDER BY tenant_id
                    """
                )
                rows = [
                    {
                        "tenant_id": row[0],
                        "tenant_code": row[1],
                        "tenant_name": row[2],
                        "old_tenant_type": row[3],
                    }
                    for row in cursor.fetchall()
                ]
        except DatabaseError as exc:
            raise CommandError("Unable to read tenant rows for tenant-type audit.") from exc

        review_rows: list[dict[str, Any]] = []
        for row in rows:
            mapped_type, confidence, notes = _map_tenant_type(row)
            old_type = _normalized(row["old_tenant_type"])
            if not include_baseline and old_type in BASELINE_TENANT_TYPE_CODES:
                continue
            review_rows.append(
                {
                    "tenant_id": row["tenant_id"],
                    "tenant_code": row["tenant_code"],
                    "tenant_name": row["tenant_name"],
                    "old_tenant_type": row["old_tenant_type"],
                    "mapped_tenant_type": mapped_type,
                    "confidence": confidence,
                    "notes": notes,
                }
            )

        fieldnames = [
            "tenant_id",
            "tenant_code",
            "tenant_name",
            "old_tenant_type",
            "mapped_tenant_type",
            "confidence",
            "notes",
        ]
        output_path = str(options.get("csv_out") or "").strip()
        if output_path:
            path = Path(output_path)
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(review_rows)
            self.stdout.write(self.style.SUCCESS(f"Wrote {len(review_rows)} tenant-type review rows to {path}."))
            return

        writer = csv.DictWriter(self.stdout, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)
