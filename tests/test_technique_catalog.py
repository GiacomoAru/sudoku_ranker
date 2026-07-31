import unittest
from dataclasses import replace

import numpy as np

from sudoku_app.core import difficulty
from sudoku_app.core import technique_catalog as catalog
from sudoku_app.core import technique_registry
from sudoku_app.core import techniques
from sudoku_app.core.data_structure import SudokuState


class TechniqueCatalogStructureTests(unittest.TestCase):
    def test_catalog_is_internally_valid(self):
        self.assertEqual(
            catalog.validate_catalog(),
            catalog.TECHNIQUE_DEFINITIONS,
        )

    def test_ids_and_canonical_names_are_unique(self):
        definitions = catalog.TECHNIQUE_DEFINITIONS
        self.assertEqual(
            len({definition.id for definition in definitions}),
            len(definitions),
        )
        self.assertEqual(
            len({
                definition.canonical_name.casefold()
                for definition in definitions
            }),
            len(definitions),
        )

    def test_representative_ids_are_stable(self):
        expected = {
            "Last Value": "single.last_value",
            "X-Wing": "fish.basic.2",
            "Skyscraper": "sdp.skyscraper",
            "Unique Rectangle Type 1": "unique.ur.1",
            "Forcing Chain": "se.forcing_chain",
            "Nested Forcing Chain": "nested.forcing_chain",
            "Complete Forcing Tree": "forcing.complete_tree",
        }
        self.assertEqual(
            {
                name: catalog.resolve_technique(name).id
                for name in expected
            },
            expected,
        )

    def test_generated_views_cover_the_same_definitions(self):
        canonical_names = {
            definition.canonical_name
            for definition in catalog.TECHNIQUE_DEFINITIONS
        }
        self.assertEqual(set(catalog.TECHNIQUE_DIFFICULTY), canonical_names)
        self.assertEqual(set(catalog.TECHNIQUE_FAMILY), canonical_names)
        self.assertEqual(set(catalog.TECHNIQUE_STRATEGY), canonical_names)
        self.assertIs(
            difficulty.TECHNIQUE_DIFFICULTY,
            catalog.TECHNIQUE_DIFFICULTY,
        )
        self.assertIs(
            techniques.TECHNIQUE_FAMILY,
            catalog.TECHNIQUE_FAMILY,
        )
        registered_logic_ids = {
            technique_id
            for runner in technique_registry.TECHNIQUE_RUNNERS
            if runner.engine_type != "local"
            for technique_id in runner.technique_ids
        }
        catalog_logic_ids = {
            definition.id
            for definition in catalog.TECHNIQUE_DEFINITIONS
            if definition.engine_type != "local"
        }
        self.assertEqual(
            registered_logic_ids,
            catalog_logic_ids,
        )

    def test_every_parent_is_resolvable(self):
        for definition in catalog.TECHNIQUE_DEFINITIONS:
            with self.subTest(technique_id=definition.id):
                if definition.parent_id is not None:
                    self.assertIn(definition.parent_id, catalog.TECHNIQUE_BY_ID)
                if definition.se_equivalent_parent_id is not None:
                    self.assertIn(
                        definition.se_equivalent_parent_id,
                        catalog.TECHNIQUE_BY_ID,
                    )

    def test_aliases_are_resolved_case_insensitively(self):
        self.assertEqual(
            catalog.resolve_technique(" full   house ").id,
            "single.last_value",
        )
        self.assertEqual(
            catalog.resolve_technique("ur1").id,
            "unique.ur.1",
        )

    def test_complete_tree_has_its_own_taxonomy_and_legacy_aliases(self):
        definition = catalog.technique_definition("forcing.complete_tree")
        self.assertEqual(definition.canonical_name, "Complete Forcing Tree")
        self.assertEqual(definition.family_id, "exhaustive_forcing")
        self.assertEqual(definition.strategy_id, "last_resort")
        self.assertEqual(definition.rating_kind, "project")
        self.assertEqual(definition.base_difficulty, 13.0)
        self.assertEqual(definition.engine_type, "complete_tree")
        self.assertEqual(definition.fallback_tier, 2)
        self.assertEqual(
            catalog.resolve_legacy_technique("Nested Forcing Chain").id,
            "forcing.complete_tree",
        )
        self.assertEqual(
            catalog.resolve_legacy_technique(
                "Nested Contradiction Forcing Chain"
            ).id,
            "forcing.complete_tree",
        )
        self.assertEqual(
            catalog.resolve_technique("Nested Forcing Chain").id,
            "nested.forcing_chain",
        )

    def test_alias_collision_requires_different_namespaces(self):
        template = catalog.TECHNIQUE_DEFINITIONS[0]
        first = replace(
            template,
            id="test.first",
            canonical_name="Test First",
            aliases=(catalog.TechniqueAlias("Shared", "source-a"),),
            detector_id="test_first",
            priority=1,
        )
        second_same_namespace = replace(
            template,
            id="test.second",
            canonical_name="Test Second",
            aliases=(catalog.TechniqueAlias("Shared", "source-a"),),
            detector_id="test_second",
            priority=2,
        )
        with self.assertRaises(catalog.CatalogValidationError):
            catalog.validate_catalog((first, second_same_namespace))

        second_other_namespace = replace(
            second_same_namespace,
            aliases=(catalog.TechniqueAlias("Shared", "source-b"),),
        )
        self.assertEqual(
            catalog.validate_catalog((first, second_other_namespace)),
            (first, second_other_namespace),
        )


class TechniqueCatalogRegistryTests(unittest.TestCase):
    @staticmethod
    def _registry():
        return {
            runner.detector_id: runner.technique_ids
            for runner in technique_registry.TECHNIQUE_RUNNERS
        }

    def test_real_detector_registry_matches_catalog(self):
        self.assertTrue(
            catalog.validate_detector_registry(self._registry())
        )

    def test_every_registered_detector_declares_techniques(self):
        for runner in technique_registry.TECHNIQUE_RUNNERS:
            with self.subTest(detector_id=runner.detector_id):
                self.assertTrue(runner.technique_ids)

    def test_missing_implemented_detector_is_rejected(self):
        registry = self._registry()
        registry.pop("last_value")
        with self.assertRaises(catalog.CatalogValidationError):
            catalog.validate_detector_registry(registry)

    def test_move_contains_catalog_identity(self):
        state = SudokuState(np.zeros((9, 9), dtype=int))
        state.candidates = [[set() for _ in range(9)] for _ in range(9)]
        state.candidates[0][0] = {7}

        move = techniques.naked_single(state)[0]

        self.assertEqual(move["technique_id"], "single.naked")
        self.assertIsNone(move["parent_id"])
        self.assertEqual(move["rating_kind"], "se")


if __name__ == "__main__":
    unittest.main()
