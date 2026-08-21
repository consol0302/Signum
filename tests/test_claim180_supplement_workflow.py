from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from signum.freeze import preregister_claim180_supplement


ROOT = Path(__file__).resolve().parents[1]


def load_example(name: str):
    path = ROOT / "examples" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLAN_MODULE = load_example("build_claim180_supplement_plan.py")
SUMMARY_MODULE = load_example("summarize_claim180_supplement_collection.py")


class Claim180SupplementWorkflowTests(unittest.TestCase):
    def test_real_candidate_plan_is_accepted_by_acquisition_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            plan_path = temporary_root / "supplement-plan.json"
            plan = PLAN_MODULE.build_plan(
                base_preregistration_path=ROOT
                / "benchmark-protocol"
                / "claim180-preregistration-v3.json",
                base_collection_path=ROOT
                / "benchmark-protocol"
                / "claim180-v3-collection-result.json",
                base_inventory_path=ROOT
                / "benchmark-protocol"
                / "claim180-v3-event-inventory.json",
                sources_path=ROOT
                / "benchmark-protocol"
                / "claim180-supplement-sources.json",
                targets_path=ROOT
                / "benchmark-protocol"
                / "claim180-supplement-targets.json",
                actions_manifest_path=ROOT
                / "benchmark-protocol"
                / "claim180-supplement-actions-manifest.json",
                output_path=plan_path,
                protocol_repository="https://github.com/consol0302/Signum",
                protocol_revision="6f9dbd67e682c6e168e5b87a478e3cb768cf9fff",
            )
            plan_path.write_text(
                json.dumps(plan, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            lock = preregister_claim180_supplement(
                plan_path, temporary_root / "supplement-lock.json"
            )

            self.assertEqual(52, len(lock["case_ids"]))
            self.assertEqual(
                {"action_failure": 19, "loading_completion": 18},
                lock["category_targets"],
            )

    def test_summary_selects_first_valid_event_in_each_category(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            collection_root = root / "captures"
            collection_root.mkdir()
            categories = ["loading_completion"] * 18 + ["action_failure"] * 20
            case_ids = [f"case-{index:02d}" for index in range(len(categories))]
            targets = []
            for index, (case_id, category) in enumerate(
                zip(case_ids, categories, strict=True)
            ):
                targets.append(
                    {
                        "case_id": case_id,
                        "action_id": "target",
                        "category": category,
                        "expected_result": f"visible result {index}",
                    }
                )
                case_root = collection_root / case_id
                case_root.mkdir()
                capture = {
                    "schema_version": 1,
                    "case_id": case_id,
                    "actions": [
                        {
                            "id": "target",
                            "status": "completed",
                            "expected_outcome": (
                                "failure"
                                if category == "action_failure"
                                else "success"
                            ),
                            "scheduled_at_seconds": 1.0,
                            "started_at_seconds": 1.01,
                            "completed_at_seconds": 1.1,
                        }
                    ],
                }
                (case_root / "capture.json").write_text(
                    json.dumps(capture), encoding="utf-8"
                )
                valid = not (category == "action_failure" and index == 18)
                verification = {
                    "schema_version": 1,
                    "case_id": case_id,
                    "valid": valid,
                    "integrity_valid": valid,
                    "policy_valid": valid,
                    "policy_reasons": [] if valid else ["test invalid"],
                }
                (case_root / "verification.json").write_text(
                    json.dumps(verification), encoding="utf-8"
                )
            plan = {
                "schema_version": 1,
                "kind": "signum_claim180_supplement_plan",
                "case_ids": case_ids,
                "target_events": targets,
                "category_targets": {
                    "action_failure": 19,
                    "loading_completion": 18,
                },
                "collection_selection": {
                    "mode": "first_valid_target_event_by_category_in_plan_order"
                },
            }
            plan_path = root / "plan.json"
            plan_path.write_text(
                json.dumps(plan, sort_keys=True) + "\n", encoding="utf-8"
            )
            preregistration = {
                "schema_version": 1,
                "kind": "signum_claim180_supplement_preregistration",
                "preregistration_id": "lock-id",
                "plan_bytes": plan_path.stat().st_size,
                "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                "case_ids": case_ids,
                "target_events": targets,
                "collection_selection": plan["collection_selection"],
            }
            preregistration_path = root / "lock.json"
            preregistration_path.write_text(
                json.dumps(preregistration), encoding="utf-8"
            )

            summary = SUMMARY_MODULE.build_summary(
                collection_root, plan_path, preregistration_path
            )

            self.assertTrue(summary["claim180_supplement_complete"])
            self.assertEqual(37, summary["counts"]["valid"])
            self.assertEqual(1, summary["counts"]["invalid"])
            selected = summary["selection"]["selected_case_ids_by_category"]
            self.assertNotIn("case-18", selected["action_failure"])
            self.assertEqual(19, len(selected["action_failure"]))
            self.assertEqual(18, len(selected["loading_completion"]))

    def test_summary_never_selects_an_unverified_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            collection_root = root / "captures"
            case_root = collection_root / "only-case"
            case_root.mkdir(parents=True)
            (case_root / "capture.json").write_text(
                json.dumps(
                    {
                        "case_id": "only-case",
                        "actions": [
                            {
                                "id": "target",
                                "status": "completed",
                                "started_at_seconds": 1.0,
                                "completed_at_seconds": 1.1,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            target = {
                "case_id": "only-case",
                "action_id": "target",
                "category": "loading_completion",
                "expected_result": "visible",
            }
            plan = {
                "kind": "signum_claim180_supplement_plan",
                "case_ids": ["only-case"],
                "target_events": [target],
                "category_targets": {"loading_completion": 1},
                "collection_selection": {"mode": "test"},
            }
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            lock = {
                "kind": "signum_claim180_supplement_preregistration",
                "preregistration_id": "lock",
                "plan_bytes": plan_path.stat().st_size,
                "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                "case_ids": ["only-case"],
                "target_events": [target],
                "collection_selection": {"mode": "test"},
            }
            lock_path = root / "lock.json"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")

            summary = SUMMARY_MODULE.build_summary(
                collection_root, plan_path, lock_path
            )

            self.assertFalse(summary["claim180_supplement_complete"])
            self.assertEqual(1, summary["counts"]["unverified"])
            self.assertEqual({}, summary["selection"]["selected_case_ids_by_category"])


if __name__ == "__main__":
    unittest.main()
