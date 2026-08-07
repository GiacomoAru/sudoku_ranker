"""Test minimo per lo scalino di ricerca P17 (search_tier).

Verifica che ogni tecnica del catalogo abbia uno scalino valido e che i
casi guida della discussione P17 (Kraken nel forcing, ALS locale vs ALS
chain-shaped, Unique Loop vs UR locale) siano classificati correttamente.
"""

import unittest

from sudoku_app.core import technique_catalog as tc


class SearchTierTests(unittest.TestCase):
    def test_every_technique_has_a_valid_search_tier(self):
        for definition in tc.TECHNIQUE_DEFINITIONS:
            self.assertIn(definition.search_tier, tc.SEARCH_TIERS, definition.id)

    def test_search_tier_is_monotone_with_strategy_progression(self):
        # Le tecniche elementari e i subset/intersezioni restano tier 0.
        self.assertEqual(tc.TECHNIQUE_CATALOG["single.naked"].search_tier, 0)
        self.assertEqual(tc.TECHNIQUE_CATALOG["subset.naked.4"].search_tier, 0)

        # Fish e Skyscraper/2-String Kite sono pattern a cifra singola
        # (tier 1), ma Kraken è forcing (tier 4) pur condividendo
        # family_id == "fish".
        self.assertEqual(tc.TECHNIQUE_CATALOG["fish.basic.3"].search_tier, 1)
        self.assertEqual(tc.TECHNIQUE_CATALOG["sdp.skyscraper"].search_tier, 1)
        self.assertEqual(
            tc.TECHNIQUE_CATALOG["kraken.fish.type1"].search_tier, 4
        )

        # ALS locale (RCC singolo, XY-Wing) è multi-cifra (tier 2); ALS
        # Chain, Death Blossom e ALS-AIC sono chain-shaped (tier 3).
        self.assertEqual(tc.TECHNIQUE_CATALOG["als.xz.single"].search_tier, 2)
        self.assertEqual(tc.TECHNIQUE_CATALOG["als.xy_wing"].search_tier, 2)
        self.assertEqual(tc.TECHNIQUE_CATALOG["als.chain"].search_tier, 3)
        self.assertEqual(
            tc.TECHNIQUE_CATALOG["als.death_blossom"].search_tier, 3
        )
        self.assertEqual(tc.TECHNIQUE_CATALOG["chain.als_aic"].search_tier, 3)

        # Unique Rectangle/BUG locali restano tier 2; Unique Loop è
        # chain-shaped.
        self.assertEqual(tc.TECHNIQUE_CATALOG["unique.ur.1"].search_tier, 2)
        self.assertEqual(tc.TECHNIQUE_CATALOG["unique.loop.1"].search_tier, 3)

        # Static chains, forcing avanzato, Nested e Complete Tree salgono
        # ordinatamente da 3 a 6.
        self.assertEqual(tc.TECHNIQUE_CATALOG["chain.aic"].search_tier, 3)
        self.assertEqual(tc.TECHNIQUE_CATALOG["forcing.dynamic"].search_tier, 4)
        self.assertEqual(
            tc.TECHNIQUE_CATALOG["nested.contradiction"].search_tier, 5
        )
        self.assertEqual(
            tc.TECHNIQUE_CATALOG["forcing.complete_tree"].search_tier, 6
        )


if __name__ == "__main__":
    unittest.main()
