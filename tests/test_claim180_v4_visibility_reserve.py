from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_example(name: str):
    path = ROOT / "examples" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_example("build_claim180_v4_visibility_reserve.py")
PLAN_MODULE = load_example("build_claim180_v4_visibility_reserve_plan.py")
PREREGISTER_MODULE = load_example("preregister_claim180_v4_visibility_reserve.py")


class Claim180V4VisibilityReserveTests(unittest.TestCase):
    def test_published_reserve_matches_builder(self) -> None:
        sources, manifest, actions = MODULE.build(
            ROOT / "benchmark-protocol" / "actions-v4",
            ROOT / "benchmark-protocol" / "actions-v4-visibility-reserve",
            ROOT / "benchmark-protocol" / "claim180-v4-visibility-reserve-sources.json",
            ROOT / "benchmark-protocol" / "claim180-v4-visibility-reserve-actions-manifest.json",
            check=True,
            round_number=1,
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

    def test_second_round_uses_new_ids_after_preserved_startup_failures(self) -> None:
        sources, manifest, _ = MODULE.build(
            ROOT / "benchmark-protocol" / "actions-v4",
            ROOT / "benchmark-protocol" / "actions-v4-visibility-reserve-v2",
            ROOT / "benchmark-protocol" / "claim180-v4-visibility-reserve-sources-v2.json",
            ROOT / "benchmark-protocol" / "claim180-v4-visibility-reserve-actions-manifest-v2.json",
            check=True,
            round_number=2,
        )
        failure = json.loads(
            (ROOT / "benchmark-protocol" / "claim180-v4-visibility-reserve-collection-result.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(8, failure["counts"]["startup_failed"])
        self.assertFalse(failure["claim180_collection_complete"])
        self.assertEqual(2, sources["reserve_round"])
        self.assertTrue(all(case_id.startswith("v4r2-") for case_id in sources["case_ids"]))
        self.assertEqual(8, manifest["candidate_count"])
        plan_path = ROOT / "benchmark-protocol" / "claim180-v4-visibility-reserve-plan-v2.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        rebuilt_plan = PLAN_MODULE.build_plan(
            ROOT / "benchmark-protocol", plan["protocol_revision"], 2
        )
        self.assertEqual(plan, rebuilt_plan)
        self.assertEqual(
            failure["collection_id"],
            plan["base_evidence"]["failed_reserve_v1"]["identity"],
        )
        preregistration = json.loads(
            (ROOT / "benchmark-protocol" / "claim180-v4-visibility-reserve-preregistration-v2.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(plan["case_ids"], preregistration["case_ids"])
        self.assertEqual(2, plan["reserve_round"])

    def test_plan_and_preregistration_freeze_conditional_activation(self) -> None:
        plan_path = (
            ROOT
            / "benchmark-protocol"
            / "claim180-v4-visibility-reserve-plan.json"
        )
        preregistration_path = (
            ROOT
            / "benchmark-protocol"
            / "claim180-v4-visibility-reserve-preregistration.json"
        )
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        preregistration = json.loads(
            preregistration_path.read_text(encoding="utf-8")
        )
        rebuilt = PLAN_MODULE.build_plan(
            ROOT / "benchmark-protocol", plan["protocol_revision"]
        )
        self.assertEqual(plan, rebuilt)
        self.assertEqual(2, plan["activation"]["reviewer_count"])
        self.assertTrue(plan["activation"]["adjudication_required"])
        self.assertTrue(
            plan["activation"]["reserve_use_forbidden_before_confirmation"]
        )
        self.assertTrue(
            plan["activation"]["method_outputs_forbidden_before_activation"]
        )
        self.assertFalse(
            plan["anchor_policy"]["exact_before_after_png_identity_allowed"]
        )
        self.assertEqual(
            plan["activation"]["required_v4_event_keys"],
            preregistration["activation"]["required_v4_event_keys"],
        )
        rebuilt_lock = PREREGISTER_MODULE.preregister(plan_path)
        for key, value in preregistration.items():
            if key not in {"created_at_utc", "preregistration_id"}:
                self.assertEqual(value, rebuilt_lock[key])
        expected_id = PREREGISTER_MODULE.fingerprint(
            {
                key: value
                for key, value in preregistration.items()
                if key not in {"created_at_utc", "preregistration_id"}
            }
        )
        self.assertEqual(expected_id, preregistration["preregistration_id"])


if __name__ == "__main__":
    unittest.main()
