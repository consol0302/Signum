from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "examples" / "audit_claim180_label_capacity.py"
SPEC = importlib.util.spec_from_file_location(
    "audit_claim180_label_capacity", MODULE_PATH
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Claim180LabelCapacityTests(unittest.TestCase):
    def test_audit_does_not_invent_transitions_or_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            captures = root / "captures" / "case-1"
            captures.mkdir(parents=True)
            summary = root / "summary.json"
            plan = root / "plan.json"
            summary.write_text(
                json.dumps(
                    {
                        "collection_id": "collection",
                        "selection": {"selected_case_ids": ["case-1"]},
                    }
                ),
                encoding="utf-8",
            )
            plan.write_text(
                json.dumps(
                    {
                        "category_targets": {
                            "action_success": 2,
                            "action_failure": 2,
                        }
                    }
                ),
                encoding="utf-8",
            )
            (captures / "capture.json").write_text(
                json.dumps(
                    {
                        "case_id": "case-1",
                        "actions": [
                            {
                                "id": "success",
                                "status": "completed",
                                "expected_outcome": "success",
                            },
                            {
                                "id": "rejected",
                                "status": "completed",
                                "expected_outcome": "failure",
                            },
                            {
                                "id": "missing",
                                "status": "failed",
                                "expected_outcome": "failure",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = MODULE.audit(summary, root / "captures", plan)

            self.assertEqual(3, result["conservative_action_anchored_transition_capacity"])
            self.assertEqual(1, result["event_transition_deficit"])
            self.assertEqual(2, result["preregistered_expected_failure_actions"])
            self.assertEqual(0, result["action_failure_deficit"])
            self.assertFalse(result["claim180_ready_for_labeling"])


if __name__ == "__main__":
    unittest.main()
