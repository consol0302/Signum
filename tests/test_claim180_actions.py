from __future__ import annotations

import hashlib
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "examples" / "build_claim180_actions.py"
SPEC = importlib.util.spec_from_file_location("build_claim180_actions", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Claim180ActionPlanTests(unittest.TestCase):
    def test_generated_actions_match_public_plan_and_manifest(self) -> None:
        plan_path = ROOT / "benchmark-protocol" / "claim180-plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        expected = MODULE.build_specs(plan)
        manifest_path = (
            ROOT / "benchmark-protocol" / "claim180-actions-manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(30, len(expected))
        self.assertEqual(plan["case_ids"], list(expected))
        self.assertEqual(plan_path.stat().st_size, manifest["plan_bytes"])
        self.assertEqual(self._sha256(plan_path), manifest["plan_sha256"])
        self.assertEqual(
            plan["case_ids"], [row["case_id"] for row in manifest["cases"]]
        )

        for row in manifest["cases"]:
            path = manifest_path.parent / row["action_file"]
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(expected[row["case_id"]], payload)
            self.assertEqual(path.stat().st_size, row["bytes"])
            self.assertEqual(self._sha256(path), row["sha256"])

    def test_every_case_has_bounded_unique_actions_and_expected_results(self) -> None:
        plan = json.loads(
            (ROOT / "benchmark-protocol" / "claim180-plan.json").read_text(
                encoding="utf-8"
            )
        )
        specs = MODULE.build_specs(plan)

        for case_id, spec in specs.items():
            actions = spec["actions"]
            self.assertGreaterEqual(len(actions), 3, case_id)
            self.assertEqual(
                len(actions), len({action["id"] for action in actions}), case_id
            )
            self.assertTrue(
                all(0 <= action["at_seconds"] < spec["duration_seconds"] for action in actions),
                case_id,
            )
            self.assertTrue(
                all(action["expected_result"] for action in actions), case_id
            )
            self.assertEqual(
                sorted(action["at_seconds"] for action in actions),
                [action["at_seconds"] for action in actions],
                case_id,
            )

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
