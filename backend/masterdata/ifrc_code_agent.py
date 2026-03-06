"""
DMIS IFRC Item Code Generator Agent (v4)
==========================================
Generates structurally valid IFRC item codes matching the real
IFRC/ICRC Standard Products Catalogue 15-character codification.

Code structure (real IFRC):
    GROUP(1) + FAMILY(3) + CATEGORY(4) + SPEC(0-7) + SEQ(02) = max 17 chars

    Example: MDRECOMPA1001
        M   = Group  Medical Renewable Items
        DRE = Family Dressings
        COMP= Category Compress / Wound Pad
        A10 = Spec  aluminized, 10 cm
        01  = Sequence 01

Taxonomy source: masterdata/data/ifrc_catalogue_taxonomy.md
LLM:            Ollama via direct httpx POST (no LangChain/LangGraph)

To update the catalogue:
    1. Edit masterdata/data/ifrc_catalogue_taxonomy.md
    2. python manage.py reload_ifrc_taxonomy
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional

from django.conf import settings
from django.core.cache import cache

from masterdata.ifrc_catalogue_loader import get_taxonomy, IFRCTaxonomy

logger = logging.getLogger("dmis.ifrc.agent")


# ─── Config ───────────────────────────────────────────────────────────────────

_DEFAULTS: dict[str, Any] = {
    "IFRC_ENABLED": True,
    "LLM_ENABLED": False,
    "OLLAMA_BASE_URL": "http://localhost:11434",
    "OLLAMA_MODEL_ID": "qwen3.5:0.8b",
    "OLLAMA_TIMEOUT_SECONDS": 10,
    "CB_FAILURE_THRESHOLD": 5,
    "CB_RESET_TIMEOUT_SECONDS": 120,
    "CB_REDIS_KEY": "ifrc:circuit_breaker",
}


def _cfg(key: str) -> Any:
    return getattr(settings, "IFRC_AGENT", {}).get(key, _DEFAULTS.get(key))


# ─── Output model ─────────────────────────────────────────────────────────────

@dataclass
class IFRCCodeSuggestion:
    """Mirrors the real IFRC 15-char code structure."""
    # Generated code (up to 17 chars: G+FAM3+CAT4+SPEC7+SEQ2)
    item_code:              Optional[str] = None
    standardised_name:      Optional[str] = None
    confidence:             float         = 0.0
    match_type:             str           = "none"
    # Segments
    grp:                    Optional[str] = None   # 1 letter
    grp_label:              Optional[str] = None
    fam:                    Optional[str] = None   # 3 letters
    fam_label:              Optional[str] = None
    cat:                    Optional[str] = None   # 4 letters
    cat_label:              Optional[str] = None
    spec_seg:               Optional[str] = None   # 0-7 chars
    seq:                    Optional[int] = None   # integer sequence
    construction_rationale: str           = ""
    llm_used:               bool          = False
    alternatives:           list          = field(default_factory=list)


@dataclass
class AgentState:
    item_name:  str
    size_weight: str = ""
    form: str = ""
    material: str = ""
    normalized: Optional[str] = None
    grp:        Optional[str] = None
    fam:        Optional[str] = None
    cat:        Optional[str] = None
    source:     str           = "unknown"
    llm_used:   bool          = False
    llm_confidence: Optional[float] = None
    result:     Optional[IFRCCodeSuggestion] = None


# ─── Circuit breaker ──────────────────────────────────────────────────────────

def _cb_count_key() -> str:
    return f"{_cfg('CB_REDIS_KEY')}:count"


def _cb_open_until_key() -> str:
    return f"{_cfg('CB_REDIS_KEY')}:open_until"


def _cb_is_open() -> bool:
    open_until_raw = cache.get(_cb_open_until_key())
    if open_until_raw is None:
        return False
    try:
        open_until = int(open_until_raw)
    except (TypeError, ValueError):
        cache.delete(_cb_open_until_key())
        return False
    now = int(time.time())
    if now < open_until:
        return True
    cache.delete(_cb_open_until_key())
    return False


def cb_is_open() -> bool:
    """Public accessor for views."""
    return _cb_is_open()


def _cb_record_failure() -> None:
    count_key = _cb_count_key()
    open_key = _cb_open_until_key()
    threshold = int(_cfg("CB_FAILURE_THRESHOLD"))
    timeout = max(int(_cfg("CB_RESET_TIMEOUT_SECONDS")), 1)

    # Atomic increment where supported by backend.
    if cache.add(count_key, 1, timeout=timeout):
        failures = 1
    else:
        try:
            failures = int(cache.incr(count_key))
        except (ValueError, TypeError):
            cache.set(count_key, 1, timeout=timeout)
            failures = 1
    try:
        cache.touch(count_key, timeout=timeout)
    except (AttributeError, NotImplementedError, TypeError):
        # Backend may not implement touch; initial timeout still bounds the key lifetime.
        pass

    if failures >= threshold:
        open_until = int(time.time()) + timeout
        cache.set(open_key, open_until, timeout=timeout)
        logger.warning("IFRC circuit breaker OPEN after %d LLM failures.", failures)


def _cb_record_success() -> None:
    cache.delete(_cb_count_key())
    cache.delete(_cb_open_until_key())
    # Cleanup legacy state key from older implementation.
    cache.delete(_cfg("CB_REDIS_KEY"))


# ─── Ollama LLM call ──────────────────────────────────────────────────────────

def _call_ollama(prompt: str) -> dict:
    import httpx
    response = httpx.post(
        f"{_cfg('OLLAMA_BASE_URL')}/api/generate",
        json={
            "model":   _cfg("OLLAMA_MODEL_ID"),
            "prompt":  prompt,
            "format":  "json",
            "stream":  False,
            "options": {"temperature": 0},
        },
        timeout=_cfg("OLLAMA_TIMEOUT_SECONDS"),
    )
    response.raise_for_status()
    raw = response.json().get("response", "")
    raw = re.sub(r"```[a-z]*|```", "", raw).strip()
    return json.loads(raw)


# ─── Classification ───────────────────────────────────────────────────────────

def _keyword_classify(
    name: str,
    taxonomy: IFRCTaxonomy,
) -> tuple[str, str, str] | None:
    """
    Fast classification from the keyword index.
    Returns (grp, fam, cat) or None.
    Bigrams checked first (more specific), then single words.
    """
    words = re.findall(r"[a-zA-Z]{3,}", name.lower())

    for i in range(len(words) - 1):
        bigram = f"{words[i]} {words[i + 1]}"
        if bigram in taxonomy.keyword_index:
            triple = taxonomy.keyword_index[bigram]
            logger.debug("IFRC bigram '%s' -> %s/%s/%s", bigram, *triple)
            return triple

    for w in words:
        if w in taxonomy.keyword_index:
            triple = taxonomy.keyword_index[w]
            logger.debug("IFRC keyword '%s' -> %s/%s/%s", w, *triple)
            return triple

    return None


def _llm_classify(
    item_name: str,
    taxonomy: IFRCTaxonomy,
) -> tuple[str, str, str, float]:
    """LLM classification. Returns (grp, fam, cat, confidence). Raises on failure."""
    prompt = (
        f'Item to classify: "{item_name}"\n\n'
        f"Available Groups (1-letter code: description):\n{taxonomy.all_groups_text()}\n\n"
        f"Available Group/Family/Category:\n{taxonomy.all_categories_text()}\n\n"
        "Reply ONLY with JSON (no markdown fences):\n"
        '{"group": "<1-letter code>", "family": "<3-letter code>", '
        '"category": "<4-letter code>", "confidence": <0.0-1.0>, "rationale": "<15 words max>"}'
    )
    t0     = time.monotonic()
    parsed = _call_ollama(prompt)
    logger.debug("IFRC LLM responded in %.2fs", time.monotonic() - t0)

    grp = str(parsed.get("group", "")).strip().upper()[:1]
    fam = str(parsed.get("family", "")).strip().upper()[:3]
    cat = str(parsed.get("category", "")).strip().upper()[:4]
    confidence = float(parsed.get("confidence", 0.5))

    if grp not in taxonomy.groups:
        raise ValueError(f"LLM returned unknown group '{grp}'")
    if fam not in taxonomy.families_for_group(grp):
        raise ValueError(f"LLM returned unknown family '{fam}' for group '{grp}'")
    if cat not in taxonomy.categories_for_family(grp, fam):
        raise ValueError(f"LLM returned unknown category '{cat}' for {grp}/{fam}")

    return grp, fam, cat, confidence


def _best_effort_fallback(
    name: str,
    taxonomy: IFRCTaxonomy,
) -> tuple[str, str, str, str]:
    """
    Rule-based fallback. Checks item name tokens against group keywords,
    then picks the first family/category available.
    Defaults to H/SHE/TRPL (tarpaulin) as a common disaster-relief item.
    Returns (grp, fam, cat, source).
    """
    n = name.lower()
    tokens = set(re.findall(r"[a-z]{3,}", n))

    group_hints: dict[str, set[str]] = {
        "M": {"compress", "bandage", "gauze", "syringe", "glove", "dressing", "suture"},
        "D": {"drug", "medicine", "tablet", "capsule", "antibiotic", "paracetamol", "vaccine"},
        "W": {"water", "hygiene", "latrine", "sanitation", "soap", "chlorine", "jerrycan", "bucket"},
        "H": {"tent", "tarpaulin", "tarp", "blanket", "sleeping", "shelter"},
        "F": {"food", "rice", "flour", "oil", "cereal", "biscuit", "meat", "fish", "bean"},
        "E": {"generator", "battery", "batteries", "solar", "lantern", "torch", "fuel"},
        "C": {"radio", "satellite", "telecom", "walkie"},
        "T": {"vehicle", "truck", "motorcycle"},
        "A": {"paper", "pen", "pencil", "stationery", "office"},
        "K": {"kit", "module"},
    }
    for grp, hints in group_hints.items():
        if tokens & hints and grp in taxonomy.groups:
            g = taxonomy.groups[grp]
            fam = next(iter(g.families))
            f   = g.families[fam]
            cat = next(iter(f.categories), "UNKN")
            return grp, fam, cat, "fallback"

    # Default: H/SHE/TRPL
    if "H" in taxonomy.groups:
        h = taxonomy.groups["H"]
        if "SHE" in h.families and "TRPL" in h.families["SHE"].categories:
            return "H", "SHE", "TRPL", "fallback"

    grp = next(iter(taxonomy.groups))
    fam = next(iter(taxonomy.groups[grp].families))
    cat = next(iter(taxonomy.groups[grp].families[fam].categories), "UNKN")
    return grp, fam, cat, "fallback"


# ─── Spec encoding (mirrors real IFRC form/material/size spec) ────────────────

_FORM_CODES: dict[str, str] = {
    "tablet": "TB",   "tablets": "TB",
    "liquid": "LQ",
    "solution": "SL",
    "powder": "PW",   "powdered": "PW",
    "canned": "CN",   "can": "CN",
    "bar": "BR",      "bars": "BR",
    "sachet": "SC",   "sachets": "SC",
    "capsule": "CP",  "capsules": "CP",
    "cream": "CR",
    "roll": "RL",     "rolls": "RL",
    "sheet": "SH",    "sheets": "SH",
    "kit": "KT",
    "pack": "PK",     "packet": "PK",
    "bottle": "BT",
    "bag": "BG",
    "box": "BX",
    "tube": "TU",
    "gel": "GL",
    "spray": "SP",
    "syrup": "SY",
    "injection": "IN",
    "infusion": "IF",
    "lotion": "LO",
}

_MATERIAL_CODES: dict[str, str] = {
    "aluminized": "AL", "aluminium": "AL", "aluminum": "AL",
    "cotton": "CT",
    "polyethylene": "PE",
    "polypropylene": "PP",
    "plastic": "PL",
    "rubber": "RB",
    "nylon": "NY",
    "synthetic": "SY",
    "stainless": "SS",
    "latex": "LX",
    "wool": "WO",
    "fleece": "FL",
    "nitrile": "NI",
}

_SIZE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(kg|mg|g|l|lt|liter|litre|ml|kva|kw|cm|mm)\b",
    re.IGNORECASE,
)


def _encode_size(text: str) -> str:
    """Encode size/weight to 1-3 char code: '200g' -> '200', '5L' -> '5L', '25kg' -> '25K'."""
    m = _SIZE_RE.search(text.lower())
    if not m:
        return ""
    unit = m.group(2).lower()
    if unit in ("lt", "liter", "litre"):
        unit = "l"

    try:
        value = Decimal(m.group(1))
    except (InvalidOperation, ValueError):
        return ""

    try:
        # Normalize first, then quantize once on the canonical base unit.
        if unit in ("kg", "g", "mg"):
            grams = (
                value * Decimal("1000")
                if unit == "kg"
                else value / Decimal("1000")
                if unit == "mg"
                else value
            )
            n = int(grams.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            return f"{n // 1000}K"[:3] if n >= 1000 else str(n)[:3]

        if unit in ("l", "ml"):
            milliliters = value * Decimal("1000") if unit == "l" else value
            n = int(milliliters.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            return f"{n // 1000}L"[:3] if n >= 1000 else f"{n}M"[:3]

        if unit in ("cm", "mm"):
            millimeters = value * Decimal("10") if unit == "cm" else value
            n = int(millimeters.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            return f"{n // 10}C"[:3] if n >= 10 and n % 10 == 0 else f"{n}M"[:3]

        if unit in ("kva", "kw"):
            n = int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            return f"{n}K"[:3]
    except (InvalidOperation, ValueError):
        return ""

    return ""


def _encode_spec(
    item_name: str,
    form: str = "",
    material: str = "",
    size_weight: str = "",
) -> str:
    """
    Build Specifications segment (0-7 chars) from the item name.
    Mirrors real IFRC spec encoding: [form/material (2 letters)] + [size (1-3 chars)].
    """
    n = item_name.lower()
    form_text = (form or "").strip().lower()
    material_text = (material or "").strip().lower()
    size_text = (size_weight or "").strip().lower()
    parts: list[str] = []

    # Explicit form parameter takes priority over parsing item_name.
    if form_text:
        for kw, code in _FORM_CODES.items():
            if re.search(r"\b" + re.escape(kw) + r"\b", form_text):
                parts.append(code)
                break

    # Fall back to form terms found in item_name.
    if not parts:
        for kw, code in _FORM_CODES.items():
            if re.search(r"\b" + re.escape(kw) + r"\b", n):
                parts.append(code)
                break

    # Material code when no form matched, using explicit material first.
    if not parts:
        if material_text:
            for kw, code in _MATERIAL_CODES.items():
                if kw in material_text:
                    parts.append(code)
                    break
    if not parts:
        for kw, code in _MATERIAL_CODES.items():
            if kw in n:
                parts.append(code)
                break

    # Size appended after form/material; explicit size hint takes precedence.
    size = _encode_size(size_text) if size_text else ""
    if not size:
        size = _encode_size(item_name)
    if size:
        parts.append(size)

    return "".join(parts)[:7]


# ─── Collision check ──────────────────────────────────────────────────────────

_SCHEMA_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _schema_name() -> str:
    schema = os.getenv("DMIS_DB_SCHEMA", "public")
    return schema if _SCHEMA_RE.fullmatch(schema) else "public"


def _find_next_seq(prefix: str) -> int:
    """
    Find next available 2-digit sequence for codes matching prefix + NN.
    Uses DB-backed locking to avoid race conditions during allocation.
    """
    from django.db import connection, DatabaseError, transaction

    schema = _schema_name()
    prefix_upper = prefix.upper()
    pattern = f"{prefix_upper}%"
    seq_pattern = re.compile(rf"^{re.escape(prefix_upper)}(\d{{1,2}})$")

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                if connection.vendor == "postgresql":
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s))",
                        [f"ifrc_seq:{prefix_upper}"],
                    )
                cursor.execute(
                    f"SELECT item_code FROM {schema}.item WHERE item_code LIKE %s",
                    [pattern],
                )
                rows = cursor.fetchall()
    except DatabaseError as exc:
        raise RuntimeError(
            f"Unable to allocate IFRC sequence for prefix '{prefix_upper}' due to database error."
        ) from exc

    used: set[int] = set()
    for (code,) in rows:
        m = seq_pattern.match(str(code or "").strip().upper())
        if m:
            seq_val = int(m.group(1))
            if 1 <= seq_val <= 99:
                used.add(seq_val)

    for seq in range(1, 100):
        if seq not in used:
            return seq
    raise RuntimeError(
        f"Unable to allocate IFRC sequence for prefix '{prefix_upper}': all suffixes 01-99 are in use."
    )


# ─── Code construction ────────────────────────────────────────────────────────

def _construct_code(
    grp: str,
    fam: str,
    cat: str,
    item_name: str,
    taxonomy: IFRCTaxonomy,
    *,
    size_weight: str = "",
    form: str = "",
    material: str = "",
) -> dict:
    """
    Build the full IFRC code: GROUP(1)+FAMILY(3)+CATEGORY(4)+SPEC(0-7)+SEQ(02).
    Returns all segments and a human-readable rationale.
    """
    spec    = _encode_spec(item_name, form=form, material=material, size_weight=size_weight)
    prefix  = f"{grp}{fam}{cat}{spec}".upper()
    seq     = _find_next_seq(prefix)
    code    = f"{prefix}{seq:02d}"

    grp_label = taxonomy.group_label(grp)
    fam_label = taxonomy.family_label(grp, fam)
    cat_label = taxonomy.category_label(grp, fam, cat)

    rationale = (
        f"Group '{grp}' ({grp_label}); "
        f"Family '{fam}' ({fam_label}); "
        f"Category '{cat}' ({cat_label}); "
        f"Spec '{spec or 'none'}'; "
        f"Sequence {seq:02d} (next available for prefix '{prefix}')."
    )
    return {
        "code":      code,
        "grp":       grp,
        "fam":       fam,
        "cat":       cat,
        "spec_seg":  spec,
        "seq":       seq,
        "rationale": rationale,
        "grp_label": grp_label,
        "fam_label": fam_label,
        "cat_label": cat_label,
    }


def _standardise_description(item_name: str) -> str:
    """Convert free-text name to IFRC-style: NOUN, ADJECTIVE, SPEC (all caps, max 120)."""
    clean = item_name.strip().upper()
    words = clean.split()
    adjectives = {
        "PLASTIC", "METAL", "SYNTHETIC", "COTTON", "NYLON", "ALUMINIUM",
        "ALUMINIZED", "SOLAR", "DIESEL", "ELECTRIC", "PORTABLE", "FOLDING",
        "HEAVY", "LIGHT", "STANDARD", "BASIC", "FAMILY", "INDIVIDUAL",
    }
    if len(words) >= 2 and words[0] in adjectives:
        clean = f"{' '.join(words[1:])}, {words[0]}"
    return clean[:120]


def _generate_alternatives(
    item_name: str,
    used_grp: str,
    used_fam: str,
    used_cat: str,
    taxonomy: IFRCTaxonomy,
    *,
    size_weight: str = "",
    form: str = "",
    material: str = "",
) -> list[dict]:
    """Generate up to 2 alternative classifications from the keyword index."""
    words = re.findall(r"[a-zA-Z]{3,}", item_name.lower())
    seen  = {(used_grp, used_fam, used_cat)}
    alts  = []

    for w in words:
        if w in taxonomy.keyword_index:
            triple = taxonomy.keyword_index[w]
            if triple not in seen:
                grp, fam, cat = triple
                try:
                    built = _construct_code(
                        grp,
                        fam,
                        cat,
                        item_name,
                        taxonomy,
                        size_weight=size_weight,
                        form=form,
                        material=material,
                    )
                    alts.append({
                        "item_code": built["code"],
                        "grp": grp, "grp_label": taxonomy.group_label(grp),
                        "fam": fam, "fam_label": taxonomy.family_label(grp, fam),
                        "cat": cat, "cat_label": taxonomy.category_label(grp, fam, cat),
                        "rationale": f"Alternative if classified under {grp}/{fam}/{cat}",
                    })
                except Exception as exc:
                    logger.debug("Alt code failed %s/%s/%s: %s", grp, fam, cat, exc)
                seen.add(triple)
        if len(alts) >= 2:
            break
    return alts


# ─── Pipeline stages ──────────────────────────────────────────────────────────

def _stage_normalize(state: AgentState) -> AgentState:
    if not (state.item_name or "").strip():
        state.normalized = ""
        state.source = "empty"
        return state
    s = state.item_name.strip().lower()
    s = re.sub(r"[^a-z0-9\s\-\',/]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        state.normalized = ""
        state.source = "empty"
        return state
    state.normalized = s
    return state


def _stage_classify(state: AgentState, taxonomy: IFRCTaxonomy) -> AgentState:
    if state.source == "empty":
        state.grp, state.fam, state.cat = None, None, None
        state.llm_used = False
        state.llm_confidence = None
        return state

    name = state.normalized or state.item_name

    hit = _keyword_classify(name, taxonomy)
    if hit:
        state.grp, state.fam, state.cat = hit
        state.source = "keyword"
        state.llm_used = False
        state.llm_confidence = None
        return state

    if not _cfg("LLM_ENABLED") or _cb_is_open():
        if _cb_is_open():
            logger.info("IFRC circuit breaker open — using fallback.")
        state.grp, state.fam, state.cat, state.source = _best_effort_fallback(name, taxonomy)
        state.llm_used = False
        state.llm_confidence = None
        return state

    try:
        grp, fam, cat, llm_confidence = _llm_classify(state.item_name, taxonomy)
        state.grp, state.fam, state.cat = grp, fam, cat
        state.source = "llm"
        state.llm_used = True
        state.llm_confidence = llm_confidence
        _cb_record_success()
    except Exception as exc:
        logger.warning("IFRC LLM failed (%s). Using fallback.", exc)
        _cb_record_failure()
        state.grp, state.fam, state.cat, state.source = _best_effort_fallback(name, taxonomy)
        state.llm_used = False
        state.llm_confidence = None

    return state


def _stage_construct(state: AgentState, taxonomy: IFRCTaxonomy) -> AgentState:
    if not state.grp or not state.fam or not state.cat:
        state.result = IFRCCodeSuggestion(
            confidence=0.0,
            match_type="none",
            construction_rationale="Classification failed; no Group/Family/Category determined.",
        )
        return state

    try:
        built    = _construct_code(
            state.grp,
            state.fam,
            state.cat,
            state.item_name,
            taxonomy,
            size_weight=state.size_weight,
            form=state.form,
            material=state.material,
        )
        std_name = _standardise_description(state.item_name)
        alts     = _generate_alternatives(
            state.item_name,
            state.grp,
            state.fam,
            state.cat,
            taxonomy,
            size_weight=state.size_weight,
            form=state.form,
            material=state.material,
        )
        if state.source == "fallback":
            confidence = 0.45
            match_type = "fallback"
        elif state.llm_used:
            confidence = state.llm_confidence if state.llm_confidence is not None else 0.90
            match_type = "generated"
        else:
            confidence = 0.85
            match_type = "generated"
        state.result = IFRCCodeSuggestion(
            item_code=built["code"],
            standardised_name=std_name,
            confidence=confidence,
            match_type=match_type,
            grp=built["grp"],
            grp_label=built["grp_label"],
            fam=built["fam"],
            fam_label=built["fam_label"],
            cat=built["cat"],
            cat_label=built["cat_label"],
            spec_seg=built["spec_seg"],
            seq=built["seq"],
            construction_rationale=built["rationale"],
            llm_used=state.llm_used,
            alternatives=alts,
        )
    except Exception as exc:
        logger.exception("IFRC code construction error: %s", exc)
        state.result = IFRCCodeSuggestion(
            confidence=0.0,
            match_type="none",
            construction_rationale=f"Code construction error: {exc}",
        )
    return state


def _stage_validate(state: AgentState) -> AgentState:
    r = state.result
    if not r:
        state.result = IFRCCodeSuggestion(
            confidence=0.0, match_type="none",
            construction_rationale="No result produced.",
        )
        return state
    r.confidence = max(0.0, min(1.0, r.confidence))
    if r.item_code:
        r.item_code = r.item_code.upper()
        if len(r.item_code) > 30:
            logger.warning("Generated code '%s' exceeds 30 chars — truncating.", r.item_code)
            r.item_code = r.item_code[:30]
    state.result = r
    return state


# ─── Public interface ─────────────────────────────────────────────────────────

class IFRCAgent:
    """
    Generates real IFRC-compliant item codes:
        GROUP(1) + FAMILY(3) + CATEGORY(4) + SPEC(0-7) + SEQ(02)

    Usage:
        agent = IFRCAgent()
        result = agent.generate("blanket synthetic medium thermal")

    To update the catalogue:
        1. Edit masterdata/data/ifrc_catalogue_taxonomy.md
        2. python manage.py reload_ifrc_taxonomy
    """

    def generate(
        self,
        item_name: str,
        *,
        size_weight: str = "",
        form: str = "",
        material: str = "",
    ) -> IFRCCodeSuggestion:
        taxonomy = get_taxonomy()
        state    = AgentState(
            item_name=item_name,
            size_weight=size_weight,
            form=form,
            material=material,
        )
        state    = _stage_normalize(state)
        state    = _stage_classify(state, taxonomy)
        state    = _stage_construct(state, taxonomy)
        state    = _stage_validate(state)
        return state.result  # type: ignore[return-value]

    def suggest(
        self,
        item_name: str,
        *,
        size_weight: str = "",
        form: str = "",
        material: str = "",
    ) -> IFRCCodeSuggestion:
        """Backward-compat shim preserving v3 hint params as explicit inputs."""
        return self.generate(
            item_name,
            size_weight=size_weight,
            form=form,
            material=material,
        )
