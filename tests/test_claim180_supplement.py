from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from signum.evaluation import EvaluationError
from signum.freeze import preregister_claim180_supplement


ROOT = Path(__file__).resolve().parents[1]
BASE_FILES = {
    "preregistration": ROOT
    / "benchmark-protocol"
    / "claim180-preregistration-v3.json",
    "collection_summary": ROOT
    / "benchmark-protocol"
    / "claim180-v3-collection-result.json",
    "event_inventory": ROOT
    / "benchmark-protocol"
    / "claim180-v3-event-inventory.json",
}
IDENTITY_FIELDS = {
    "preregistration": "preregistration_id",
    "collection_summary": "collection_id",
    "event_inventory": "inventory_id",
}


def identity(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {
        "path": path.name,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


class Claim180SupplementPreregistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_context = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_context.name)
        self.actions_root = self.root / "actions"
        self.actions_root.mkdir()
        self.base_references = {}
        for name, source in BASE_FILES.items():
            destination = self.root / source.name
            destination.write_bytes(source.read_bytes())
            payload = json.loads(destination.read_text(encoding="utf-8"))
            self.base_references[name] = {
                **identity(destination),
                "identity": payload[IDENTITY_FIELDS[name]],
            }

    def tearDown(self) -> None:
        self.temp_context.cleanup()

    def test_supplement_lock_binds_deficits_targets_and_actions(self) -> None:
        plan_path = self._write_plan()
        lock = preregister_claim180_supplement(
            plan_path, self.root / "supplement-lock.json"
        )

        self.assertEqual(
            {"action_failure": 19, "loading_completion": 18},
            lock["category_targets"],
        )
        self.assertEqual(37, len(lock["case_ids"]))
        self.assertEqual(37, len(lock["target_events"]))
        self.assertEqual(
            "first_valid_target_event_by_category_in_plan_order",
            lock["collection_selection"]["mode"],
        )
        self.assertTrue(lock["collection_selection"]["retain_all_attempts"])
        self.assertTrue(
            lock["collection_selection"][
                "model_outputs_forbidden_before_selection"
            ]
        )

    def test_supplement_rejects_target_category_not_backed_by_action(self) -> None:
        plan_path = self._write_plan()
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
        payload["target_events"][0]["category"] = "action_failure"
        plan_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(
            EvaluationError, "action_failure targets must preregister"
        ):
            preregister_claim180_supplement(
                plan_path, self.root / "invalid-lock.json"
            )

    def test_supplement_rejects_changed_base_inventory(self) -> None:
        plan_path = self._write_plan()
        inventory = self.root / "claim180-v3-event-inventory.json"
        inventory.write_text("changed after plan creation", encoding="utf-8")

        with self.assertRaisesRegex(EvaluationError, "integrity check failed"):
            preregister_claim180_supplement(
                plan_path, self.root / "tampered-lock.json"
            )

    def _write_plan(self) -> Path:
        case_ids = []
        sources = []
        targets = []
        action_rows = []
        for category, count in (
            ("loading_completion", 18),
            ("action_failure", 19),
        ):
            for index in range(count):
                case_id = f"supp-{category}-{index:02d}"
                action_id = "target"
                expected_result = f"visible {category} result {index}"
                action = {
                    "id": action_id,
                    "at_seconds": 1.0,
                    "type": "wait_for" if category == "loading_completion" else "click",
                    "required": True,
                    "expected_outcome": (
                        "success" if category == "loading_completion" else "failure"
                    ),
                    "expected_result": expected_result,
                }
                action_path = self.actions_root / f"{case_id}.json"
                action_path.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "case_id": case_id,
                            "actions": [action],
                        }
                    ),
                    encoding="utf-8",
                )
                action_identity = identity(action_path)
                case_ids.append(case_id)
                sources.append(
                    {
                        "case_id": case_id,
                        "url": f"https://example.invalid/{case_id}",
                        "goal": f"observe {category}",
                    }
                )
                targets.append(
                    {
                        "case_id": case_id,
                        "action_id": action_id,
                        "category": category,
                        "expected_result": expected_result,
                    }
                )
                action_rows.append(
                    {
                        "case_id": case_id,
                        "action_file": f"actions/{case_id}.json",
                        "bytes": action_identity["bytes"],
                        "sha256": action_identity["sha256"],
                    }
                )
        manifest_path = self.root / "actions-manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "signum_claim180_browser_actions",
                    "collector_revision": "b" * 40,
                    "cases": action_rows,
                }
            ),
            encoding="utf-8",
        )
        manifest_identity = identity(manifest_path)
        category_targets = {"action_failure": 19, "loading_completion": 18}
        plan = {
            "schema_version": 1,
            "kind": "signum_claim180_supplement_plan",
            "protocol_id": "signum-claim180-supplement-test",
            "protocol_repository": "https://example.invalid/signum",
            "protocol_revision": "a" * 40,
            "base_evidence": self.base_references,
            "category_targets": category_targets,
            "case_ids": case_ids,
            "workflow_sources": sources,
            "target_events": targets,
            "actions_manifest": {
                "path": manifest_path.name,
                "bytes": manifest_identity["bytes"],
                "sha256": manifest_identity["sha256"],
            },
            "collection_selection": {
                "mode": "first_valid_target_event_by_category_in_plan_order",
                "validity_source": "independent_capture_verification",
                "retain_all_attempts": True,
                "model_outputs_forbidden_before_selection": True,
                "candidate_count": len(case_ids),
                "category_targets": category_targets,
            },
            "evidence_policy": {"review": "human blind"},
            "observation_budget": {"screenshots": 2},
        }
        plan_path = self.root / "supplement-plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        return plan_path


if __name__ == "__main__":
    unittest.main()
