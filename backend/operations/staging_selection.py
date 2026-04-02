from __future__ import annotations

from dataclasses import dataclass

from django.db import connection

from operations import policy as operations_policy
from operations.constants import (
    STAGING_SELECTION_BASIS_PROXIMITY_MATRIX,
    STAGING_SELECTION_BASIS_SAME_PARISH,
)


@dataclass(frozen=True)
class StagingRecommendation:
    recommended_staging_warehouse_id: int | None
    staging_selection_basis: str | None
    recommended_staging_warehouse_name: str | None = None
    recommended_staging_parish_code: str | None = None


def _fetch_rows(sql: str, params: list[object]) -> list[dict[str, object]]:
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            columns = [column[0] for column in cursor.description or ()]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception:
        return []


def _staging_hub_rows(*, odpem_tenant_id: int) -> list[dict[str, object]]:
    return _fetch_rows(
        """
        SELECT warehouse_id, warehouse_name, parish_code
        FROM warehouse
        WHERE tenant_id = %s
          AND UPPER(COALESCE(warehouse_type, '')) = 'SUB-HUB'
          AND COALESCE(status_code, 'A') = 'A'
        ORDER BY warehouse_name, warehouse_id
        """,
        [int(odpem_tenant_id)],
    )


def beneficiary_parish_code_for_request(reliefrqst_id: int) -> str | None:
    rows = _fetch_rows(
        """
        SELECT a.parish_code
        FROM reliefrqst r
        LEFT JOIN agency a ON a.agency_id = r.agency_id
        WHERE r.reliefrqst_id = %s
        LIMIT 1
        """,
        [int(reliefrqst_id)],
    )
    if not rows:
        return None
    parish_code = str(rows[0].get("parish_code") or "").strip()
    return parish_code or None


def get_staging_hub_details(warehouse_id: int) -> dict[str, object] | None:
    odpem_tenant_id = operations_policy.resolve_odpem_tenant_id()
    if odpem_tenant_id is None:
        return None
    rows = _fetch_rows(
        """
        SELECT warehouse_id, warehouse_name, parish_code
        FROM warehouse
        WHERE warehouse_id = %s
          AND tenant_id = %s
          AND UPPER(COALESCE(warehouse_type, '')) = 'SUB-HUB'
          AND COALESCE(status_code, 'A') = 'A'
        LIMIT 1
        """,
        [int(warehouse_id), int(odpem_tenant_id)],
    )
    return rows[0] if rows else None


def recommend_staging_hub(*, beneficiary_parish_code: str | None) -> StagingRecommendation:
    odpem_tenant_id = operations_policy.resolve_odpem_tenant_id()
    if odpem_tenant_id is None:
        return StagingRecommendation(None, None)

    candidates = _staging_hub_rows(odpem_tenant_id=int(odpem_tenant_id))
    if not candidates:
        return StagingRecommendation(None, None)

    target_parish_code = str(beneficiary_parish_code or "").strip()
    if target_parish_code:
        for candidate in candidates:
            if str(candidate.get("parish_code") or "").strip() == target_parish_code:
                return StagingRecommendation(
                    recommended_staging_warehouse_id=int(candidate["warehouse_id"]),
                    staging_selection_basis=STAGING_SELECTION_BASIS_SAME_PARISH,
                    recommended_staging_warehouse_name=str(candidate.get("warehouse_name") or "").strip() or None,
                    recommended_staging_parish_code=target_parish_code,
                )

        proximity_rows = _fetch_rows(
            """
            SELECT candidate_parish_code, proximity_rank
            FROM parish_proximity_matrix
            WHERE source_parish_code = %s
            ORDER BY proximity_rank ASC, candidate_parish_code ASC
            """,
            [target_parish_code],
        )
        ranked_parishes = [str(row["candidate_parish_code"]) for row in proximity_rows]
        if ranked_parishes:
            rank_lookup = {parish_code: index for index, parish_code in enumerate(ranked_parishes)}
            ranked_candidates = sorted(
                candidates,
                key=lambda row: (
                    rank_lookup.get(str(row.get("parish_code") or "").strip(), len(rank_lookup) + 1),
                    str(row.get("warehouse_name") or ""),
                    int(row["warehouse_id"]),
                ),
            )
            best = ranked_candidates[0]
            return StagingRecommendation(
                recommended_staging_warehouse_id=int(best["warehouse_id"]),
                staging_selection_basis=STAGING_SELECTION_BASIS_PROXIMITY_MATRIX,
                recommended_staging_warehouse_name=str(best.get("warehouse_name") or "").strip() or None,
                recommended_staging_parish_code=str(best.get("parish_code") or "").strip() or None,
            )

    best = candidates[0]
    return StagingRecommendation(
        recommended_staging_warehouse_id=int(best["warehouse_id"]),
        staging_selection_basis=STAGING_SELECTION_BASIS_PROXIMITY_MATRIX,
        recommended_staging_warehouse_name=str(best.get("warehouse_name") or "").strip() or None,
        recommended_staging_parish_code=str(best.get("parish_code") or "").strip() or None,
    )
