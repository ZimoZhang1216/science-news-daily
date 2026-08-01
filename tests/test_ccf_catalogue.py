import unittest

import main
from personalization.ccf_catalogue import CCF_CATALOGUE_VERSION, conferences_for_tiers


class CcfCatalogueTests(unittest.TestCase):
    def test_catalogue_has_current_ai_and_database_a_tier_venues(self) -> None:
        venues = {venue.abbreviation for venue in conferences_for_tiers(("A",))}

        self.assertTrue({"AAAI", "NeurIPS", "SIGMOD", "VLDB"}.issubset(venues))

    def test_catalogue_filters_to_the_selected_tier_scope(self) -> None:
        a_venues = {venue.abbreviation for venue in conferences_for_tiers(("A",))}
        ab_venues = {venue.abbreviation for venue in conferences_for_tiers(("A", "B"))}
        abc_venues = {venue.abbreviation for venue in conferences_for_tiers(("A", "B", "C"))}

        self.assertNotIn("EMNLP", a_venues)
        self.assertIn("EMNLP", ab_venues)
        self.assertNotIn("AISTATS", ab_venues)
        self.assertIn("AISTATS", abc_venues)

    def test_catalogue_declares_the_current_ccf_release(self) -> None:
        self.assertEqual(CCF_CATALOGUE_VERSION, "CCF 2026 第七版")

    def test_ccf_source_is_available_only_for_computer_science(self) -> None:
        self.assertIn("ccf_conferences", main.available_source_ids("computer_science"))
        self.assertNotIn("ccf_conferences", main.available_source_ids("statistics"))

