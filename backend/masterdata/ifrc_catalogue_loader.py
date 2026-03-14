"""
DMIS IFRC Catalogue Taxonomy Loader
=====================================
Parses ifrc_catalogue_taxonomy.md into structured Python dicts for the agent.

Expected MD format:
    ## GROUP:<G>   <Label>       — 1-letter Group (real IFRC groups A-X)
    ### FAMILY:<FAM> <Label>     — 3-letter Family code
    #### CATEGORY:<CAT> <Label>  — 4-letter Category code
    - ITEM: <description>        — representative item (keyword source)

Code structure produced:
    GROUP(1) + FAMILY(3) + CATEGORY(4) + SPEC(0-7) + SEQ(02) = max 17 chars

This is the ONLY file that reads the taxonomy MD.
To update the catalogue: edit ifrc_catalogue_taxonomy.md, then run
    python manage.py reload_ifrc_taxonomy
No code changes needed.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("dmis.ifrc.loader")


@dataclass
class CategoryDef:
    code:  str
    label: str
    items: list[str] = field(default_factory=list)
    item_metadata: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass
class FamilyDef:
    code:       str
    label:      str
    categories: dict[str, CategoryDef] = field(default_factory=dict)


@dataclass
class GroupDef:
    code:     str
    label:    str
    families: dict[str, FamilyDef] = field(default_factory=dict)


@dataclass
class IFRCTaxonomy:
    """
    Parsed IFRC catalogue taxonomy. Immutable after construction.
    keyword_index maps lowercase keywords -> (group, family, category).
    """
    groups:        dict[str, GroupDef]
    keyword_index: dict[str, tuple[str, str, str]] = field(default_factory=dict)

    # ── Lookup helpers ────────────────────────────────────────────────────────

    def group_label(self, grp: str) -> str:
        return self.groups.get(grp, GroupDef(grp, grp)).label

    def family_label(self, grp: str, fam: str) -> str:
        g = self.groups.get(grp)
        if not g:
            return fam
        return g.families.get(fam, FamilyDef(fam, fam)).label

    def category_label(self, grp: str, fam: str, cat: str) -> str:
        g = self.groups.get(grp)
        if not g:
            return cat
        f = g.families.get(fam)
        if not f:
            return cat
        return f.categories.get(cat, CategoryDef(cat, cat)).label

    def families_for_group(self, grp: str) -> dict[str, FamilyDef]:
        return self.groups.get(grp, GroupDef(grp, grp)).families

    def categories_for_family(self, grp: str, fam: str) -> dict[str, CategoryDef]:
        g = self.groups.get(grp)
        if not g:
            return {}
        return g.families.get(fam, FamilyDef(fam, fam)).categories

    def all_groups_text(self) -> str:
        return "\n".join(
            f"  {code}: {g.label}"
            for code, g in self.groups.items()
        )

    def all_families_text(self) -> str:
        lines = []
        for grp_code, g in self.groups.items():
            for fam_code, f in g.families.items():
                lines.append(f"  {grp_code}/{fam_code}: {f.label}")
        return "\n".join(lines)

    def all_categories_text(self) -> str:
        lines = []
        for grp_code, g in self.groups.items():
            for fam_code, f in g.families.items():
                for cat_code, c in f.categories.items():
                    lines.append(f"  {grp_code}/{fam_code}/{cat_code}: {c.label}")
        return "\n".join(lines)

    def items_for_category(self, grp: str, fam: str, cat: str) -> list[str]:
        g = self.groups.get(grp)
        if not g:
            return []
        f = g.families.get(fam)
        if not f:
            return []
        c = f.categories.get(cat)
        return c.items if c else []


# ─── Parser ───────────────────────────────────────────────────────────────────

_GROUP_RE    = re.compile(r"^##\s+GROUP:([A-Z]{1,4})\s+(.+)$")
_FAMILY_RE   = re.compile(r"^###\s+FAMILY:([A-Z]{1,6})\s+(.+)$")
_CATEGORY_RE = re.compile(r"^####\s+CATEGORY:([A-Z]{1,6})\s+(.+)$")
_ITEM_RE     = re.compile(r"^-\s+ITEM:\s+(.+)$")
_ITEM_METADATA_RE = re.compile(r"^([A-Z_]+)\s*=\s*(.+)$")
_ITEM_METADATA_KEYS = frozenset({"IFRC_CODE", "SIZE_WEIGHT", "FORM", "MATERIAL", "SPEC_SEGMENT"})


def _normalize_item_metadata_key(item_desc: str) -> str:
    return " ".join(str(item_desc or "").strip().upper().split())


def _parse_item_entry(raw_entry: str) -> tuple[str, dict[str, str]]:
    parts = [part.strip() for part in str(raw_entry or "").split("|")]
    item_desc = parts[0] if parts else ""
    item_desc = item_desc.strip()
    if item_desc == "":
        raise ValueError("Item description cannot be empty.")
    metadata: dict[str, str] = {}
    for part in parts[1:]:
        if not part:
            continue
        match = _ITEM_METADATA_RE.fullmatch(part)
        if not match:
            raise ValueError(f"Invalid item metadata segment: {part!r}")
        key = match.group(1).strip().upper()
        value = match.group(2).strip()
        if key not in _ITEM_METADATA_KEYS:
            raise ValueError(f"Unsupported item metadata key: {key!r}")
        if value:
            metadata[key] = value
    return item_desc, metadata


def parse_taxonomy(md_path: Path) -> IFRCTaxonomy:
    """
    Parse the taxonomy MD into an IFRCTaxonomy object.
    Raises FileNotFoundError if the file is missing.
    Raises ValueError if no groups are parsed or if parsed structure has
    no categories/items.
    """
    if not md_path.exists():
        raise FileNotFoundError(
            f"IFRC taxonomy file not found: {md_path}\n"
            "Check the IFRC_TAXONOMY_FILE env var or settings.IFRC_AGENT['TAXONOMY_FILE']."
        )

    groups:          dict[str, GroupDef]    = {}
    current_group:   GroupDef   | None      = None
    current_family:  FamilyDef  | None      = None
    current_category: CategoryDef | None    = None

    with md_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip()

            m = _GROUP_RE.match(line)
            if m:
                code, label = m.group(1).strip(), m.group(2).strip()
                current_group    = GroupDef(code=code, label=label)
                current_family   = None
                current_category = None
                groups[code]     = current_group
                continue

            m = _FAMILY_RE.match(line)
            if m and current_group:
                code, label = m.group(1).strip(), m.group(2).strip()
                current_family   = FamilyDef(code=code, label=label)
                current_category = None
                current_group.families[code] = current_family
                continue

            m = _CATEGORY_RE.match(line)
            if m and current_family:
                code, label = m.group(1).strip(), m.group(2).strip()
                current_category = CategoryDef(code=code, label=label)
                current_family.categories[code] = current_category
                continue

            m = _ITEM_RE.match(line)
            if m and current_category:
                item_desc, item_metadata = _parse_item_entry(m.group(1).strip())
                current_category.items.append(item_desc)
                if item_metadata:
                    current_category.item_metadata[_normalize_item_metadata_key(item_desc)] = item_metadata

    if not groups:
        raise ValueError(
            f"No groups parsed from taxonomy file: {md_path}\n"
            "Verify the file uses '## GROUP:X Label' heading format."
        )

    taxonomy = IFRCTaxonomy(groups=groups)
    taxonomy.keyword_index = _build_keyword_index(taxonomy)

    n_groups    = len(groups)
    n_families  = sum(len(g.families) for g in groups.values())
    n_categories = sum(
        len(f.categories)
        for g in groups.values()
        for f in g.families.values()
    )
    n_items = sum(
        len(c.items)
        for g in groups.values()
        for f in g.families.values()
        for c in f.categories.values()
    )
    zero_counts: list[str] = []
    if n_categories == 0:
        zero_counts.append("n_categories")
    if n_items == 0:
        zero_counts.append("n_items")
    if zero_counts:
        raise ValueError(
            "Invalid IFRCTaxonomy parsed from taxonomy file "
            f"{md_path}: zero value in {', '.join(zero_counts)} "
            f"(n_categories={n_categories}, n_items={n_items}) before "
            "_build_keyword_index can produce a usable keyword index."
        )
    logger.info(
        "IFRC taxonomy loaded: %d groups, %d families, %d categories, %d items, %d keywords",
        n_groups, n_families, n_categories, n_items, len(taxonomy.keyword_index),
    )
    return taxonomy


def _build_keyword_index(
    taxonomy: IFRCTaxonomy,
) -> dict[str, tuple[str, str, str]]:
    """
    Map lowercase item keywords -> (grp, fam, cat).
    Bigrams indexed first (more specific); single words second.
    First-match wins so more specific entries are not overwritten.
    """
    index: dict[str, tuple[str, str, str]] = {}
    stop = {
        "a", "an", "the", "and", "or", "for", "with", "without", "per",
        "set", "kit", "type", "size", "colour", "color", "standard",
        "basic", "complete", "various", "other", "assorted", "each",
        "sterile", "disposable", "generic",
    }
    for grp_code, g in taxonomy.groups.items():
        for fam_code, f in g.families.items():
            for cat_code, c in f.categories.items():
                triple = (grp_code, fam_code, cat_code)
                for item_desc in c.items:
                    words = [
                        w.lower()
                        for w in re.findall(r"[a-zA-Z]{3,}", item_desc)
                        if w.lower() not in stop
                    ]
                    # Bigrams first
                    for i in range(len(words) - 1):
                        bigram = f"{words[i]} {words[i + 1]}"
                        if bigram not in index:
                            index[bigram] = triple
                    # Single words
                    for w in words[:5]:
                        if w not in index:
                            index[w] = triple
    return index


# ─── Thread-safe singleton ────────────────────────────────────────────────────

_taxonomy_instance: IFRCTaxonomy | None = None
_taxonomy_path: Path | None = None
_taxonomy_lock = threading.Lock()


def _taxonomy_path_from_settings() -> Path:
    from django.conf import settings

    default_path = Path(__file__).resolve().parent / "data" / "ifrc_catalogue_taxonomy.md"
    env_path = os.environ.get("IFRC_TAXONOMY_FILE")
    path_raw = None
    if getattr(settings, "configured", False):
        agent_cfg = getattr(settings, "IFRC_AGENT", {}) or {}
        path_raw = agent_cfg.get("TAXONOMY_FILE")
    path_raw = path_raw or env_path or str(default_path)
    return Path(path_raw)


def get_taxonomy() -> IFRCTaxonomy:
    """Returns the singleton IFRCTaxonomy, parsing the MD file on first call."""
    global _taxonomy_instance, _taxonomy_path
    path = _taxonomy_path_from_settings()

    if _taxonomy_instance is not None and _taxonomy_path == path:
        return _taxonomy_instance

    with _taxonomy_lock:
        if _taxonomy_instance is None or _taxonomy_path != path:
            _taxonomy_instance = parse_taxonomy(path)
            _taxonomy_path = path

    return _taxonomy_instance


def reload_taxonomy() -> IFRCTaxonomy:
    """Force re-parse of the MD file. Thread-safe."""
    global _taxonomy_instance, _taxonomy_path
    with _taxonomy_lock:
        _taxonomy_instance = None
        _taxonomy_path = None
    return get_taxonomy()

