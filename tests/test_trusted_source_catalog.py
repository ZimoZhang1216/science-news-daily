import unittest
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from docx import Document

import main
from personalization.source_catalog import (
    ALL_PROFILE_KEYS,
    SOURCE_DEFINITIONS,
    TRUSTED_SOURCE_LAYERS,
    collectable_source_ids,
    default_source_ids_for_layers,
    source_definitions_for_profile,
)


REQUIRED_SOURCE_SCOPES = {
    "arxiv": (
        "chemistry", "organic_chemistry", "biology", "statistics", "business_management", "economics",
        "natural_sciences", "engineering", "agriculture", "medicine", "interdisciplinary_studies", "computer_science",
    ),
    "pubmed": ("chemistry", "organic_chemistry", "biology", "statistics", "natural_sciences", "agriculture", "medicine"),
    "crossref": (
        "chemistry", "organic_chemistry", "biology", "statistics", "business_management", "philosophy",
        "economics", "law", "education", "literature", "history", "natural_sciences", "engineering",
        "agriculture", "medicine", "management", "arts", "interdisciplinary_studies", "military_science",
        "computer_science",
    ),
    "rss": ("chemistry", "organic_chemistry", "biology", "statistics", "business_management", "computer_science"),
    "openalex": (
        "chemistry", "organic_chemistry", "biology", "statistics", "business_management", "philosophy",
        "economics", "law", "education", "literature", "history", "natural_sciences", "engineering",
        "agriculture", "medicine", "management", "arts", "interdisciplinary_studies", "military_science",
        "computer_science",
    ),
    "ccf_conferences": ("computer_science",),
    "official_rss": ("computer_science",),
    "github_releases": ("computer_science",),
    "hackernews": ("computer_science",),
    "europe_pmc": ("biology", "medicine"),
    "clinical_trials": ("medicine",),
    "nber_working_papers": ("economics", "management", "business_management"),
    "mit_csail_news": ("computer_science",),
    "psycinfo_metadata": ("medicine", "education"),
    "iso_standards_metadata": ("engineering", "computer_science", "management"),
    "zbmath": ("statistics", "natural_sciences"),
    "project_euclid": ("statistics", "natural_sciences"),
    "ims": ("statistics",),
    "asa": ("statistics",),
    "nasa_ads": ("natural_sciences", "engineering", "interdisciplinary_studies"),
    "cern": ("natural_sciences", "engineering"),
    "esa": ("natural_sciences", "engineering"),
    "nasa": ("natural_sciences", "engineering"),
    "aps": ("natural_sciences",),
    "aip": ("natural_sciences", "engineering"),
    "acs": ("chemistry", "organic_chemistry"),
    "rsc": ("chemistry", "organic_chemistry"),
    "nature_chemistry": ("chemistry", "organic_chemistry"),
    "chemistry_world": ("chemistry", "organic_chemistry"),
    "energy_agencies": ("chemistry", "organic_chemistry", "engineering", "natural_sciences", "management"),
    "energy_standards": ("chemistry", "organic_chemistry", "natural_sciences", "engineering", "management"),
    "who": (
        "biology", "medicine", "agriculture", "economics", "law", "education", "management",
        "business_management", "interdisciplinary_studies",
    ),
    "cdc": ("biology", "medicine"),
    "nih": ("biology", "medicine"),
    "cochrane": ("medicine",),
    "biorxiv": ("biology", "medicine", "agriculture", "natural_sciences"),
    "medrxiv": ("biology", "medicine"),
    "openreview": ("computer_science", "statistics", "interdisciplinary_studies"),
    "dblp": ("computer_science",),
    "semantic_scholar": ("computer_science", "interdisciplinary_studies", "natural_sciences"),
    "papers_with_code": ("computer_science",),
    "acm": ("computer_science", "engineering"),
    "ieee": ("computer_science", "engineering"),
    "usenix": ("computer_science",),
    "3gpp": ("engineering", "computer_science"),
    "ietf": ("engineering", "computer_science"),
    "itu": ("engineering", "computer_science", "management"),
    "etsi": ("engineering", "computer_science"),
    "asme": ("engineering",),
    "sae": ("engineering",),
    "faa": ("engineering",),
    "industrial_automation_associations": ("engineering", "computer_science", "management"),
    "transport_departments": ("engineering", "management", "business_management", "law"),
    "transport_associations": ("engineering", "management", "business_management"),
    "ipcc": ("natural_sciences", "engineering", "agriculture", "interdisciplinary_studies", "management"),
    "unep": ("natural_sciences", "engineering", "agriculture", "interdisciplinary_studies", "management"),
    "earthdata": ("natural_sciences", "engineering", "agriculture"),
    "usgs": ("natural_sciences", "engineering", "agriculture"),
    "noaa": ("natural_sciences", "engineering", "agriculture", "interdisciplinary_studies"),
    "wmo": ("natural_sciences", "engineering", "agriculture", "interdisciplinary_studies"),
    "copernicus": ("natural_sciences", "engineering", "agriculture"),
    "national_science_agencies": ("natural_sciences", "engineering", "agriculture", "medicine"),
    "fao": ("agriculture", "economics", "management", "interdisciplinary_studies"),
    "usda": ("agriculture", "economics", "management"),
    "cgiar": ("agriculture", "natural_sciences", "interdisciplinary_studies"),
    "national_statistics": (
        "statistics", "economics", "law", "education", "agriculture", "medicine", "management", "business_management",
        "interdisciplinary_studies",
    ),
    "international_statistics": ("statistics", "economics", "education", "management", "business_management", "interdisciplinary_studies"),
    "fred": ("economics", "management", "business_management"),
    "imf": ("economics", "management", "business_management"),
    "world_bank": ("economics", "law", "management", "business_management", "agriculture", "interdisciplinary_studies"),
    "oecd": ("economics", "law", "management", "business_management", "education"),
    "bis": ("economics", "management", "business_management"),
    "central_banks": ("economics", "law", "management", "business_management"),
    "fiscal_regulators": ("economics", "law", "management", "business_management"),
    "cepr": ("economics", "management", "business_management"),
    "repec": ("economics", "management", "business_management"),
    "ssrn": ("economics", "law", "management", "business_management"),
    "exchanges": ("economics", "management", "business_management"),
    "government_legislation": ("law", "management", "military_science", "interdisciplinary_studies"),
    "judicial_opinions": ("law",),
    "united_nations": ("law", "education", "history", "interdisciplinary_studies", "military_science"),
    "wto": ("economics", "law", "management", "business_management"),
    "think_tanks": ("law", "economics", "management", "interdisciplinary_studies", "military_science"),
    "eric": ("education",),
    "unesco": ("education", "history", "arts", "interdisciplinary_studies"),
    "unicef": ("education", "medicine", "interdisciplinary_studies"),
    "wvs": ("education", "economics", "management", "interdisciplinary_studies"),
    "doaj": ("philosophy", "education", "literature", "history", "arts", "interdisciplinary_studies"),
    "jstor_metadata": ("philosophy", "literature", "history", "arts"),
    "open_library": ("philosophy", "literature", "history", "arts"),
    "dpla": ("philosophy", "literature", "history", "arts"),
    "national_libraries": ("literature", "history", "arts"),
    "museums_heritage": ("history", "arts", "literature"),
}


class TrustedSourceCatalogueTests(unittest.TestCase):
    def test_catalogue_has_the_complete_literal_required_source_scope_matrix(self) -> None:
        """Every specified source must have one independently reviewable, exact profile scope."""

        actual_scopes = {source.id: source.profile_scope for source in SOURCE_DEFINITIONS}

        self.assertEqual(actual_scopes, REQUIRED_SOURCE_SCOPES)

    def test_catalogue_does_not_misrepresent_legacy_discovery_as_profile_scope(self) -> None:
        """Legacy IDs remain runnable without falsely displaying them for unrelated disciplines."""

        literature_ids = {source.id for source in source_definitions_for_profile("literature")}
        medicine_ids = {source.id for source in source_definitions_for_profile("medicine")}

        self.assertNotIn("pubmed", literature_ids)
        self.assertNotIn("hackernews", literature_ids)
        self.assertNotIn("hackernews", medicine_ids)
        for profile_key in ALL_PROFILE_KEYS:
            if profile_key == "computer_science":
                continue
            with self.subTest(profile_key=profile_key):
                self.assertNotIn(
                    "hackernews",
                    {source.id for source in source_definitions_for_profile(profile_key)},
                )
        self.assertIn("pubmed", main.available_source_ids("literature"))
        self.assertIn("hackernews", main.available_source_ids("literature"))

    def test_every_catalogue_record_has_complete_policy_fields(self) -> None:
        """A displayed source must never lose its trust, access, or fallback contract."""

        for source in SOURCE_DEFINITIONS:
            with self.subTest(source_id=source.id):
                self.assertTrue(source.id)
                self.assertTrue(source.chinese_name)
                self.assertIn(source.layer, TRUSTED_SOURCE_LAYERS)
                self.assertTrue(source.profile_scope)
                self.assertTrue(source.topic_scope)
                self.assertTrue(source.acquisition_method)
                self.assertTrue(source.key_requirement)
                self.assertTrue(source.update_cadence)
                self.assertIn(source.credibility, range(1, 6))
                self.assertTrue(source.access_label)
                self.assertTrue(source.access_notice)
                self.assertTrue(source.fallback)
                if source.default_enabled:
                    self.assertTrue(source.collectable)
                    self.assertEqual(source.access_label, "公开可用")
                if source.access_label == "需要授权":
                    self.assertFalse(source.default_enabled)
                if source.layer == "community_signal":
                    self.assertFalse(source.default_enabled)

    def test_jstor_metadata_allows_public_metadata_selection_despite_full_text_restrictions(self) -> None:
        """The catalogue must distinguish public bibliographic metadata from gated full text."""

        jstor = {source.id: source for source in SOURCE_DEFINITIONS}["jstor_metadata"]

        self.assertTrue(jstor.collectable)
        self.assertEqual(jstor.access_label, "公开可用")
        self.assertIn("全文", jstor.access_notice)
        self.assertIn("授权", jstor.access_notice)

    def test_available_source_ids_accepts_legacy_profile_dicts_without_a_key(self) -> None:
        """Persisted or ad-hoc legacy dictionaries must not require catalogue metadata."""

        legacy_ids = main.available_source_ids({"arxiv_query_terms": ["quantum"]})

        self.assertEqual(legacy_ids, ("arxiv", "pubmed", "openalex", "hackernews"))

    def test_copernicus_public_default_is_not_labelled_as_authorised_only(self) -> None:
        """A public default source cannot present a contradictory authorisation boundary."""

        copernicus = {source.id: source for source in SOURCE_DEFINITIONS}["copernicus"]

        self.assertTrue(copernicus.collectable)
        self.assertTrue(copernicus.default_enabled)
        self.assertEqual(copernicus.access_label, "公开可用")

    def test_medical_catalogue_separates_public_papers_from_restricted_indexes(self) -> None:
        """A login-only index must never look like an executable public paper source."""

        sources = {source.id: source for source in source_definitions_for_profile("medicine")}

        self.assertEqual(sources["europe_pmc"].layer, "academic_research")
        self.assertFalse(sources["psycinfo_metadata"].collectable)
        self.assertEqual(sources["psycinfo_metadata"].access_label, "需要授权")

    def test_catalogue_records_are_immutable_and_include_every_evidence_layer(self) -> None:
        """Source policy must remain stable when callers build selection controls."""

        sources = source_definitions_for_profile("computer_science")

        self.assertEqual(
            TRUSTED_SOURCE_LAYERS,
            (
                "official_data_policy",
                "academic_research",
                "institutional_research",
                "industry_engineering",
                "community_signal",
            ),
        )
        self.assertEqual({source.layer for source in sources}, set(TRUSTED_SOURCE_LAYERS))
        with self.assertRaises(FrozenInstanceError):
            sources[0].chinese_name = "changed"  # type: ignore[misc]

    def test_layer_defaults_exclude_restricted_and_community_sources(self) -> None:
        """Automatic defaults must not silently opt users into gated or community sources."""

        default_ids = default_source_ids_for_layers(
            "medicine",
            ("academic_research", "community_signal"),
        )

        self.assertIn("europe_pmc", default_ids)
        self.assertNotIn("psycinfo_metadata", default_ids)
        self.assertNotIn("hackernews", default_ids)
        self.assertTrue(set(default_ids).issubset(collectable_source_ids()))

    def test_available_source_ids_preserve_legacy_profile_sources(self) -> None:
        """Existing profile versions keep their established source IDs after catalogue adoption."""

        source_ids = main.available_source_ids("computer_science")

        self.assertTrue(
            {
                "arxiv",
                "pubmed",
                "crossref",
                "rss",
                "openalex",
                "ccf_conferences",
                "official_rss",
                "hackernews",
                "github_releases",
            }.issubset(source_ids)
        )

    def test_available_source_ids_keep_legacy_ids_and_registered_catalogue_feeds(self) -> None:
        """A registered RSS source is selectable; a source without a collector is not."""

        source_ids = set(main.available_source_ids("business_management"))
        self.assertTrue({"arxiv", "pubmed", "crossref", "openalex", "hackernews"}.issubset(source_ids))
        self.assertIn("nber_working_papers", source_ids)
        self.assertNotIn("rss", source_ids)
        # NASA ADS is catalogued but needs a token and has no registered
        # collector, so it must remain a transparent directory entry.
        self.assertNotIn("nasa_ads", main.available_source_ids("natural_sciences"))
        self.assertEqual(
            main.available_source_ids({"rss_feeds": []}),
            ("arxiv", "pubmed", "openalex", "hackernews"),
        )

    def test_document_separates_all_evidence_layers_and_keeps_community_distinct(self) -> None:
        """The Word renderer must never present community content as peer evidence."""

        layer_sources = (
            ("clinical_trials", "官方登记"),
            ("arxiv", "论文预印本"),
            ("nber_working_papers", "机构报告"),
            ("github_releases", "工程发布"),
            ("hackernews", "社区讨论"),
        )
        items = [
            main.NewsItem(
                title=title,
                source=source_id,
                published=datetime(2026, 7, 30, tzinfo=UTC),
                link=f"https://example.test/{source_id}",
                source_id=source_id,
                source_layer=main.source_provenance(source_id)[0],
                field_name="人工智能与机器学习",
                item_id=str(index),
                comment=title,
            )
            for index, (source_id, title) in enumerate(layer_sources)
        ]
        with TemporaryDirectory() as directory:
            output = main.create_document(
                items, {"top_ids": ["4"], "field_summaries": []}, date(2026, 7, 30),
                Path(directory), main.resolve_profile("computer_science"),
            )
            rendered = "\n".join(paragraph.text for paragraph in Document(output).paragraphs)

        headings = [main.SOURCE_LAYER_LABELS[layer] for layer in TRUSTED_SOURCE_LAYERS]
        self.assertEqual([rendered.index(heading) for heading in headings], sorted(rendered.index(heading) for heading in headings))
        highlights = rendered.split("分领域摘要", 1)[0]
        self.assertNotIn("社区讨论", highlights)
        self.assertIn("社区信号（可信度 1/5）", rendered)


if __name__ == "__main__":
    unittest.main()
