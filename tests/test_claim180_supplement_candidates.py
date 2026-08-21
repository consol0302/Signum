from __future__ import annotations

from collections import Counter
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "examples" / "build_claim180_supplement_candidates.py"
SPEC = importlib.util.spec_from_file_location(
    "build_claim180_supplement_candidates", MODULE_PATH
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Claim180SupplementCandidateTests(unittest.TestCase):
    def test_candidate_pool_has_fixed_category_capacity_and_diversity(self) -> None:
        candidates = [
            *MODULE.build_loading_candidates(),
            *MODULE.build_failure_candidates(),
        ]
        counts = Counter(row["category"] for row in candidates)
        domains = Counter(urlparse(row["url"]).netloc for row in candidates)

        self.assertEqual(52, len(candidates))
        self.assertEqual(52, len({row["case_id"] for row in candidates}))
        self.assertEqual(
            {"loading_completion": 26, "action_failure": 26},
            dict(counts),
        )
        self.assertGreaterEqual(len(domains), 5)
        self.assertGreaterEqual(
            sum(count > 1 for count in domains.values()),
            4,
        )

    def test_target_events_are_single_bounded_transitions(self) -> None:
        candidates = [
            *MODULE.build_loading_candidates(),
            *MODULE.build_failure_candidates(),
        ]
        for candidate in candidates:
            actions = candidate["actions"]
            action_ids = [row["id"] for row in actions]
            self.assertEqual(len(action_ids), len(set(action_ids)))
            self.assertEqual(
                [row["at_seconds"] for row in actions],
                sorted(row["at_seconds"] for row in actions),
            )
            targets = [
                row
                for row in actions
                if row["id"] == candidate["target_action_id"]
            ]
            self.assertEqual(1, len(targets), candidate["case_id"])
            target = targets[0]
            self.assertLess(target["at_seconds"], candidate["duration_seconds"])
            self.assertTrue(target["expected_result"])
            if candidate["category"] == "loading_completion":
                self.assertEqual("wait_for", target["type"])
                self.assertEqual("success", target["expected_outcome"])
            else:
                self.assertEqual("failure", target["expected_outcome"])

    def test_generated_catalogs_and_action_hashes_match_builder(self) -> None:
        candidates = [
            *MODULE.build_loading_candidates(),
            *MODULE.build_failure_candidates(),
        ]
        sources_path = (
            ROOT / "benchmark-protocol" / "claim180-supplement-sources.json"
        )
        targets_path = (
            ROOT / "benchmark-protocol" / "claim180-supplement-targets.json"
        )
        manifest_path = (
            ROOT
            / "benchmark-protocol"
            / "claim180-supplement-actions-manifest.json"
        )
        sources = json.loads(sources_path.read_text(encoding="utf-8"))
        targets = json.loads(targets_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        expected_ids = [row["case_id"] for row in candidates]
        self.assertEqual(expected_ids, sources["case_ids"])
        self.assertEqual(
            expected_ids,
            [row["case_id"] for row in targets["target_events"]],
        )
        self.assertEqual(
            expected_ids,
            [row["case_id"] for row in manifest["cases"]],
        )
        self.assertEqual(
            self._sha256(sources_path), manifest["source_catalog"]["sha256"]
        )
        self.assertEqual(
            self._sha256(targets_path), manifest["target_catalog"]["sha256"]
        )
        target_by_case = {
            row["case_id"]: row for row in targets["target_events"]
        }
        candidate_by_case = {row["case_id"]: row for row in candidates}
        for row in manifest["cases"]:
            action_path = manifest_path.parent / row["action_file"]
            action_payload = json.loads(action_path.read_text(encoding="utf-8"))
            candidate = candidate_by_case[row["case_id"]]
            target = target_by_case[row["case_id"]]
            target_action = next(
                action
                for action in action_payload["actions"]
                if action["id"] == target["action_id"]
            )
            self.assertEqual(candidate["actions"], action_payload["actions"])
            self.assertEqual(target["category"], candidate["category"])
            self.assertEqual(
                target["expected_result"], target_action["expected_result"]
            )
            self.assertEqual(action_path.stat().st_size, row["bytes"])
            self.assertEqual(self._sha256(action_path), row["sha256"])

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
