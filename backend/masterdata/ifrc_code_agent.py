"""
IFRC Item Code Generation Agent (v3 catalogue structure).

Produces codes conforming to the real 15-character IFRC codification:
  Group (1)  +  Family (3)  +  Category (4)  +  Specifications (1-7)

Example output:  FCANMEAT01       (Food / Canned / Meat, generic, seq 01)
                 FCANMEATCN20G01  (same + canned form, 200g)
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError, connection

logger = logging.getLogger("masterdata.ifrc.agent")


@dataclass
class IFRCCodeSuggestion:
    ifrc_code: str | None = None
    ifrc_description: str | None = None
    confidence: float = 0.0
    match_type: str = "none"
    construction_rationale: str = ""
    llm_used: bool = False
    group_code: str = ""       # 1 letter  (official IFRC group)
    family_code: str = ""      # 3 letters (official IFRC family)
    category_code: str = ""    # 4 letters (official IFRC category)
    spec_segment: str = ""     # 0-5 chars (form + size encoding)
    sequence: int = 0


_DEFAULTS: dict[str, Any] = {
    "LLM_ENABLED": False,
    "OLLAMA_BASE_URL": "http://localhost:11434",
    "OLLAMA_MODEL_ID": "qwen3.5:0.8b",
    "OLLAMA_TIMEOUT_SECONDS": 10,
    "CB_FAILURE_THRESHOLD": 5,
    "CB_RESET_TIMEOUT_SECONDS": 120,
    "CB_REDIS_KEY": "ifrc:circuit_breaker",
}

# ── Official IFRC group codes (18 groups, 1 letter each) ────────────────────
_GROUP_LABELS: dict[str, str] = {
    "A": "Administration",
    "C": "Radio and Telecommunications",
    "D": "Drugs",
    "E": "Engineering",
    "F": "Food",
    "H": "Housing, Shelter",
    "I": "Information Technology",
    "K": "Kits, Modules and Sets",
    "L": "Library",
    "M": "Medical Renewable Items",
    "O": "Prosthetic Technology",
    "R": "Economic Rehabilitation",
    "S": "Services",
    "T": "Transport",
    "U": "Emergency Response Units",
    "V": "Veterinary",
    "W": "Water and Sanitation",
    "X": "Medical Equipment and Instruments",
}

# ── Curated catalogue reference (group 1, family 3, category 4, keywords) ───
# Sourced from itemscatalogue.redcross.int and IFRC catalogue documentation.
# Covers disaster-relief items most relevant to ODPEM / Jamaica operations.
_CATALOGUE: list[tuple[str, str, str, list[str]]] = [
    # ── Food (F) ─────────────────────────────────────────────────────────────
    ("F", "CAN", "MEAT", ["corned beef", "canned meat", "canned beef", "luncheon meat"]),
    ("F", "CAN", "FISH", ["tuna", "sardine", "canned fish", "mackerel", "tinned fish", "herrings"]),
    ("F", "CAN", "BEAN", ["baked bean", "canned bean", "canned pea", "canned legume"]),
    ("F", "CER", "RICE", ["rice", "white rice", "parboiled rice", "long grain rice"]),
    ("F", "CER", "MAIZ", ["maize", "corn", "cornmeal", "grits"]),
    ("F", "CER", "FLOU", ["wheat flour", "flour", "all purpose flour"]),
    ("F", "CER", "OATS", ["oats", "oatmeal", "rolled oats"]),
    ("F", "OIL", "COOK", ["cooking oil", "vegetable oil", "palm oil", "canola oil", "sunflower oil"]),
    ("F", "SUG", "SUGR", ["sugar", "granulated sugar", "white sugar"]),
    ("F", "SAL", "SALT", ["salt", "iodized salt", "table salt"]),
    ("F", "NUT", "BSCT", ["biscuit", "energy biscuit", "fortified biscuit", "high energy biscuit"]),
    ("F", "PLS", "LENT", ["lentil", "red lentil", "split pea", "dried bean"]),
    # ── Water and Sanitation (W) ──────────────────────────────────────────────
    ("W", "WTR", "DRWT", ["bottled water", "drinking water", "potable water", "mineral water", "water"]),
    ("W", "WTR", "TABL", ["water purification tablet", "purification tablet", "water tablet", "chlorine tablet", "aquatab"]),
    ("W", "WTR", "CHLR", ["chlorine solution", "sodium hypochlorite", "water treatment chemical"]),
    ("W", "WTR", "CONT", ["jerry can", "jerrycan", "water container", "water jug", "water barrel"]),
    ("W", "WTR", "FLTR", ["water filter", "ceramic filter", "biosand filter", "household filter"]),
    ("W", "WTR", "PUMP", ["water pump", "hand pump", "submersible pump"]),
    ("W", "HYG", "SOAP", ["soap", "bar soap", "laundry soap", "toilet soap"]),
    ("W", "HYG", "SANR", ["hand sanitizer", "sanitiser", "sanitizer", "alcohol gel", "hand rub"]),
    ("W", "HYG", "TOIL", ["toilet paper", "toilet tissue", "tissue paper"]),
    ("W", "HYG", "BUCK", ["bucket", "pail", "water bucket"]),
    ("W", "HYG", "DPKM", ["menstrual pad", "sanitary pad", "sanitary towel", "menstrual kit"]),
    ("W", "SAN", "LATR", ["latrine", "portable toilet", "toilet seat", "sanitation kit"]),
    # ── Housing, Shelter (H) ──────────────────────────────────────────────────
    ("H", "SHE", "TRPL", ["tarpaulin", "tarp", "plastic sheeting", "poly sheeting", "polyethylene sheeting"]),
    ("H", "SHE", "TENT", ["tent", "family tent", "shelter tent", "emergency tent"]),
    ("H", "SHE", "ROPE", ["rope", "cord", "guy rope", "nylon rope"]),
    ("H", "BED", "BLAN", ["blanket", "fleece blanket", "thermal blanket", "emergency blanket"]),
    ("H", "BED", "SLPB", ["sleeping bag", "sleep bag"]),
    ("H", "KIT", "HHKT", ["household kit", "non-food item", "NFI kit", "family kit"]),
    ("H", "KIT", "KTKN", ["kitchen kit", "cooking kit", "kitchen set", "cooking utensil"]),
    # ── Medical Renewable Items (M) ───────────────────────────────────────────
    ("M", "DRE", "COMP", ["compress", "wound pad", "gauze pad", "dressing pad", "aluminized compress"]),
    ("M", "DRE", "BAND", ["bandage", "crepe bandage", "elastic bandage", "roller bandage"]),
    ("M", "DRE", "GAZE", ["gauze", "gauze roll", "gauze swab", "gauze dressing"]),
    ("M", "DRE", "SUTR", ["suture", "surgical suture", "absorbable suture"]),
    ("M", "SYR", "DISP", ["syringe", "disposable syringe", "injection syringe", "auto-disable syringe"]),
    ("M", "GLV", "LATX", ["glove", "latex glove", "examination glove", "disposable glove", "surgical glove"]),
    ("M", "MAS", "SURG", ["surgical mask", "face mask", "medical mask"]),
    ("M", "COL", "COLD", ["cold box", "vaccine carrier", "ice pack", "cold chain box"]),
    # ── Drugs (D) ────────────────────────────────────────────────────────────
    ("D", "ANL", "PARA", ["paracetamol", "acetaminophen", "panadol", "pain relief", "analgesic"]),
    ("D", "ANL", "IBUP", ["ibuprofen", "brufen", "anti-inflammatory"]),
    ("D", "ANB", "AMOX", ["amoxicillin", "antibiotic", "penicillin", "ampicillin"]),
    ("D", "ANT", "COAR", ["artemisinin", "coartem", "malaria treatment", "chloroquine", "antimalarial"]),
    ("D", "ANT", "RDTE", ["malaria rapid test", "malaria RDT", "rapid diagnostic test"]),
    ("D", "ORS", "ORSA", ["oral rehydration", "ORS", "rehydration salt", "electrolyte solution"]),
    ("D", "VIT", "VITA", ["vitamin A", "multivitamin", "vitamin supplement"]),
    # ── Kits, Modules and Sets (K) ────────────────────────────────────────────
    ("K", "FAK", "BASK", ["first aid kit", "FAK", "trauma kit"]),
    ("K", "HYK", "STND", ["hygiene kit", "dignity kit", "hygiene pack"]),
    ("K", "MED", "EMRG", ["emergency health kit", "medical emergency kit", "health kit"]),
    # ── Engineering (E) ──────────────────────────────────────────────────────
    ("E", "GEN", "PORT", ["generator", "portable generator", "petrol generator", "diesel generator"]),
    ("E", "GEN", "SOLA", ["solar panel", "solar system", "solar kit", "photovoltaic"]),
    ("E", "LGT", "SLRL", ["solar lantern", "solar lamp", "solar light"]),
    ("E", "LGT", "TRCL", ["torch", "flashlight", "headlamp"]),
    ("E", "BAT", "ALKA", ["battery", "alkaline battery", "batteries", "AA battery", "D cell battery"]),
    ("E", "FUE", "DIES", ["diesel", "fuel", "petrol", "gasoline", "kerosene"]),
    # ── Radio and Telecommunications (C) ─────────────────────────────────────
    ("C", "RAD", "HAND", ["radio", "handheld radio", "two-way radio", "walkie-talkie", "VHF radio"]),
    ("C", "COM", "SATP", ["satellite phone", "satphone", "thuraya", "iridium phone"]),
    # ── Administration (A) ────────────────────────────────────────────────────
    ("A", "OFC", "PAPE", ["paper", "office paper", "notebook", "notepad"]),
    ("A", "OFC", "PENC", ["pen", "pencil", "marker", "stationery", "ballpoint pen"]),
    # ── Transport (T) ─────────────────────────────────────────────────────────
    ("T", "VEH", "TRCK", ["truck", "pickup truck", "four-wheel drive", "4x4"]),
    ("T", "VEH", "BIKE", ["motorcycle", "motorbike", "bike", "moto"]),
]

# ── Spec encoding tables ─────────────────────────────────────────────────────
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
    "lotion": "LO",
    "gel": "GL",
    "drops": "DR",
    "spray": "SP",
    "granules": "GR",
    "syrup": "SY",
    "injection": "IN",
    "infusion": "IF",
}

_MATERIAL_CODES: dict[str, str] = {
    "aluminized": "AL",  "aluminium": "AL",  "aluminum": "AL",
    "cotton": "CT",
    "polyethylene": "PE",
    "polypropylene": "PP",
    "plastic": "PL",
    "rubber": "RB",
    "nylon": "NY",
    "synthetic": "SY",
    "stainless": "SS",
    "steel": "ST",
    "latex": "LX",
    "wool": "WO",
    "fleece": "FL",
}

_SIZE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(kg|g|l|lt|liter|litre|ml|kva|kw|cm|mm)\b",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _cfg(key: str) -> Any:
    return getattr(settings, "IFRC_AGENT", {}).get(key, _DEFAULTS.get(key))


def _schema_name() -> str:
    schema = os.getenv("DMIS_DB_SCHEMA", "public")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        return schema
    logger.warning("Invalid DMIS_DB_SCHEMA %r, defaulting to public", schema)
    return "public"


def _tokenize(value: str) -> list[str]:
    return _TOKEN_RE.findall((value or "").lower())


def _normalize(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9\s\-/]", " ", (value or "").strip().lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _clamp_confidence(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


# ── Circuit breaker ──────────────────────────────────────────────────────────

def _cb_is_open() -> bool:
    state = cache.get(_cfg("CB_REDIS_KEY")) or {}
    return bool(state.get("open"))


def cb_is_open() -> bool:
    return _cb_is_open()


def _cb_record_failure() -> None:
    key = _cfg("CB_REDIS_KEY")
    threshold = int(_cfg("CB_FAILURE_THRESHOLD"))
    reset_timeout = int(_cfg("CB_RESET_TIMEOUT_SECONDS"))
    state = cache.get(key) or {"failures": 0, "open": False}
    state["failures"] = int(state.get("failures", 0)) + 1
    if state["failures"] >= threshold:
        state["open"] = True
        cache.set(key, state, timeout=reset_timeout)
    else:
        cache.set(key, state, timeout=reset_timeout * 2)


def _cb_record_success() -> None:
    cache.delete(_cfg("CB_REDIS_KEY"))


# ── Catalogue lookup ─────────────────────────────────────────────────────────

def _catalogue_lookup(normalized: str) -> tuple[str, str, str, float]:
    """
    Match item name tokens against curated catalogue keywords.
    Returns (group, family, category, confidence).
    """
    tokens = set(_tokenize(normalized))
    best_score = 0.0
    best: tuple[str, str, str] | None = None

    for group, family, category, keywords in _CATALOGUE:
        for kw in keywords:
            kw_tokens = set(_tokenize(kw))
            if not kw_tokens:
                continue
            overlap = kw_tokens & tokens
            if not overlap:
                continue
            if kw_tokens <= tokens:
                # Full multi-word phrase matched — weight by specificity
                score = len(kw_tokens) + 1.0
            else:
                # Partial — fraction of keyword tokens present
                score = len(overlap) / len(kw_tokens)

            if score > best_score:
                best_score = score
                best = (group, family, category)

    if best and best_score > 0:
        confidence = 0.85 if best_score >= 2.0 else 0.75 if best_score >= 1.0 else 0.65
        g, f, c = best
        return g, f, c, confidence

    # Fallback: keyword-based group detection, generic family/category
    group = _classify_group_fallback(tokens)
    return group, "GEN", "GENR", 0.50


def _classify_group_fallback(tokens: set[str]) -> str:
    """Rule-based group assignment when no catalogue entry matches."""
    if tokens & {"compress", "bandage", "gauze", "syringe", "glove", "dressing"}:
        return "M"
    if tokens & {"drug", "medicine", "tablet", "capsule", "antibiotic", "paracetamol", "vaccine"}:
        return "D"
    if tokens & {"water", "hygiene", "latrine", "sanitation", "soap", "chlorine", "jerrycan"}:
        return "W"
    if tokens & {"tent", "tarpaulin", "tarp", "blanket", "sleeping", "shelter"}:
        return "H"
    if tokens & {"food", "rice", "flour", "oil", "cereal", "biscuit", "meat", "fish", "bean"}:
        return "F"
    if tokens & {"generator", "battery", "batteries", "solar", "lantern", "torch", "fuel"}:
        return "E"
    if tokens & {"radio", "communication", "satellite", "telecom", "walkie"}:
        return "C"
    if tokens & {"vehicle", "truck", "motorcycle", "transport"}:
        return "T"
    if tokens & {"paper", "pen", "pencil", "stationery", "office"}:
        return "A"
    if tokens & {"kit", "module", "set"} and len(tokens) <= 4:
        return "K"
    return "K"


# ── Spec encoding ────────────────────────────────────────────────────────────

def _encode_size(size_weight: str) -> str:
    """Encode size/weight to 1-3 char code. '200g' → '20G', '5L' → '5L'."""
    if not size_weight:
        return ""
    m = _SIZE_RE.search(size_weight.lower())
    if m:
        number = float(m.group(1))
        unit = m.group(2).lower()
        n = int(round(number))
        if unit == "kg":
            return f"{n}K"[:3]
        if unit == "g":
            return f"{n // 1000}K" if n >= 1000 else str(n)[:3]
        if unit in ("l", "lt", "liter", "litre"):
            return f"{n}L"[:3]
        if unit == "ml":
            return f"{n // 1000}L" if n >= 1000 else f"{n}M"[:3]
        if unit == "cm":
            return f"{n}C"[:3]
        if unit == "mm":
            return f"{n}M"[:3]
        if unit in ("kva", "kw"):
            return f"{n}K"[:3]
    digits = re.sub(r"[^\d]", "", size_weight)[:3]
    return digits


def _encode_spec(size_weight: str, form: str, material: str) -> str:
    """
    Build Specifications segment prefix (0-5 chars).
    Mirrors real IFRC codes: [form/material (2 letters)] + [size (1-3 chars)]
    """
    parts: list[str] = []

    # Form code (2 letters) takes priority over material
    if form:
        fc = _FORM_CODES.get(form.lower().strip())
        if fc:
            parts.append(fc)

    # Material code (2 letters) when no form given
    if not parts and material:
        for key, code in _MATERIAL_CODES.items():
            if key in material.lower():
                parts.append(code)
                break

    sc = _encode_size(size_weight)
    if sc:
        parts.append(sc)

    return "".join(parts)[:5]


# ── Sequence / collision check ────────────────────────────────────────────────

def _next_sequence(prefix_with_spec: str) -> tuple[int, str]:
    """
    Find the smallest unused 2-digit sequence for codes matching
    prefix_with_spec + NN.  Returns (seq, reason).
    """
    try:
        schema = _schema_name()
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT item_code FROM {schema}.item WHERE item_code LIKE %s ORDER BY item_code",
                [f"{prefix_with_spec.upper()}%"],
            )
            rows = cursor.fetchall()
    except DatabaseError as exc:
        logger.warning("Collision check failed for %s: %s", prefix_with_spec, exc)
        return 1, "DB check failed; defaulted to 01."

    used: set[int] = set()
    pat = re.compile(rf"^{re.escape(prefix_with_spec.upper())}(\d{{1,2}})$")
    for (code,) in rows:
        m = pat.match(str(code or "").strip().upper())
        if m:
            used.add(int(m.group(1)))

    for candidate in range(1, 100):
        if candidate not in used:
            return candidate, f"SEQ={candidate:02d} after {len(rows)} collision checks."
    return 0, "No sequence available in 01-99 for this prefix."


# ── Main agent ───────────────────────────────────────────────────────────────

class IFRCAgent:
    """IFRC v3 code-construction agent."""

    def suggest(
        self,
        item_name: str,
        *,
        size_weight: str = "",
        form: str = "",
        material: str = "",
    ) -> IFRCCodeSuggestion:
        normalized = _normalize(item_name)
        if not normalized:
            return IFRCCodeSuggestion(
                confidence=0.0,
                match_type="none",
                construction_rationale="No usable input after normalization.",
            )

        group, family, category, confidence = _catalogue_lookup(normalized)
        llm_used = False

        # Optional LLM refinement
        if _cfg("LLM_ENABLED") and not _cb_is_open():
            llm_result = self._try_llm_classify(normalized)
            if llm_result:
                group, family, category, confidence = llm_result
                llm_used = True
                _cb_record_success()

        spec_segment = _encode_spec(size_weight, form, material)
        prefix8 = f"{group}{family}{category}".upper()
        search_prefix = f"{prefix8}{spec_segment}".upper()

        sequence, seq_reason = _next_sequence(search_prefix)
        if sequence == 0:
            return IFRCCodeSuggestion(
                confidence=0.0,
                match_type="none",
                construction_rationale=f"Prefix {search_prefix}: no sequence available.",
                group_code=group,
                family_code=family,
                category_code=category,
                spec_segment=spec_segment,
            )

        final_code = f"{search_prefix}{sequence:02d}"
        group_label = _GROUP_LABELS.get(group, group)
        rationale = (
            f"Group={group} ({group_label}), Family={family}, "
            f"Category={category}, Spec={spec_segment or 'none'}, {seq_reason}"
        )

        return IFRCCodeSuggestion(
            ifrc_code=final_code,
            ifrc_description=normalized[:120].upper(),
            confidence=_clamp_confidence(confidence),
            match_type="generated" if llm_used else "fallback",
            construction_rationale=rationale[:500],
            llm_used=llm_used,
            group_code=group,
            family_code=family,
            category_code=category,
            spec_segment=spec_segment,
            sequence=sequence,
        )

    def _try_llm_classify(
        self, normalized: str
    ) -> tuple[str, str, str, float] | None:
        """Attempt LLM classification; return None on any failure."""
        try:
            from langchain.chat_models import init_chat_model  # type: ignore

            catalogue_index = {
                f"{g}{f}{c}": kws[:2] for g, f, c, kws in _CATALOGUE
            }
            prompt = (
                "Select the best IFRC catalogue prefix for this disaster-relief item.\n"
                f"Item: {normalized}\n"
                f"Available prefixes (prefix: sample keywords): {json.dumps(catalogue_index)}\n"
                "Return JSON only: group_code (1 letter), family_code (3 letters), "
                "category_code (4 letters), confidence (0-1), reason (string)."
            )
            llm = init_chat_model(
                model=str(_cfg("OLLAMA_MODEL_ID")),
                model_provider="ollama",
                base_url=str(_cfg("OLLAMA_BASE_URL")),
                temperature=0.0,
                format="json",
                request_timeout=int(_cfg("OLLAMA_TIMEOUT_SECONDS")),
            )
            started = time.monotonic()
            raw = llm.invoke(prompt)
            logger.debug("IFRC LLM took %.2fs", time.monotonic() - started)

            payload = json.loads(str(getattr(raw, "content", raw)).strip())
            group = str(payload.get("group_code", "")).upper().strip()
            family = str(payload.get("family_code", "")).upper().strip()
            category = str(payload.get("category_code", "")).upper().strip()
            confidence = _clamp_confidence(float(payload.get("confidence", 0.80)))

            if group not in _GROUP_LABELS:
                return None
            if len(family) != 3 or len(category) != 4:
                return None

            return group, family, category, confidence
        except Exception as exc:
            logger.warning("IFRC LLM failed (%s): %s", type(exc).__name__, exc)
            _cb_record_failure()
            return None
