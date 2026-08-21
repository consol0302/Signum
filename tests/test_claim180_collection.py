from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "examples" / "summarize_claim180_collection.py"
SPEC = importlib.util.spec_from_file_location(
    "summarize_claim180_collection", MODULE_PATH
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Claim180CollectionSummaryTests(unittest.TestCase):
    def test_summary_selects_first_valid_candidate_per_slot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            captures = root / "captures"
            captures.mkdir()
            case_ids = ["s1-primary", "s1-alternate", "s2-primary", "s2-alternate"]
            selection = {
                "mode": "first_valid_per_slot_in_plan_order",
                "candidate_count": 4,
                "required_valid_cases": 2,
                "validity_source": "independent_capture_verification",
                "retain_all_attempts": True,
                "model_outputs_forbidden_before_selection": True,
                "slots": [
                    {
                        "slot_id": "slot-1",
                        "candidate_ids": ["s1-primary", "s1-alternate"],
                    },
                    {
                        "slot_id": "slot-2",
                        "candidate_ids": ["s2-primary", "s2-alternate"],
                    },
                ],
            }
            plan = root / "plan.json"
            preregistration = root / "preregistration.json"
            plan.write_text(
                json.dumps({"case_ids": case_ids, "collection_selection": selection}),
                encoding="utf-8",
            )
            preregistration.write_text(
                json.dumps(
                    {
                        "case_ids": case_ids,
                        "preregistration_id": "slot-lock",
                        "collection_selection": selection,
                    }
                ),
                encoding="utf-8",
            )
            self._write_capture(captures, "s1-primary", valid=False)
            self._write_capture(captures, "s1-alternate", valid=True)
            self._write_capture(captures, "s2-primary", valid=True)
            self._write_capture(captures, "s2-alternate", valid=True)

            summary = MODULE.build_summary(captures, plan, preregistration)

            self.assertTrue(summary["claim180_collection_complete"])
            self.assertEqual(
                ["s1-alternate", "s2-primary"],
                summary["selection"]["selected_case_ids"],
            )
            self.assertEqual(
                [
                    {"slot_id": "slot-1", "case_id": "s1-alternate"},
                    {"slot_id": "slot-2", "case_id": "s2-primary"},
                ],
                summary["selection"]["selected_by_slot"],
            )

    def test_summary_preserves_valid_invalid_and_startup_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            captures = root / "captures"
            captures.mkdir()
            case_ids = ["valid-case", "invalid-case", "startup-case"]
            plan = root / "plan.json"
            preregistration = root / "preregistration.json"
            plan.write_text(json.dumps({"case_ids": case_ids}), encoding="utf-8")
            preregistration.write_text(
                json.dumps(
                    {
                        "case_ids": case_ids,
                        "preregistration_id": "frozen-preregistration",
                    }
                ),
                encoding="utf-8",
            )
            self._write_capture(captures, "valid-case", valid=True)
            self._write_capture(captures, "invalid-case", valid=False)
            startup = captures / "startup-case"
            startup.mkdir()
            (startup / "failure.json").write_text(
                json.dumps(
                    {
                        "failure_type": "TimeoutError",
                        "failure": "navigation timed out",
                    }
                ),
                encoding="utf-8",
            )

            summary = MODULE.build_summary(captures, plan, preregistration)

            self.assertEqual(
                {"valid": 1, "invalid": 1, "startup_failed": 1, "missing": 0},
                summary["counts"],
            )
            self.assertFalse(summary["claim180_collection_complete"])
            self.assertEqual("all_planned_cases_valid", summary["selection"]["mode"])
            self.assertEqual([], summary["selection"]["selected_case_ids"])
            self.assertEqual(
                ["valid", "invalid", "startup_failed"],
                [row["collection_status"] for row in summary["cases"]],
            )
            self.assertNotIn(
                "source_path", summary["cases"][0]["action_spec"]
            )
            self.assertNotIn("executable", summary["cases"][0]["browser"])

    @staticmethod
    def _write_capture(root: Path, case_id: str, *, valid: bool) -> None:
        case_root = root / case_id
        case_root.mkdir()
        (case_root / "capture.json").write_text(
            json.dumps(
                {
                    "case_id": case_id,
                    "captured_at_utc": "2026-08-21T00:00:00Z",
                    "source_url": "https://example.invalid",
                    "navigation": {"final_url": "https://example.invalid"},
                    "action_spec": {
                        "path": "actions.json",
                        "source_path": "C:/private/action.json",
                        "bytes": 10,
                        "sha256": "a" * 64,
                    },
                    "browser": {
                        "executable": "C:/private/chrome.exe",
                        "version": "1",
                    },
                    "actions": [],
                }
            ),
            encoding="utf-8",
        )
        (case_root / "verification.json").write_text(
            json.dumps(
                {
                    "case_id": case_id,
                    "valid": valid,
                    "integrity_valid": valid,
                    "policy_valid": valid,
                    "policy_reasons": [] if valid else ["required action failed"],
                    "required_action_failures": [] if valid else ["click"],
                    "recomputed_statistics": {
                        "frame_count": 2,
                        "effective_average_fps": 15,
                        "interval_seconds": {"maximum": 0.07},
                    },
                }
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
