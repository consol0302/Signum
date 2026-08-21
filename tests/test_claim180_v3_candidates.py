from __future__ import annotations

import hashlib
import importlib.util
import json
import unittest
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "examples" / "build_claim180_v3_candidates.py"
SPEC = importlib.util.spec_from_file_location(
    "build_claim180_v3_candidates", MODULE_PATH
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Claim180V3CandidateTests(unittest.TestCase):
    def test_v3_plan_and_preregistration_bind_ordered_selection(self) -> None:
        plan_path = ROOT / "benchmark-protocol" / "claim180-plan-v3.json"
        preregistration_path = (
            ROOT / "benchmark-protocol" / "claim180-preregistration-v3.json"
        )
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        preregistration = json.loads(
            preregistration_path.read_text(encoding="utf-8")
        )

        self.assertEqual(45, len(plan["case_ids"]))
        self.assertEqual(
            {
                "mode": "first_valid_in_plan_order",
                "validity_source": "independent_capture_verification",
                "retain_all_attempts": True,
                "model_outputs_forbidden_before_selection": True,
                "required_valid_cases": 30,
                "candidate_count": 45,
            },
            plan["collection_selection"],
        )
        self.assertEqual(plan["collection_selection"], preregistration["collection_selection"])
        self.assertEqual(plan["case_ids"], preregistration["case_ids"])
        self.assertEqual(plan_path.stat().st_size, preregistration["plan_bytes"])
        self.assertEqual(self._sha256(plan_path), preregistration["plan_sha256"])
        expected_id = hashlib.sha256(
            json.dumps(
                {
                    key: value
                    for key, value in preregistration.items()
                    if key not in {"created_at_utc", "preregistration_id"}
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(expected_id, preregistration["preregistration_id"])

    def test_public_candidate_pool_and_action_hashes_are_frozen(self) -> None:
        candidates = MODULE.build_candidates()
        sources_path = ROOT / "benchmark-protocol" / "claim180-v3-sources.json"
        manifest_path = (
            ROOT / "benchmark-protocol" / "claim180-v3-actions-manifest.json"
        )
        sources = json.loads(sources_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(45, len(candidates))
        self.assertEqual(45, len({row["case_id"] for row in candidates}))
        self.assertEqual(
            [row["case_id"] for row in candidates], sources["case_ids"]
        )
        self.assertEqual(sources_path.stat().st_size, manifest["source_catalog"]["bytes"])
        self.assertEqual(self._sha256(sources_path), manifest["source_catalog"]["sha256"])
        self.assertEqual(
            sources["case_ids"], [row["case_id"] for row in manifest["cases"]]
        )
        domains = Counter(urlparse(row["url"]).netloc for row in candidates)
        self.assertGreaterEqual(len(domains), 3)
        self.assertGreaterEqual(min(domains.values()), 10)

        for row in manifest["cases"]:
            action_path = manifest_path.parent / row["action_file"]
            payload = json.loads(action_path.read_text(encoding="utf-8"))
            candidate = next(
                item for item in candidates if item["case_id"] == row["case_id"]
            )
            self.assertEqual(candidate["url"], payload["source_url"])
            self.assertEqual(candidate["goal"], payload["goal"])
            self.assertEqual(candidate["actions"], payload["actions"])
            self.assertEqual(action_path.stat().st_size, row["bytes"])
            self.assertEqual(self._sha256(action_path), row["sha256"])

    def test_every_candidate_uses_only_supported_bounded_actions(self) -> None:
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
            "wait_for",
        }
        for candidate in MODULE.build_candidates():
            actions = candidate["actions"]
            self.assertGreaterEqual(len(actions), 2, candidate["case_id"])
            self.assertEqual(
                len(actions), len({row["id"] for row in actions}), candidate["case_id"]
            )
            self.assertEqual(
                [row["at_seconds"] for row in actions],
                sorted(row["at_seconds"] for row in actions),
                candidate["case_id"],
            )
            self.assertTrue(
                all(
                    0 <= row["at_seconds"] < candidate["duration_seconds"]
                    and row["type"] in supported
                    and row["expected_result"]
                    for row in actions
                ),
                candidate["case_id"],
            )

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
