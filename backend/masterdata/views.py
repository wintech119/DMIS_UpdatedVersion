"""
Generic API views for master data CRUD.

All endpoints are parameterized by ``table_key`` which maps to a
``TableConfig`` in the registry.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError, connection
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from api.authentication import LegacyCompatAuthentication
from masterdata.ifrc_code_agent import IFRCCodeSuggestion, IFRCAgent, cb_is_open
from masterdata.models import ItemIfrcSuggestLog
from masterdata.permissions import (
    MasterDataPermission,
    PERM_MASTERDATA_CREATE,
    PERM_MASTERDATA_EDIT,
    PERM_MASTERDATA_INACTIVATE,
    PERM_MASTERDATA_VIEW,
)
from masterdata.serializers import IFRCSuggestionResponseSerializer
from masterdata.services.data_access import (
    INACTIVE_ITEM_FORWARD_WRITE_CODE,
    TABLE_REGISTRY,
    _safe_rollback,
    _schema_name,
    activate_record,
    check_dependencies,
    create_record,
    get_lookup,
    get_record,
    get_summary_counts,
    get_table_config,
    inactivate_record,
    list_records,
    update_record,
)
from masterdata.services.catalog_governance import (
    activate_catalog_record,
    catalog_detail_metadata,
    create_catalog_record,
    create_catalog_replacement,
    inactivate_catalog_record,
    is_governed_catalog_table,
    suggest_ifrc_family_authoring,
    suggest_ifrc_reference_authoring,
    update_catalog_record,
    validate_catalog_update,
)
from masterdata.services.item_master import (
    create_item_record,
    find_item_canonical_conflict,
    get_item_record,
    list_item_category_lookup,
    list_ifrc_family_lookup,
    list_ifrc_reference_lookup,
    list_item_records,
    update_item_record,
    validate_item_payload,
)
from masterdata.services.validation import validate_record

logger = logging.getLogger(__name__)

DEFAULT_PAGE_LIMIT = 100
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 500
_SAFE_INPUT_RE = re.compile(r"[^a-zA-Z0-9\s\-\'\(\)/]")
_IFRC_AGENT_SINGLETON: IFRCAgent | None = None
_IFRC_RESOLVED_CANDIDATE_MIN = 0.55
_IFRC_PLAUSIBLE_CANDIDATE_MIN = 0.35
_IFRC_RESPONSE_CANDIDATE_LIMIT = 5


def _actor_id(request) -> str:
    return str(getattr(request.user, "user_id", "system"))


def _validate_table_key(table_key: str):
    cfg = get_table_config(table_key)
    if cfg is None:
        return None, Response({"detail": f"Unknown table: {table_key}"}, status=404)
    return cfg, None


def _ifrc_cfg() -> dict[str, Any]:
    cfg = getattr(settings, "IFRC_AGENT", {})
    return {
        "IFRC_ENABLED": bool(cfg.get("IFRC_ENABLED", True)),
        "MIN_INPUT_LENGTH": int(cfg.get("MIN_INPUT_LENGTH", 3)),
        "MAX_INPUT_LENGTH": int(cfg.get("MAX_INPUT_LENGTH", 120)),
        "RATE_LIMIT_PER_MINUTE": int(cfg.get("RATE_LIMIT_PER_MINUTE", 30)),
        "AUTO_FILL_CONFIDENCE_THRESHOLD": float(cfg.get("AUTO_FILL_CONFIDENCE_THRESHOLD", 0.85)),
        "OLLAMA_MODEL_ID": str(cfg.get("OLLAMA_MODEL_ID", "qwen3.5:0.8b")),
        "LLM_ENABLED": bool(cfg.get("LLM_ENABLED", False)),
    }


def _item_validation_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = dict(data)
    payload.pop("item_code", None)
    payload.pop("legacy_item_code", None)
    return payload


def _item_conflict_response(conflict: dict[str, Any]):
    return Response(
        {
            "detail": "An item already exists for the selected IFRC reference.",
            "errors": {
                conflict["code"]: conflict,
            },
        },
        status=409,
    )


def _inactive_item_guard_response(warnings: list[str], fallback_table: str):
    if INACTIVE_ITEM_FORWARD_WRITE_CODE not in warnings:
        return None

    item_ids: list[int] = []
    table_key = fallback_table
    workflow_state = "UNKNOWN"
    for warning in warnings:
        if warning.startswith("inactive_item_id_"):
            raw_id = warning.removeprefix("inactive_item_id_")
            try:
                item_ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue
        elif warning.startswith("forward_write_table_"):
            table_key = warning.removeprefix("forward_write_table_") or fallback_table
        elif warning.startswith("forward_write_workflow_"):
            workflow_state = warning.removeprefix("forward_write_workflow_") or "UNKNOWN"

    payload = {
        "code": INACTIVE_ITEM_FORWARD_WRITE_CODE,
        "table": table_key,
        "workflow_state": workflow_state,
        "item_ids": sorted(set(item_ids)),
    }
    return Response(
        {"detail": "Cannot write forward-looking data for inactive item(s).", "errors": {INACTIVE_ITEM_FORWARD_WRITE_CODE: payload}},
        status=409,
    )


def _ifrc_agent() -> IFRCAgent:
    global _IFRC_AGENT_SINGLETON
    if _IFRC_AGENT_SINGLETON is None:
        _IFRC_AGENT_SINGLETON = IFRCAgent()
    return _IFRC_AGENT_SINGLETON


def _ifrc_rate_limit_key(user_id: str) -> str:
    return f"ifrc:rate:{user_id}:{int(time.time() // 60)}"


def _allow_ifrc_request(user_id: str, per_minute: int) -> bool:
    key = _ifrc_rate_limit_key(user_id)
    if cache.add(key, 1, timeout=70):
        return True
    try:
        current = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=70)
        current = 1
    return int(current) <= int(per_minute)



def _tokenize_ifrc_terms(*parts: Any) -> set[str]:
    tokens: set[str] = set()
    for part in parts:
        for token in re.findall(r"[A-Z0-9]{2,}", str(part or "").upper()):
            tokens.add(token)
    return tokens


def _spec_from_ifrc_code(
    ifrc_code: str | None,
    *,
    group_code: str | None,
    family_code: str | None,
    category_code: str | None,
) -> str:
    normalized = str(ifrc_code or "").strip().upper()
    prefix_len = len(f"{group_code or ''}{family_code or ''}{category_code or ''}")
    if len(normalized) <= prefix_len + 2:
        return ""
    return normalized[prefix_len:-2]


def _build_ifrc_search_keys(suggestion: IFRCCodeSuggestion) -> list[dict[str, Any]]:
    raw_keys: list[dict[str, Any]] = [
        {
            "source": "primary",
            "group_code": str(suggestion.grp or "").upper(),
            "family_code": str(suggestion.fam or "").upper(),
            "category_code": str(suggestion.cat or "").upper(),
            "ifrc_code": str(suggestion.item_code or "").upper(),
            "spec_segment": str(suggestion.spec_seg or "").upper(),
        }
    ]
    for alternative in suggestion.alternatives or []:
        group_code = str(alternative.get("grp") or "").upper()
        family_code = str(alternative.get("fam") or "").upper()
        category_code = str(alternative.get("cat") or "").upper()
        ifrc_code = str(alternative.get("item_code") or "").upper()
        spec_segment = str(alternative.get("spec_seg") or "").upper()
        if not spec_segment:
            spec_segment = _spec_from_ifrc_code(
                ifrc_code,
                group_code=group_code,
                family_code=family_code,
                category_code=category_code,
            )
        raw_keys.append(
            {
                "source": "alternative",
                "group_code": group_code,
                "family_code": family_code,
                "category_code": category_code,
                "ifrc_code": ifrc_code,
                "spec_segment": spec_segment,
            }
        )

    search_keys: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for entry in raw_keys:
        dedupe_key = (
            str(entry["group_code"]),
            str(entry["family_code"]),
            str(entry["category_code"]),
            str(entry["ifrc_code"]),
            str(entry["spec_segment"]),
        )
        if not all(dedupe_key[:3]) or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        search_keys.append(entry)
    return search_keys


def _candidate_dict_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "ifrc_item_ref_id": int(row[0]),
        "ifrc_family_id": int(row[1]),
        "ifrc_code": str(row[2] or ""),
        "reference_desc": str(row[3] or ""),
        "category_code": str(row[4] or ""),
        "category_label": str(row[5] or ""),
        "spec_segment": str(row[6] or ""),
        "size_weight": str(row[7] or ""),
        "form": str(row[8] or ""),
        "material": str(row[9] or ""),
        "group_code": str(row[10] or ""),
        "group_label": str(row[11] or ""),
        "family_code": str(row[12] or ""),
        "family_label": str(row[13] or ""),
    }


def _fetch_ifrc_family_id(schema: str, group_code: str, family_code: str) -> int | None:
    if not group_code or not family_code:
        return None
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT ifrc_family_id
            FROM {schema}.ifrc_family
            WHERE group_code = %s
              AND family_code = %s
              AND status_code = 'A'
            LIMIT 1
            """,
            [group_code, family_code],
        )
        row = cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _fetch_ifrc_reference_by_code(
    schema: str,
    ifrc_code: str,
    *,
    active_only: bool | None,
) -> dict[str, Any] | None:
    if not ifrc_code:
        return None

    status_filter = ""
    if active_only is True:
        status_filter = "AND r.status_code = 'A' AND f.status_code = 'A'"
    elif active_only is False:
        status_filter = "AND (r.status_code <> 'A' OR f.status_code <> 'A')"

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                r.ifrc_item_ref_id,
                r.ifrc_family_id,
                r.ifrc_code,
                r.reference_desc,
                r.category_code,
                r.category_label,
                COALESCE(r.spec_segment, ''),
                COALESCE(r.size_weight, ''),
                COALESCE(r.form, ''),
                COALESCE(r.material, ''),
                f.group_code,
                f.group_label,
                f.family_code,
                f.family_label
            FROM {schema}.ifrc_item_reference r
            JOIN {schema}.ifrc_family f
              ON f.ifrc_family_id = r.ifrc_family_id
            WHERE r.ifrc_code = %s
              {status_filter}
            LIMIT 1
            """,
            [ifrc_code],
        )
        row = cursor.fetchone()
    return _candidate_dict_from_row(row) if row else None


def _load_ifrc_reference_candidates(
    schema: str,
    search_keys: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates_by_id: dict[int, dict[str, Any]] = {}
    with connection.cursor() as cursor:
        for search_key in search_keys:
            cursor.execute(
                f"""
                SELECT
                    r.ifrc_item_ref_id,
                    r.ifrc_family_id,
                    r.ifrc_code,
                    r.reference_desc,
                    r.category_code,
                    r.category_label,
                    COALESCE(r.spec_segment, ''),
                    COALESCE(r.size_weight, ''),
                    COALESCE(r.form, ''),
                    COALESCE(r.material, ''),
                    f.group_code,
                    f.group_label,
                    f.family_code,
                    f.family_label
                FROM {schema}.ifrc_item_reference r
                JOIN {schema}.ifrc_family f
                  ON f.ifrc_family_id = r.ifrc_family_id
                WHERE r.status_code = 'A'
                  AND f.status_code = 'A'
                  AND f.group_code = %s
                  AND f.family_code = %s
                  AND r.category_code = %s
                ORDER BY r.reference_desc, r.ifrc_code
                """,
                [
                    search_key["group_code"],
                    search_key["family_code"],
                    search_key["category_code"],
                ],
            )
            for row in cursor.fetchall():
                candidate = _candidate_dict_from_row(row)
                candidates_by_id[candidate["ifrc_item_ref_id"]] = candidate
    return list(candidates_by_id.values())


def _score_ifrc_candidate(
    candidate: dict[str, Any],
    search_key: dict[str, Any],
    *,
    item_tokens: set[str],
    size_tokens: set[str],
    form_tokens: set[str],
    material_tokens: set[str],
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    candidate_code = str(candidate.get("ifrc_code") or "").upper()
    candidate_spec = str(candidate.get("spec_segment") or "").upper()
    generated_code = str(search_key.get("ifrc_code") or "").upper()
    generated_spec = str(search_key.get("spec_segment") or "").upper()

    if search_key.get("source") == "primary":
        score += 0.15
        reasons.append("primary_classification")
    else:
        score += 0.05
        reasons.append("alternative_classification")

    if generated_code and candidate_code == generated_code:
        score += 0.70 if search_key.get("source") == "primary" else 0.60
        reasons.append("exact_generated_code_match")
    elif generated_code and len(generated_code) > 2 and candidate_code.startswith(generated_code[:-2]):
        score += 0.35
        reasons.append("generated_prefix_match")

    if generated_spec and candidate_spec == generated_spec:
        score += 0.25
        reasons.append("exact_spec_match")
    elif generated_spec and candidate_spec and (
        candidate_spec.startswith(generated_spec) or generated_spec.startswith(candidate_spec)
    ):
        score += 0.15
        reasons.append("partial_spec_match")

    candidate_tokens = _tokenize_ifrc_terms(
        candidate.get("reference_desc"),
        candidate.get("category_label"),
        candidate.get("family_label"),
        candidate.get("size_weight"),
        candidate.get("form"),
        candidate.get("material"),
        candidate_spec,
        candidate_code,
    )
    overlap = sorted(item_tokens & candidate_tokens)
    if overlap:
        score += min(0.20, 0.04 * len(overlap))
        reasons.append(f"desc_overlap:{','.join(overlap[:3])}")

    for tokens, label, bonus in (
        (size_tokens, "size_weight", 0.12),
        (form_tokens, "form", 0.10),
        (material_tokens, "material", 0.10),
    ):
        if tokens and tokens & candidate_tokens:
            score += bonus
            reasons.append(f"{label}_match")

    return min(score, 1.0), reasons


def _rank_ifrc_reference_candidates(
    candidate_rows: list[dict[str, Any]],
    search_keys: list[dict[str, Any]],
    *,
    item_name: str,
    ifrc_description: str,
    size_weight: str,
    form: str,
    material: str,
    auto_fill_threshold: float,
) -> list[dict[str, Any]]:
    item_tokens = _tokenize_ifrc_terms(item_name, ifrc_description)
    size_tokens = _tokenize_ifrc_terms(size_weight)
    form_tokens = _tokenize_ifrc_terms(form)
    material_tokens = _tokenize_ifrc_terms(material)

    ranked: list[dict[str, Any]] = []
    for candidate in candidate_rows:
        best_score = -1.0
        best_reasons: list[str] = []
        for search_key in search_keys:
            if (
                candidate.get("group_code") != search_key.get("group_code")
                or candidate.get("family_code") != search_key.get("family_code")
                or candidate.get("category_code") != search_key.get("category_code")
            ):
                continue
            score, reasons = _score_ifrc_candidate(
                candidate,
                search_key,
                item_tokens=item_tokens,
                size_tokens=size_tokens,
                form_tokens=form_tokens,
                material_tokens=material_tokens,
            )
            if score > best_score:
                best_score = score
                best_reasons = reasons
        if best_score < 0:
            continue
        ranked.append(
            {
                **candidate,
                "score": round(best_score, 2),
                "match_reasons": best_reasons,
            }
        )

    ranked.sort(key=lambda row: (-row["score"], row["reference_desc"], row["ifrc_code"]))
    for rank, candidate in enumerate(ranked, start=1):
        candidate["rank"] = rank
        candidate["auto_highlight"] = False

    if ranked and ranked[0]["score"] >= auto_fill_threshold:
        ranked[0]["auto_highlight"] = True
    return ranked


def _resolve_ifrc_suggestion(
    suggestion: IFRCCodeSuggestion,
    *,
    item_name: str,
    size_weight: str,
    form: str,
    material: str,
    auto_fill_threshold: float,
) -> dict[str, Any]:
    resolution_payload: dict[str, Any] = {
        "resolution_status": "unresolved",
        "resolution_explanation": "Generated suggestion did not resolve to an active governed IFRC reference.",
        "ifrc_family_id": None,
        "resolved_ifrc_item_ref_id": None,
        "candidate_count": 0,
        "auto_highlight_candidate_id": None,
        "direct_accept_allowed": False,
        "candidates": [],
    }

    if not any([suggestion.item_code, suggestion.grp, suggestion.fam, suggestion.cat]):
        return resolution_payload

    schema = _schema_name()
    search_keys = _build_ifrc_search_keys(suggestion)
    try:
        primary_family_id = _fetch_ifrc_family_id(
            schema,
            str(suggestion.grp or "").upper(),
            str(suggestion.fam or "").upper(),
        )
        exact_active = _fetch_ifrc_reference_by_code(
            schema,
            str(suggestion.item_code or "").upper(),
            active_only=True,
        )
        exact_inactive = None
        if exact_active is None and suggestion.item_code:
            exact_inactive = _fetch_ifrc_reference_by_code(
                schema,
                str(suggestion.item_code or "").upper(),
                active_only=False,
            )
        candidate_rows = _load_ifrc_reference_candidates(schema, search_keys) if search_keys else []
    except DatabaseError as exc:
        _safe_rollback()
        logger.warning(
            "IFRC reference resolution lookup failed for code %s: %s",
            suggestion.item_code,
            exc,
        )
        resolution_payload["resolution_explanation"] = (
            "Active IFRC reference resolution failed; manual review is required."
        )
        return resolution_payload

    if exact_active is not None:
        exact_candidate = {
            **exact_active,
            "rank": 1,
            "score": 1.0,
            "auto_highlight": bool(suggestion.confidence >= auto_fill_threshold),
            "match_reasons": ["exact_generated_code_match"],
        }
        return {
            "resolution_status": "resolved",
            "resolution_explanation": (
                "Generated suggestion resolved to exactly one active governed IFRC reference."
            ),
            "ifrc_family_id": exact_candidate["ifrc_family_id"],
            "resolved_ifrc_item_ref_id": exact_candidate["ifrc_item_ref_id"],
            "candidate_count": 1,
            "auto_highlight_candidate_id": (
                exact_candidate["ifrc_item_ref_id"] if exact_candidate["auto_highlight"] else None
            ),
            "direct_accept_allowed": True,
            "candidates": [exact_candidate],
        }

    ranked_candidates = _rank_ifrc_reference_candidates(
        candidate_rows,
        search_keys,
        item_name=item_name,
        ifrc_description=str(suggestion.standardised_name or ""),
        size_weight=size_weight,
        form=form,
        material=material,
        auto_fill_threshold=auto_fill_threshold,
    )
    plausible_candidates = [
        candidate
        for candidate in ranked_candidates
        if candidate["score"] >= _IFRC_PLAUSIBLE_CANDIDATE_MIN
    ]

    if len(plausible_candidates) == 1 and plausible_candidates[0]["score"] >= _IFRC_RESOLVED_CANDIDATE_MIN:
        winner = plausible_candidates[0]
        return {
            "resolution_status": "resolved",
            "resolution_explanation": (
                "Generated suggestion resolved to exactly one active governed IFRC reference after ranking candidates."
            ),
            "ifrc_family_id": winner["ifrc_family_id"],
            "resolved_ifrc_item_ref_id": winner["ifrc_item_ref_id"],
            "candidate_count": 1,
            "auto_highlight_candidate_id": (
                winner["ifrc_item_ref_id"] if winner["auto_highlight"] else None
            ),
            "direct_accept_allowed": True,
            "candidates": [winner],
        }

    if plausible_candidates:
        visible_candidates = plausible_candidates[:_IFRC_RESPONSE_CANDIDATE_LIMIT]
        auto_highlight_candidate_id = next(
            (candidate["ifrc_item_ref_id"] for candidate in visible_candidates if candidate["auto_highlight"]),
            None,
        )
        return {
            "resolution_status": "ambiguous",
            "resolution_explanation": (
                "Multiple active governed IFRC references are plausible; explicit user selection is required."
            ),
            "ifrc_family_id": visible_candidates[0]["ifrc_family_id"],
            "resolved_ifrc_item_ref_id": None,
            "candidate_count": len(plausible_candidates),
            "auto_highlight_candidate_id": auto_highlight_candidate_id,
            "direct_accept_allowed": False,
            "candidates": visible_candidates,
        }

    resolution_payload["ifrc_family_id"] = primary_family_id
    if exact_inactive is not None:
        resolution_payload["resolution_explanation"] = (
            "Generated suggestion matched an inactive governed IFRC reference and cannot be accepted."
        )
    elif ranked_candidates:
        resolution_payload["resolution_explanation"] = (
            "Generated suggestion did not resolve strongly enough to a single active governed IFRC reference."
        )
    elif primary_family_id is not None:
        resolution_payload["resolution_explanation"] = (
            "No active governed IFRC item reference matched the generated classification."
        )
    return resolution_payload
# ---------------------------------------------------------------------------
# List + Create
# ---------------------------------------------------------------------------

@api_view(["GET", "POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def master_list_create(request, table_key: str):
    cfg, err = _validate_table_key(table_key)
    if err:
        return err

    if request.method == "GET":
        return _handle_list(request, cfg)
    return _handle_create(request, cfg)


master_list_create.required_permission = {
    "GET": PERM_MASTERDATA_VIEW,
    "POST": PERM_MASTERDATA_CREATE,
}


def _handle_list(request, cfg):
    if cfg.key == "items":
        return _handle_item_list(request)

    status_filter = request.query_params.get("status")
    search = request.query_params.get("search")
    order_by = request.query_params.get("order_by")
    try:
        limit = int(request.query_params.get("limit", DEFAULT_PAGE_LIMIT))
        limit = max(MIN_PAGE_LIMIT, min(limit, MAX_PAGE_LIMIT))
        offset = max(int(request.query_params.get("offset", 0)), 0)
    except (ValueError, TypeError):
        limit, offset = DEFAULT_PAGE_LIMIT, 0

    rows, total, warnings = list_records(
        cfg.key,
        status_filter=status_filter,
        search=search,
        order_by=order_by,
        limit=limit,
        offset=offset,
    )
    return Response({
        "results": rows,
        "count": total,
        "limit": limit,
        "offset": offset,
        "warnings": warnings,
    })


def _handle_create(request, cfg):
    if cfg.key == "items":
        return _handle_item_create(request, cfg)

    data = request.data or {}
    errors = validate_record(cfg, data, is_update=False)
    if errors:
        return Response({"errors": errors}, status=400)

    if is_governed_catalog_table(cfg.key):
        pk_val, warnings = create_catalog_record(cfg.key, data, _actor_id(request))
    else:
        pk_val, warnings = create_record(cfg.key, data, _actor_id(request))
    if pk_val is None:
        guard_response = _inactive_item_guard_response(warnings, cfg.key)
        if guard_response:
            return guard_response
        return Response(
            {"detail": "Failed to create record.", "warnings": warnings},
            status=500,
        )

    record, _ = get_record(cfg.key, pk_val)
    _link_ifrc_selection_if_present(
        request_data=data,
        actor_id=_actor_id(request),
        table_key=cfg.key,
        record=record,
        warnings=warnings,
    )
    payload = {"record": record, "warnings": warnings}
    payload.update(catalog_detail_metadata(cfg.key))
    return Response(payload, status=201)


def _handle_item_list(request):
    status_filter = request.query_params.get("status")
    search = request.query_params.get("search")
    order_by = request.query_params.get("order_by")
    category_id = request.query_params.get("category_id")
    ifrc_family_id = request.query_params.get("ifrc_family_id")
    ifrc_item_ref_id = request.query_params.get("ifrc_item_ref_id")
    try:
        limit = int(request.query_params.get("limit", DEFAULT_PAGE_LIMIT))
        limit = max(MIN_PAGE_LIMIT, min(limit, MAX_PAGE_LIMIT))
        offset = max(int(request.query_params.get("offset", 0)), 0)
    except (ValueError, TypeError):
        limit, offset = DEFAULT_PAGE_LIMIT, 0

    rows, total, warnings = list_item_records(
        status_filter=status_filter,
        search=search,
        order_by=order_by,
        category_id=category_id,
        ifrc_family_id=ifrc_family_id,
        ifrc_item_ref_id=ifrc_item_ref_id,
        limit=limit,
        offset=offset,
    )
    return Response({
        "results": rows,
        "count": total,
        "limit": limit,
        "offset": offset,
        "warnings": warnings,
    })


def _handle_item_create(request, cfg):
    data = request.data or {}
    errors = validate_record(cfg, _item_validation_payload(data), is_update=False)
    extra_errors, validation_warnings = validate_item_payload(
        data,
        is_update=False,
    )
    errors.update(extra_errors)
    if validation_warnings:
        return Response(
            {
                "detail": "Failed to validate item taxonomy.",
                "warnings": validation_warnings,
            },
            status=500,
        )
    if errors:
        return Response({"errors": errors}, status=400)

    conflict = find_item_canonical_conflict(data)
    if conflict is not None:
        return _item_conflict_response(conflict)

    pk_val, warnings = create_item_record(data, _actor_id(request))
    if pk_val is None:
        guard_response = _inactive_item_guard_response(warnings, cfg.key)
        if guard_response:
            return guard_response
        return Response(
            {"detail": "Failed to create record.", "warnings": warnings},
            status=500,
        )

    record, record_warnings = get_item_record(pk_val)
    warnings.extend(record_warnings)
    if record is None:
        return Response(
            {"detail": "Failed to load created item.", "warnings": warnings or ["db_error"]},
            status=500,
        )
    _link_ifrc_selection_if_present(
        request_data=data,
        actor_id=_actor_id(request),
        table_key=cfg.key,
        record=record,
        warnings=warnings,
    )
    return Response({"record": record, "warnings": warnings}, status=201)


# ---------------------------------------------------------------------------
# Detail + Update
# ---------------------------------------------------------------------------

@api_view(["GET", "PATCH"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def master_detail_update(request, table_key: str, pk: str):
    cfg, err = _validate_table_key(table_key)
    if err:
        return err

    pk_value = _coerce_pk(cfg, pk)

    if request.method == "GET":
        return _handle_detail(cfg, pk_value)
    return _handle_update(request, cfg, pk_value)


master_detail_update.required_permission = {
    "GET": PERM_MASTERDATA_VIEW,
    "PATCH": PERM_MASTERDATA_EDIT,
}


def _coerce_pk(cfg, pk_str: str) -> Any:
    pk_def = cfg._pk_def
    if pk_def and pk_def.db_type in ("int", "smallint"):
        try:
            return int(pk_str)
        except (ValueError, TypeError):
            pass
    return pk_str


def _handle_detail(cfg, pk_value):
    if cfg.key == "items":
        record, warnings = get_item_record(pk_value)
        if record is None:
            transient_warning = next(
                (
                    warning
                    for warning in warnings
                    if warning == "db_unavailable" or warning.startswith("transient")
                ),
                None,
            )
            if transient_warning is not None:
                return Response(
                    {
                        "detail": "Item detail lookup is temporarily unavailable.",
                        "diagnostic": (
                            "get_item_record returned no record and a transient read warning "
                            f"while loading item detail: {transient_warning}"
                        ),
                        "warnings": warnings,
                    },
                    status=503,
                )
            if "db_error" in warnings:
                return Response(
                    {
                        "detail": "Failed to load item detail.",
                        "diagnostic": (
                            "get_item_record returned no record and a database read warning "
                            "while loading item detail: db_error"
                        ),
                        "warnings": warnings,
                    },
                    status=500,
                )
            return Response({"detail": "Not found."}, status=404)
        return Response({"record": record, "warnings": warnings})

    record, warnings = get_record(cfg.key, pk_value)
    if record is None:
        return Response({"detail": "Not found."}, status=404)
    payload = {"record": record, "warnings": warnings}
    payload.update(catalog_detail_metadata(cfg.key))
    return Response(payload)


def _handle_update(request, cfg, pk_value):
    if cfg.key == "items":
        return _handle_item_update(request, cfg, pk_value)

    data = request.data or {}
    expected_version = data.pop("version_nbr", None)
    if expected_version is not None:
        try:
            expected_version = int(expected_version)
        except (ValueError, TypeError):
            expected_version = None

    existing_record = None
    if is_governed_catalog_table(cfg.key):
        existing_record, read_warnings = get_record(cfg.key, pk_value)
        if existing_record is None:
            if "db_error" in read_warnings:
                return Response(
                    {"detail": "Failed to load record for validation.", "warnings": read_warnings},
                    status=500,
                )
            return Response({"detail": "Not found."}, status=404)

    errors = validate_record(
        cfg,
        _item_validation_payload(data),
        is_update=True,
        current_pk=pk_value,
        existing_record=existing_record,
    )
    if existing_record is not None:
        locked_errors, locked_warnings = validate_catalog_update(cfg.key, data, existing_record)
        errors.update(locked_errors)
        if locked_warnings:
            return Response(
                {"detail": "Failed to validate governed catalog edit.", "warnings": locked_warnings},
                status=500,
            )
    if errors:
        return Response({"errors": errors}, status=400)

    if is_governed_catalog_table(cfg.key):
        success, warnings = update_catalog_record(
            cfg.key,
            pk_value,
            data,
            _actor_id(request),
            expected_version,
            existing_record=existing_record,
        )
    else:
        success, warnings = update_record(
            cfg.key, pk_value, data, _actor_id(request), expected_version,
        )
    if not success:
        guard_response = _inactive_item_guard_response(warnings, cfg.key)
        if guard_response:
            return guard_response
        if "version_conflict" in warnings:
            return Response(
                {"detail": "Record was modified by another user. Please reload.", "warnings": warnings},
                status=409,
            )
        if "not_found" in warnings:
            return Response({"detail": "Not found."}, status=404)
        return Response({"detail": "Update failed.", "warnings": warnings}, status=500)

    record, _ = get_record(cfg.key, pk_value)
    _link_ifrc_selection_if_present(
        request_data=data,
        actor_id=_actor_id(request),
        table_key=cfg.key,
        record=record,
        warnings=warnings,
    )
    payload = {"record": record, "warnings": warnings}
    payload.update(catalog_detail_metadata(cfg.key))
    return Response(payload)


def _handle_item_update(request, cfg, pk_value):
    data = request.data or {}
    expected_version = data.pop("version_nbr", None)
    if expected_version is not None:
        try:
            expected_version = int(expected_version)
        except (ValueError, TypeError):
            expected_version = None

    existing_record, read_warnings = get_item_record(pk_value)
    if existing_record is None:
        if "db_error" in read_warnings:
            return Response(
                {"detail": "Failed to load record for validation.", "warnings": read_warnings},
                status=500,
            )
        return Response({"detail": "Not found."}, status=404)

    errors = validate_record(
        cfg,
        _item_validation_payload(data),
        is_update=True,
        current_pk=pk_value,
        existing_record=existing_record,
    )
    extra_errors, validation_warnings = validate_item_payload(
        data,
        is_update=True,
        existing_record=existing_record,
    )
    errors.update(extra_errors)
    if validation_warnings:
        return Response(
            {
                "detail": "Failed to validate item taxonomy.",
                "warnings": validation_warnings,
            },
            status=500,
        )
    if errors:
        return Response({"errors": errors}, status=400)

    conflict = find_item_canonical_conflict(data, existing_record=existing_record)
    if conflict is not None:
        return _item_conflict_response(conflict)

    success, warnings = update_item_record(
        pk_value,
        data,
        _actor_id(request),
        expected_version,
    )
    if not success:
        guard_response = _inactive_item_guard_response(warnings, cfg.key)
        if guard_response:
            return guard_response
        if "version_conflict" in warnings:
            return Response(
                {"detail": "Record was modified by another user. Please reload.", "warnings": warnings},
                status=409,
            )
        if "not_found" in warnings:
            return Response({"detail": "Not found."}, status=404)
        return Response({"detail": "Update failed.", "warnings": warnings}, status=500)

    record, record_warnings = get_item_record(pk_value)
    warnings.extend(record_warnings)
    if record is None:
        return Response(
            {"detail": "Failed to load updated item.", "warnings": warnings or ["db_error"]},
            status=500,
        )
    _link_ifrc_selection_if_present(
        request_data=data,
        actor_id=_actor_id(request),
        table_key=cfg.key,
        record=record,
        warnings=warnings,
    )
    return Response({"record": record, "warnings": warnings})


def _link_ifrc_selection_if_present(
    *,
    request_data: dict[str, Any],
    actor_id: str,
    table_key: str,
    record: dict[str, Any] | None,
    warnings: list[str],
) -> None:
    """
    If an item save includes `ifrc_suggest_log_id`, append a new audit row with
    the selected_code for traceability (ItemIfrcSuggestLog is append-only).
    """
    if table_key != "items" or not record:
        return

    suggestion_id = request_data.get("ifrc_suggest_log_id")
    if suggestion_id in (None, ""):
        return

    item_code = str(record.get("item_code") or "").strip().upper()
    if not item_code:
        return

    try:
        original = ItemIfrcSuggestLog.objects.filter(
            pk=suggestion_id,
            user_id=actor_id,
        ).first()
        if original is None:
            warnings.append("ifrc_log_not_linked")
            return

        ItemIfrcSuggestLog.objects.create(
            item_name_input=original.item_name_input,
            suggested_code=original.suggested_code,
            suggested_desc=original.suggested_desc,
            confidence=original.confidence,
            match_type=original.match_type,
            construction_rationale=original.construction_rationale,
            selected_code=item_code[:30],
            user_id=original.user_id,
        )
    except Exception as exc:
        logger.warning("Failed to link IFRC suggestion log %r: %s", suggestion_id, exc)
        warnings.append("ifrc_log_link_failed")


# ---------------------------------------------------------------------------
# Summary counts
# ---------------------------------------------------------------------------

@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def master_summary(request, table_key: str):
    cfg, err = _validate_table_key(table_key)
    if err:
        return err
    counts, warnings = get_summary_counts(cfg.key)
    return Response({"counts": counts, "warnings": warnings})


master_summary.required_permission = PERM_MASTERDATA_VIEW


# ---------------------------------------------------------------------------
# Lookup (FK dropdown data)
# ---------------------------------------------------------------------------

@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def master_lookup(request, table_key: str):
    cfg, err = _validate_table_key(table_key)
    if err:
        return err
    active_only = request.query_params.get("active_only", "true").lower() != "false"
    items, warnings = get_lookup(cfg.key, active_only=active_only)
    return Response({"items": items, "warnings": warnings})


master_lookup.required_permission = PERM_MASTERDATA_VIEW


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def item_level1_category_lookup(request):
    active_only = request.query_params.get("active_only", "true").lower() != "false"
    items, warnings = list_item_category_lookup(
        active_only=active_only,
        include_value=(
            request.query_params.get("include_value")
            or request.query_params.get("current_category_id")
        ),
    )
    return Response({"items": items, "warnings": warnings})


item_level1_category_lookup.required_permission = PERM_MASTERDATA_VIEW


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def item_ifrc_family_lookup(request):
    active_only = request.query_params.get("active_only", "true").lower() != "false"
    items, warnings = list_ifrc_family_lookup(
        category_id=request.query_params.get("category_id"),
        search=request.query_params.get("search"),
        active_only=active_only,
    )
    return Response({"items": items, "warnings": warnings})


item_ifrc_family_lookup.required_permission = PERM_MASTERDATA_VIEW


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def item_ifrc_reference_lookup(request):
    active_only = request.query_params.get("active_only", "true").lower() != "false"
    try:
        limit = int(request.query_params.get("limit", DEFAULT_PAGE_LIMIT))
        limit = max(MIN_PAGE_LIMIT, min(limit, MAX_PAGE_LIMIT))
    except (ValueError, TypeError):
        limit = DEFAULT_PAGE_LIMIT

    items, warnings = list_ifrc_reference_lookup(
        ifrc_family_id=(
            request.query_params.get("ifrc_family_id")
            or request.query_params.get("family_id")
        ),
        search=request.query_params.get("search"),
        active_only=active_only,
        limit=limit,
    )
    return Response({"items": items, "warnings": warnings})


item_ifrc_reference_lookup.required_permission = PERM_MASTERDATA_VIEW


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def ifrc_family_suggest(request):
    payload, errors, warnings = suggest_ifrc_family_authoring(request.data or {})
    if errors:
        return Response({"errors": errors, "warnings": warnings}, status=400)
    return Response({**(payload or {}), "warnings": warnings})


ifrc_family_suggest.required_permission = [PERM_MASTERDATA_CREATE, PERM_MASTERDATA_EDIT]


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def ifrc_item_reference_suggest(request):
    payload, errors, warnings = suggest_ifrc_reference_authoring(request.data or {})
    if errors:
        return Response({"errors": errors, "warnings": warnings}, status=400)
    return Response({**(payload or {}), "warnings": warnings})


ifrc_item_reference_suggest.required_permission = [PERM_MASTERDATA_CREATE, PERM_MASTERDATA_EDIT]


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def ifrc_family_replacement(request, pk: str):
    cfg = TABLE_REGISTRY["ifrc_families"]
    pk_value = _coerce_pk(cfg, pk)
    retire_original = str((request.data or {}).get("retire_original") or "").lower() in {"1", "true", "yes"}
    payload, warnings = create_catalog_replacement(
        "ifrc_families",
        pk_value,
        request.data or {},
        _actor_id(request),
        retire_original=retire_original,
    )
    if payload is None:
        if "not_found" in warnings:
            return Response({"detail": "Not found.", "warnings": warnings}, status=404)
        return Response({"detail": "Replacement failed.", "warnings": warnings}, status=500)
    response_payload = dict(payload)
    response_payload["warnings"] = warnings
    response_payload.update(catalog_detail_metadata("ifrc_families"))
    return Response(response_payload, status=201)


ifrc_family_replacement.required_permission = [PERM_MASTERDATA_CREATE, PERM_MASTERDATA_EDIT]


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def ifrc_item_reference_replacement(request, pk: str):
    cfg = TABLE_REGISTRY["ifrc_item_references"]
    pk_value = _coerce_pk(cfg, pk)
    retire_original = str((request.data or {}).get("retire_original") or "").lower() in {"1", "true", "yes"}
    payload, warnings = create_catalog_replacement(
        "ifrc_item_references",
        pk_value,
        request.data or {},
        _actor_id(request),
        retire_original=retire_original,
    )
    if payload is None:
        if "not_found" in warnings:
            return Response({"detail": "Not found.", "warnings": warnings}, status=404)
        return Response({"detail": "Replacement failed.", "warnings": warnings}, status=500)
    response_payload = dict(payload)
    response_payload["warnings"] = warnings
    response_payload.update(catalog_detail_metadata("ifrc_item_references"))
    return Response(response_payload, status=201)


ifrc_item_reference_replacement.required_permission = [PERM_MASTERDATA_CREATE, PERM_MASTERDATA_EDIT]


# ---------------------------------------------------------------------------
# IFRC Suggest / Health
# ---------------------------------------------------------------------------


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def ifrc_suggest(request):
    cfg = _ifrc_cfg()
    if not cfg["IFRC_ENABLED"]:
        return Response({"detail": "IFRC suggestion service is disabled."}, status=503)

    user_id = _actor_id(request)
    if not _allow_ifrc_request(user_id, cfg["RATE_LIMIT_PER_MINUTE"]):
        return Response({"detail": "Rate limit exceeded."}, status=429)

    raw_name = str(request.query_params.get("name", "")).strip()
    if len(raw_name) < cfg["MIN_INPUT_LENGTH"]:
        return Response(
            {"error": f"'name' must be at least {cfg['MIN_INPUT_LENGTH']} characters."},
            status=400,
        )
    if len(raw_name) > cfg["MAX_INPUT_LENGTH"]:
        return Response(
            {"error": f"'name' must not exceed {cfg['MAX_INPUT_LENGTH']} characters."},
            status=400,
        )

    sanitized_name = _SAFE_INPUT_RE.sub("", raw_name).strip()
    if not sanitized_name:
        return Response({"error": "Input contains no usable characters."}, status=400)

    size_weight = _SAFE_INPUT_RE.sub("", str(request.query_params.get("size_weight", ""))).strip()[:20]
    form = _SAFE_INPUT_RE.sub("", str(request.query_params.get("form", ""))).strip()[:20]
    material = _SAFE_INPUT_RE.sub("", str(request.query_params.get("material", ""))).strip()[:30]

    suggestion = _ifrc_agent().generate(
        sanitized_name,
        size_weight=size_weight,
        form=form,
        material=material,
    )
    suggestion_id = _write_ifrc_audit_log(
        item_name_input=sanitized_name,
        suggestion=suggestion,
        user_id=user_id,
    )
    resolution_payload = _resolve_ifrc_suggestion(
        suggestion,
        item_name=sanitized_name,
        size_weight=size_weight,
        form=form,
        material=material,
        auto_fill_threshold=cfg["AUTO_FILL_CONFIDENCE_THRESHOLD"],
    )

    response_payload = {
        "suggestion_id": str(suggestion_id) if suggestion_id is not None else None,
        # Map v4 field names to existing API field names for backward compatibility.
        "ifrc_code": suggestion.item_code,
        "ifrc_description": suggestion.standardised_name,
        "confidence": suggestion.confidence,
        "match_type": suggestion.match_type,
        "construction_rationale": suggestion.construction_rationale,
        "group_code": suggestion.grp or "",
        "family_code": suggestion.fam or "",
        "category_code": suggestion.cat or "",
        "spec_segment": suggestion.spec_seg or "",
        "sequence": suggestion.seq or 0,
        "auto_fill_threshold": cfg["AUTO_FILL_CONFIDENCE_THRESHOLD"],
        **resolution_payload,
    }

    serializer = IFRCSuggestionResponseSerializer(response_payload)
    return Response(serializer.data, status=200)


ifrc_suggest.required_permission = PERM_MASTERDATA_VIEW


@api_view(["GET"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def ifrc_health(request):
    cfg = _ifrc_cfg()
    breaker_open = cb_is_open()
    status = "healthy" if cfg["IFRC_ENABLED"] and not breaker_open else "degraded"

    return Response(
        {
            "status": status,
            "ifrc_enabled": cfg["IFRC_ENABLED"],
            "llm_enabled": cfg["LLM_ENABLED"],
            "llm_circuit_breaker_open": breaker_open,
            "model_id": cfg["OLLAMA_MODEL_ID"],
        },
        status=200 if status == "healthy" else 503,
    )


ifrc_health.required_permission = PERM_MASTERDATA_VIEW


def _write_ifrc_audit_log(
    *,
    item_name_input: str,
    suggestion: IFRCCodeSuggestion,
    user_id: str,
) -> int | None:
    try:
        row = ItemIfrcSuggestLog.objects.create(
            item_name_input=item_name_input[:120],
            suggested_code=(suggestion.item_code or "")[:30],
            suggested_desc=(suggestion.standardised_name or "")[:120],
            confidence=suggestion.confidence,
            match_type=(suggestion.match_type or "none")[:20],
            construction_rationale=(suggestion.construction_rationale or "")[:4000],
            user_id=user_id[:50],
        )
        return int(row.pk)
    except Exception as exc:
        logger.warning("Failed to write IFRC audit log for user %s: %s", user_id, exc)
        return None


# ---------------------------------------------------------------------------
# Inactivate / Activate
# ---------------------------------------------------------------------------

@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def master_inactivate(request, table_key: str, pk: str):
    cfg, err = _validate_table_key(table_key)
    if err:
        return err
    if not cfg.has_status:
        return Response({"detail": "This table does not support status changes."}, status=400)
    pk_value = _coerce_pk(cfg, pk)

    # Check dependencies first
    blocking, dep_warnings = check_dependencies(cfg.key, pk_value)
    if any(w.startswith("dependency_check_failed_") for w in dep_warnings):
        return Response(
            {
                "detail": "Failed to validate dependencies before inactivation.",
                "warnings": dep_warnings,
            },
            status=500,
        )
    if blocking:
        return Response({
            "detail": "Cannot inactivate: referenced by other records.",
            "blocking": blocking,
            "warnings": dep_warnings,
        }, status=409)

    expected_version = (request.data or {}).get("version_nbr")
    if expected_version is not None:
        try:
            expected_version = int(expected_version)
        except (ValueError, TypeError):
            expected_version = None

    if cfg.key == "items":
        success, warnings = update_item_record(
            pk_value,
            {cfg.status_field: cfg.inactive_status},
            _actor_id(request),
            expected_version,
        )
    elif is_governed_catalog_table(cfg.key):
        success, warnings = inactivate_catalog_record(
            cfg.key, pk_value, _actor_id(request), expected_version,
        )
    else:
        success, warnings = inactivate_record(
            cfg.key, pk_value, _actor_id(request), expected_version,
        )
    if not success:
        if "version_conflict" in warnings:
            return Response(
                {"detail": "Record was modified by another user.", "warnings": warnings},
                status=409,
            )
        return Response({"detail": "Inactivation failed.", "warnings": warnings}, status=500)

    if cfg.key == "items":
        record, _ = get_item_record(pk_value)
    else:
        record, _ = get_record(cfg.key, pk_value)
    payload = {"record": record, "warnings": warnings}
    payload.update(catalog_detail_metadata(cfg.key))
    return Response(payload)


master_inactivate.required_permission = PERM_MASTERDATA_INACTIVATE


@api_view(["POST"])
@authentication_classes([LegacyCompatAuthentication])
@permission_classes([MasterDataPermission])
def master_activate(request, table_key: str, pk: str):
    cfg, err = _validate_table_key(table_key)
    if err:
        return err
    if not cfg.has_status:
        return Response({"detail": "This table does not support status changes."}, status=400)
    pk_value = _coerce_pk(cfg, pk)

    expected_version = (request.data or {}).get("version_nbr")
    if expected_version is not None:
        try:
            expected_version = int(expected_version)
        except (ValueError, TypeError):
            expected_version = None

    if cfg.key == "items":
        success, warnings = update_item_record(
            pk_value,
            {cfg.status_field: cfg.active_status},
            _actor_id(request),
            expected_version,
        )
    elif is_governed_catalog_table(cfg.key):
        success, warnings = activate_catalog_record(
            cfg.key, pk_value, _actor_id(request), expected_version,
        )
    else:
        success, warnings = activate_record(
            cfg.key, pk_value, _actor_id(request), expected_version,
        )
    if not success:
        if "version_conflict" in warnings:
            return Response(
                {"detail": "Record was modified by another user.", "warnings": warnings},
                status=409,
            )
        return Response({"detail": "Activation failed.", "warnings": warnings}, status=500)

    if cfg.key == "items":
        record, _ = get_item_record(pk_value)
    else:
        record, _ = get_record(cfg.key, pk_value)
    payload = {"record": record, "warnings": warnings}
    payload.update(catalog_detail_metadata(cfg.key))
    return Response(payload)


master_activate.required_permission = PERM_MASTERDATA_EDIT


for _view in (
    master_list_create,
    master_detail_update,
    master_summary,
    master_lookup,
    item_level1_category_lookup,
    item_ifrc_family_lookup,
    item_ifrc_reference_lookup,
    ifrc_family_suggest,
    ifrc_item_reference_suggest,
    ifrc_family_replacement,
    ifrc_item_reference_replacement,
    ifrc_suggest,
    ifrc_health,
    master_inactivate,
    master_activate,
):
    if hasattr(_view, "cls"):
        _view.cls.required_permission = _view.required_permission





