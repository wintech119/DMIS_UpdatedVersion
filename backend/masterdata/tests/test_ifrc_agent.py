"""
Unit tests for the IFRC code generator agent (v4).
Uses a minimal in-memory taxonomy — no file I/O against the real catalogue,
no Ollama required for keyword-path tests.
"""
import os
import textwrap
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings

from masterdata.ifrc_catalogue_loader import parse_taxonomy, IFRCTaxonomy
from masterdata.ifrc_code_agent import (
    IFRCAgent,
    IFRCCodeSuggestion,
    _extract_item_segment,
    _extract_vrnt_segment,
    _keyword_classify,
    _llm_classify,
    _standardise_description,
    extract_reference_metadata,
)

_BASE_IFRC_SETTINGS = {
    "IFRC_ENABLED": True,
    "LLM_ENABLED": False,
    "TAXONOMY_FILE": "/tmp/test_taxonomy.md",
    "OLLAMA_BASE_URL": "http://localhost:11434",
    "OLLAMA_MODEL_ID": "qwen3.5:0.8b",
    "OLLAMA_TIMEOUT_SECONDS": 8,
    "AUTO_FILL_CONFIDENCE_THRESHOLD": 0.85,
    "MIN_INPUT_LENGTH": 3,
    "MAX_INPUT_LENGTH": 120,
    "CB_FAILURE_THRESHOLD": 5,
    "CB_RESET_TIMEOUT_SECONDS": 120,
    "CB_REDIS_KEY": "ifrc:cb:test",
    "RATE_LIMIT_PER_MINUTE": 30,
}

_TEST_TAXONOMY_MD = textwrap.dedent("""\
    ## GROUP:RE Relief (General Emergency Goods)
    ### FAMILY:HO Household (Bedding, Clothing, Equipment)
    #### CATEGORY:BLKT Blankets and Sleeping
    - ITEM: Blanket, synthetic, medium thermal
    - ITEM: Sleeping bag, lightweight

    #### CATEGORY:NETS Mosquito Nets
    - ITEM: Mosquito net, family size

    ### FAMILY:SH Shelter and Construction
    #### CATEGORY:TARP Tarpaulins and Tents
    - ITEM: Tarpaulin, 4x5 m
    - ITEM: Family tent, 16 m2

    ## GROUP:WS WASH (Water, Sanitation and Hygiene)
    ### FAMILY:WT Water Treatment, Purification and Storage
    #### CATEGORY:WATR Water Containers
    - ITEM: Jerrycan, plastic, 20 L

    #### CATEGORY:PURI Water Purification
    - ITEM: Water purification tablet | FORM=TABLET | MATERIAL=CHLORINE
""")


def _write_temp_taxonomy() -> Path:
    f = NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")
    try:
        f.write(_TEST_TAXONOMY_MD)
        f.flush()
        return Path(f.name)
    finally:
        f.close()


class TestTaxonomyLoader(TestCase):
    def setUp(self):
        self.path = _write_temp_taxonomy()

    def tearDown(self):
        self.path.unlink(missing_ok=True)

    def test_parses_groups(self):
        t = parse_taxonomy(self.path)
        self.assertIn("RE", t.groups)
        self.assertIn("WS", t.groups)

    def test_parses_families(self):
        t = parse_taxonomy(self.path)
        self.assertIn("HO", t.groups["RE"].families)
        self.assertIn("WT", t.groups["WS"].families)

    def test_parses_items(self):
        t = parse_taxonomy(self.path)
        categories = t.groups["RE"].families["HO"].categories
        self.assertIn("BLKT", categories)
        items = categories["BLKT"].items
        self.assertTrue(any("Blanket" in i for i in items))

    def test_parses_item_metadata(self):
        t = parse_taxonomy(self.path)
        category = t.groups["WS"].families["WT"].categories["PURI"]

        self.assertEqual(category.items, ["Water purification tablet"])
        self.assertEqual(
            category.item_metadata["WATER PURIFICATION TABLET"],
            {"FORM": "TABLET", "MATERIAL": "CHLORINE"},
        )

    def test_rejects_item_entry_with_empty_description(self):
        bad_taxonomy = textwrap.dedent("""\
            ## GROUP:WS WASH (Water, Sanitation and Hygiene)
            ### FAMILY:WT Water Treatment, Purification and Storage
            #### CATEGORY:PURI Water Purification
            - ITEM: | FORM=TABLET | MATERIAL=CHLORINE
        """)
        with NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as fh:
            fh.write(bad_taxonomy)
            bad_path = Path(fh.name)
        try:
            with self.assertRaisesMessage(ValueError, "Item description cannot be empty."):
                parse_taxonomy(bad_path)
        finally:
            bad_path.unlink(missing_ok=True)

    def test_keyword_index_built(self):
        t = parse_taxonomy(self.path)
        self.assertGreater(len(t.keyword_index), 0)

    def test_file_not_found_raises(self):
        with self.assertRaises(FileNotFoundError):
            parse_taxonomy(Path("/nonexistent/path.md"))

    def test_empty_file_raises(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# No groups here\n")
            path = Path(f.name)
        try:
            with self.assertRaises(ValueError):
                parse_taxonomy(path)
        finally:
            path.unlink(missing_ok=True)


class TestTaxonomyPathResolution(TestCase):
    def test_uses_django_settings_when_configured(self):
        import masterdata.ifrc_catalogue_loader as loader

        configured_settings = SimpleNamespace(
            configured=True,
            IFRC_AGENT={"TAXONOMY_FILE": "/tmp/settings-taxonomy.md"},
        )
        with patch("django.conf.settings", configured_settings):
            with patch.dict(os.environ, {"IFRC_TAXONOMY_FILE": "/tmp/env-taxonomy.md"}, clear=False):
                self.assertEqual(
                    loader._taxonomy_path_from_settings(),
                    Path("/tmp/settings-taxonomy.md"),
                )

    def test_uses_env_when_django_settings_not_configured(self):
        import masterdata.ifrc_catalogue_loader as loader

        with patch("django.conf.settings", SimpleNamespace(configured=False)):
            with patch.dict(os.environ, {"IFRC_TAXONOMY_FILE": "/tmp/env-taxonomy.md"}, clear=False):
                self.assertEqual(
                    loader._taxonomy_path_from_settings(),
                    Path("/tmp/env-taxonomy.md"),
                )

    def test_uses_bundled_default_when_settings_not_configured_and_env_missing(self):
        import masterdata.ifrc_catalogue_loader as loader

        expected = Path(loader.__file__).resolve().parent / "data" / "ifrc_catalogue_taxonomy.md"
        with patch("django.conf.settings", SimpleNamespace(configured=False)):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("IFRC_TAXONOMY_FILE", None)
                self.assertEqual(loader._taxonomy_path_from_settings(), expected)


class TestKeywordClassifier(TestCase):
    def setUp(self):
        self.path = _write_temp_taxonomy()
        self.taxonomy = parse_taxonomy(self.path)

    def tearDown(self):
        self.path.unlink(missing_ok=True)

    def test_blanket_classified_correctly(self):
        result = _keyword_classify("synthetic blanket medium thermal", self.taxonomy)
        self.assertIsNotNone(result)
        self.assertEqual(result, ("RE", "HO", "BLKT"))

    def test_jerrycan_classified_correctly(self):
        result = _keyword_classify("jerrycan 20 litre plastic", self.taxonomy)
        self.assertIsNotNone(result)
        self.assertEqual(result, ("WS", "WT", "WATR"))

    def test_unknown_item_returns_none(self):
        result = _keyword_classify("xyzzy zork widget", self.taxonomy)
        self.assertIsNone(result)


class TestSegmentExtraction(TestCase):
    def test_item_segment_length(self):
        seg = _extract_item_segment("blanket")
        self.assertEqual(len(seg), 4)

    def test_item_segment_uppercase(self):
        seg = _extract_item_segment("tarpaulin")
        self.assertEqual(seg, seg.upper())

    def test_vrnt_volume(self):
        self.assertEqual(_extract_vrnt_segment("jerrycan 20 litre"), "20L")

    def test_vrnt_material(self):
        self.assertEqual(_extract_vrnt_segment("blanket synthetic"), "SY")

    def test_vrnt_size(self):
        self.assertEqual(_extract_vrnt_segment("mosquito net large"), "LG")

    def test_vrnt_generic_fallback(self):
        self.assertEqual(_extract_vrnt_segment("something unspecified"), "GN")

    def test_vrnt_medium_thermal(self):
        # "medium thermal" should beat plain "medium"
        self.assertEqual(_extract_vrnt_segment("blanket synthetic medium thermal"), "MT")

    def test_extract_reference_metadata_from_description(self):
        metadata = extract_reference_metadata("water purification tablet 500 g plastic")

        self.assertEqual(metadata["form"], "TABLET")
        self.assertEqual(metadata["material"], "PLASTIC")
        self.assertEqual(metadata["size_weight"], "500 G")

    def test_extract_reference_metadata_from_dimension_description(self):
        metadata = extract_reference_metadata("tarpaulin 4x5 m")

        self.assertEqual(metadata["size_weight"], "4X5 M2")

    def test_extract_reference_metadata_from_area_description(self):
        metadata = extract_reference_metadata("family tent 16 m2")

        self.assertEqual(metadata["size_weight"], "16 M2")

    def test_extract_reference_metadata_does_not_treat_linear_meters_as_area(self):
        metadata = extract_reference_metadata("rope 20 m")

        self.assertNotEqual(metadata["size_weight"], "20 M2")
        self.assertIn(metadata["size_weight"], {"", "20 M"})

    def test_extract_reference_metadata_preserves_raw_dimension_value(self):
        metadata = extract_reference_metadata("tarpaulin", size_weight="4 x 5 sq m")

        self.assertEqual(metadata["size_weight"], "4X5 M2")

    def test_extract_reference_metadata_preserves_explicit_material_metadata(self):
        metadata = extract_reference_metadata(
            "water purification tablet, aquatab",
            form="TABLET",
            material="CHLORINE",
        )

        self.assertEqual(metadata["form"], "TABLET")
        self.assertEqual(metadata["material"], "CHLORINE")


class TestIFRCAgent(TestCase):
    def setUp(self):
        self.taxonomy_path = _write_temp_taxonomy()
        import masterdata.ifrc_catalogue_loader as loader
        loader._taxonomy_instance = None

    def tearDown(self):
        self.taxonomy_path.unlink(missing_ok=True)

    def _settings(self):
        cfg = dict(_BASE_IFRC_SETTINGS)
        cfg["TAXONOMY_FILE"] = str(self.taxonomy_path)
        return cfg

    def test_generates_code_via_keywords(self):
        with override_settings(IFRC_AGENT=self._settings()):
            agent  = IFRCAgent()
            result = agent.generate("synthetic blanket medium thermal")

        self.assertIsInstance(result, IFRCCodeSuggestion)
        self.assertIsNotNone(result.item_code)
        self.assertEqual(result.match_type, "generated")
        self.assertFalse(result.llm_used)
        self.assertEqual(len(result.item_code), 12)
        self.assertTrue(result.item_code.startswith("REHO"), result.item_code)
        self.assertEqual(len(result.spec_seg or ""), 4)

    @patch("masterdata.ifrc_code_agent._call_ollama")
    def test_generates_code_via_llm(self, mock_ollama):
        cfg = self._settings()
        cfg["LLM_ENABLED"] = True
        mock_ollama.return_value = {
            "group": "WS", "family": "WT",
            "confidence": 0.88, "rationale": "Water treatment item"
        }
        with override_settings(IFRC_AGENT=cfg):
            agent  = IFRCAgent()
            result = agent.generate("traditional ceramic water filter")

        self.assertEqual(result.match_type, "generated")
        self.assertTrue(result.llm_used)
        self.assertIsNotNone(result.item_code)

    @patch("masterdata.ifrc_code_agent._call_ollama")
    def test_llm_prompt_includes_taxonomy_and_scope_guardrails(self, mock_ollama):
        mock_ollama.return_value = {
            "group": "WS",
            "family": "WT",
            "category": "PURI",
            "confidence": 0.88,
            "rationale": "Water treatment item",
        }
        taxonomy = parse_taxonomy(self.taxonomy_path)

        _llm_classify("traditional ceramic water filter", taxonomy)

        prompt = mock_ollama.call_args.args[0]
        self.assertIn(
            "Choose only from the provided IFRC taxonomy. Do not invent new groups, families, or categories.",
            prompt,
        )
        self.assertIn(
            "Ignore local business-category and unit-of-measure conventions; this task is IFRC classification only.",
            prompt,
        )

    @patch("masterdata.ifrc_code_agent._call_ollama")
    def test_fallback_on_llm_failure(self, mock_ollama):
        cfg = self._settings()
        cfg["LLM_ENABLED"] = True
        mock_ollama.side_effect = Exception("Ollama not running")
        with override_settings(IFRC_AGENT=cfg):
            agent  = IFRCAgent()
            result = agent.generate("xyzzy unclassifiable object")

        self.assertIsInstance(result, IFRCCodeSuggestion)
        self.assertFalse(result.llm_used)

    def test_code_always_uppercase(self):
        with override_settings(IFRC_AGENT=self._settings()):
            agent  = IFRCAgent()
            result = agent.generate("blanket")
        self.assertTrue(result.item_code)
        self.assertEqual(result.item_code, result.item_code.upper())

    def test_code_max_30_chars(self):
        with override_settings(IFRC_AGENT=self._settings()):
            agent  = IFRCAgent()
            result = agent.generate("a very long description of a complex multi-word item type")
        self.assertTrue(result.item_code)
        self.assertLessEqual(len(result.item_code), 30)

    def test_construction_rationale_mentions_all_segments(self):
        with override_settings(IFRC_AGENT=self._settings()):
            agent  = IFRCAgent()
            result = agent.generate("blanket synthetic")
        for segment in ["Group", "Family", "Compact specification"]:
            self.assertIn(segment, result.construction_rationale)

    def test_generated_codes_do_not_use_sequence_suffix(self):
        with override_settings(IFRC_AGENT=self._settings()):
            agent  = IFRCAgent()
            result = agent.generate("blanket synthetic")
        self.assertIsNone(result.seq)
        self.assertEqual(len(result.item_code or ""), 12)

    def test_suggest_compat_shim_works(self):
        """suggest() backward-compat shim should produce the same result as generate()."""
        with override_settings(IFRC_AGENT=self._settings()):
            agent  = IFRCAgent()
            suggested = agent.suggest(
                "blanket",
                size_weight="medium",
                material="synthetic",
            )
            generated = agent.generate(
                "blanket",
                size_weight="medium",
                material="synthetic",
            )

        self.assertTrue(suggested.item_code)
        self.assertEqual(suggested.item_code, generated.item_code)
        self.assertEqual(suggested.standardised_name, generated.standardised_name)
        self.assertEqual(suggested.confidence, generated.confidence)
        self.assertEqual(suggested.grp, generated.grp)
        self.assertEqual(suggested.grp_label, generated.grp_label)
        self.assertEqual(suggested.fam, generated.fam)
        self.assertEqual(suggested.fam_label, generated.fam_label)
        self.assertEqual(suggested.cat, generated.cat)
        self.assertEqual(suggested.cat_label, generated.cat_label)
        self.assertEqual(suggested.spec_seg, generated.spec_seg)
        self.assertEqual(suggested.seq, generated.seq)
        self.assertEqual(suggested.construction_rationale, generated.construction_rationale)
        self.assertEqual(suggested.llm_used, generated.llm_used)
        self.assertEqual(suggested.alternatives, generated.alternatives)


