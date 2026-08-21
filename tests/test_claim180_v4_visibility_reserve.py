from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "examples" / "build_claim180_v4_visibility_reserve.py"
SPEC = importlib.util.spec_from_file_location("build_visibility_reserve", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Claim180V4VisibilityReserveTests(unittest.TestCase):
    def test_published_reserve_matches_builder(self) -> None:
        sources, manifest, actions = MODULE.build(
            ROOT / "benchmark-protocol" / "actions-v4",
            ROOT / "benchmark-protocol" / "actions-v4-visibility-reserve",
            ROOT / "benchmark-protocol" / "claim180-v4-visibility-reserve-sources.json",
            ROOT / "benchmark-protocol" / "claim180-v4-visibility-reserve-actions-manifest.json",
            check=True,
        )
        self.assertEqual(8, manifest["candidate_count"])
        self.assertEqual(2, manifest["slot_count"])
        self.assertEqual(8, len(actions))
        self.assertEqual(2, sources["activation_deficit"]["count"])

    def test_reserve_has_four_fresh_candidates_per_slot(self) -> None:
        sources = json.loads(
            (ROOT / "benchmark-protocol" / "claim180-v4-visibility-reserve-sources.json").read_text(
                encoding="utf-8"
            )
        )
        original = json.loads(
            (ROOT / "benchmark-protocol" / "claim180-v4-collection-result.json").read_text(
                encoding="utf-8"
            )
        )
        original_ids = {row["case_id"] for row in original["cases"]}
        self.assertEqual(2, len(sources["slots"]))
        for slot in sources["slots"]:
            self.assertEqual(4, len(slot["candidate_ids"]))
            self.assertTrue(original_ids.isdisjoint(slot["candidate_ids"]))
        for target in sources["target_events"]:
            self.assertEqual(
                [{"action_id": target["events"][0]["action_id"], "category": "cursor_hover_focus"}],
                target["events"],
            )


if __name__ == "__main__":
    unittest.main()
