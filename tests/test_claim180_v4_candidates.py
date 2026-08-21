from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from signum.evaluation import CLAIM180_TARGETS


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "examples" / "build_claim180_v4_candidates.py"
SPEC = importlib.util.spec_from_file_location(
    "build_claim180_v4_candidates", MODULE_PATH
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Claim180V4CandidateTests(unittest.TestCase):
    def test_pool_has_thirty_balanced_slots_and_three_fresh_domains(self) -> None:
        candidates = MODULE.build_candidates()

        self.assertEqual(60, len(candidates))
        self.assertEqual(60, len({row["case_id"] for row in candidates}))
        domains = Counter(urlparse(row["url"]).netloc for row in candidates)
        self.assertEqual(
            {
                "playwrightlab.github.io": 20,
                "qapracticehub.com": 20,
                "testpages.eviltester.com": 20,
            },
            dict(domains),
        )
        totals = Counter()
        for index in range(0, 60, 2):
            pair = candidates[index : index + 2]
            self.assertEqual(pair[0]["slot_id"], pair[1]["slot_id"])
            templates = [
                [event["category"] for event in row["target_events"]]
                for row in pair
            ]
            self.assertEqual(templates[0], templates[1])
            totals.update(templates[0])
        self.assertEqual(CLAIM180_TARGETS, dict(totals))

    def test_targets_are_unique_bounded_actions_with_matching_outcomes(self) -> None:
        supported = {
            "click",
            "double_click",
            "fill",
            "press",
            "select",
            "check",
            "uncheck",
            "hover",
            "scroll",
            "reload",
            "navigate",
            "wait_for",
        }
        for candidate in MODULE.build_candidates():
            actions = candidate["actions"]
            action_ids = [row["id"] for row in actions]
            target_ids = [row["action_id"] for row in candidate["target_events"]]
            self.assertEqual(len(action_ids), len(set(action_ids)), candidate["case_id"])
            self.assertEqual(6, len(target_ids), candidate["case_id"])
            self.assertEqual(6, len(set(target_ids)), candidate["case_id"])
            self.assertTrue(set(target_ids).issubset(action_ids), candidate["case_id"])
            self.assertEqual(
                [row["at_seconds"] for row in actions],
                sorted(row["at_seconds"] for row in actions),
                candidate["case_id"],
            )
            action_index = {row["id"]: row for row in actions}
            for action in actions:
                self.assertIn(action["type"], supported)
                self.assertLess(action["at_seconds"], candidate["duration_seconds"])
                self.assertTrue(action["expected_result"])
            for target in candidate["target_events"]:
                failed = action_index[target["action_id"]]["expected_outcome"] == "failure"
                self.assertEqual(target["category"] == "action_failure", failed)

    def test_generated_outputs_bind_sources_actions_and_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources.json"
            actions = root / "actions"
            manifest = root / "manifest.json"
            MODULE.build_outputs(
                sources,
                actions,
                manifest,
                "a" * 40,
                check=False,
            )
            MODULE.build_outputs(
                sources,
                actions,
                manifest,
                "a" * 40,
                check=True,
            )
            source_payload = json.loads(sources.read_text(encoding="utf-8"))
            manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(30, len(source_payload["slots"]))
            self.assertEqual(60, len(source_payload["target_events"]))
            self.assertEqual(60, manifest_payload["candidate_count"])
            self.assertEqual(30, manifest_payload["slot_count"])
            self.assertEqual(
                source_payload["case_ids"],
                [row["case_id"] for row in manifest_payload["cases"]],
            )


if __name__ == "__main__":
    unittest.main()
