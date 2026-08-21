from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from signum.cli import main
from signum.evaluation import (
    CLAIM180_TARGETS,
    PILOT60_TARGETS,
    EvaluationError,
    audit_manifest,
    load_manifest,
    run_evaluation,
    score_reviews,
)
from signum.gateway import GatewayConfig, PerceptionEvent, SemanticResult
from signum.freeze import freeze_manifest, verify_freeze
from signum.synthetic import generate_suite


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_context = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp_context.name)
        cls.generated = generate_suite(cls.root / "media")
        cls.flash_case, cls.flash_video = cls.generated[3]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_context.cleanup()

    def _manifest(self, name: str, *, acceptable_states: list[str] | None = None) -> Path:
        path = self.root / f"{name}.json"
        event = self.flash_case.events[0]
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "cases": [
                        {
                            "id": name,
                            "video": str(self.flash_video),
                            "goal": "notice the brief full-screen flash",
                            "events": [
                                {
                                    "id": event.name,
                                    "start": event.start,
                                    "end": event.end,
                                    "tolerance": event.tolerance,
                                    "acceptable_states": acceptable_states or [],
                                    "notes": "The white flash must be visible.",
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_equal_budget_replay_recovers_preserved_peak(self) -> None:
        output = self.root / "detector-evaluation"
        result = run_evaluation(
            self._manifest("brief-flash"),
            output,
            config=GatewayConfig(min_event_interval_seconds=0.0),
        )

        signum = result["aggregate"]["signum"]
        uniform = result["aggregate"]["uniform"]
        self.assertEqual(signum["observations"], uniform["observations"])
        self.assertEqual(1.0, signum["trigger_recall"])
        self.assertEqual(0.0, uniform["trigger_recall"])
        self.assertEqual(1, signum["unmatched_initial_observations"])
        self.assertEqual(
            signum["false_observations"] - 1,
            signum["unmatched_non_initial_observations"],
        )
        match = result["cases"][0]["methods"]["signum"]["matches"][0]
        self.assertEqual("change_peak", match["matched_image_role"])
        self.assertTrue((output / "evaluation.json").is_file())
        self.assertTrue((output / "review-template.json").is_file())
        for method in ("signum", "uniform"):
            self.assertTrue(
                (output / "cases" / "brief-flash" / method / "observations.json").is_file()
            )

    def test_freeze_detects_changed_video(self) -> None:
        video = self.root / "freeze-video.avi"
        shutil.copyfile(self.flash_video, video)
        manifest = self._manifest("freeze-case")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["cases"][0]["video"] = str(video)
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        lock_path = self.root / "freeze.json"

        frozen = freeze_manifest(manifest, lock_path, role="development")
        self.assertEqual("development", frozen["role"])
        self.assertTrue(verify_freeze(lock_path)["valid"])

        with video.open("ab") as handle:
            handle.write(b"changed")
        verified = verify_freeze(lock_path)
        self.assertFalse(verified["valid"])
        video_check = next(
            row for row in verified["checks"] if row["kind"] == "video:freeze-case"
        )
        self.assertFalse(video_check["valid"])

    def test_human_review_produces_end_to_end_success_rate(self) -> None:
        output = self.root / "reviewed-evaluation"
        run_evaluation(
            self._manifest("reviewed-flash"),
            output,
            config=GatewayConfig(min_event_interval_seconds=0.0),
        )
        review_path = output / "review-template.json"
        review = json.loads(review_path.read_text(encoding="utf-8"))
        incomplete = score_reviews(output / "evaluation.json", review_path)
        self.assertFalse(incomplete["complete"])
        self.assertIsNone(
            incomplete["methods"]["signum"]["end_to_end_success_rate"]
        )
        for row in review["reviews"]:
            if row["triggered"]:
                row["evidence_visible"] = True
                row["semantic_correct"] = True
                row["task_state_correct"] = True
        review["reviewer"] = "reviewer-1"
        review["review_method"] = "human_blind"
        completed_review = output / "completed-review.json"
        completed_review.write_text(json.dumps(review), encoding="utf-8")

        score = score_reviews(
            output / "evaluation.json",
            completed_review,
        )

        self.assertTrue(score["complete"])
        self.assertEqual("reviewer-1", score["reviewer"])
        self.assertEqual("human_blind", score["review_method"])
        self.assertEqual(
            1.0, score["methods"]["signum"]["end_to_end_success_rate"]
        )
        self.assertEqual(
            0.0, score["methods"]["uniform"]["end_to_end_success_rate"]
        )

    def test_codex_state_accuracy_is_separate_from_human_review(self) -> None:
        class FakeInterpreter:
            def interpret(
                self,
                event: PerceptionEvent,
                goal: str,
                previous: SemanticResult | None,
            ) -> SemanticResult:
                return SemanticResult(
                    state="flash_visible",
                    summary="A flash is visible.",
                    relevant=True,
                    confidence=1.0,
                    recommended_action="Continue.",
                    input_tokens=10,
                    output_tokens=5,
                )

        result = run_evaluation(
            self._manifest("semantic-flash", acceptable_states=["flash visible"]),
            self.root / "semantic-evaluation",
            config=GatewayConfig(min_event_interval_seconds=0.0),
            interpreter=FakeInterpreter(),
        )

        self.assertTrue(result["semantic_attempted"])
        self.assertEqual(
            1.0, result["aggregate"]["signum"]["exact_state_accuracy"]
        )
        self.assertEqual(
            0.0, result["aggregate"]["uniform"]["exact_state_accuracy"]
        )
        for method in ("signum", "uniform"):
            aggregate = result["aggregate"][method]
            self.assertTrue(aggregate["reported_usage_complete"])
            self.assertEqual(
                aggregate["ai_calls"] * 15,
                aggregate["reported_total_tokens"],
            )

    def test_manifest_rejects_region_outside_frame(self) -> None:
        manifest = self._manifest("invalid-region")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["cases"][0]["events"][0]["region"] = {
            "x": 0.9,
            "y": 0.0,
            "width": 0.2,
            "height": 0.1,
        }
        manifest.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaises(EvaluationError):
            load_manifest(manifest)

    def test_schema_two_requires_category_and_audits_pilot_coverage(self) -> None:
        manifest = self._manifest("audit-category")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["schema_version"] = 2
        with self.assertRaises(EvaluationError):
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            load_manifest(manifest)

        payload["cases"][0]["events"][0]["category"] = "action_failure"
        payload["cases"][0]["events"][0]["risk"] = "high"
        payload["cases"][0]["events"][0]["before_timestamp"] = 0.0
        payload["cases"][0]["events"][0]["after_timestamp"] = payload["cases"][0][
            "events"
        ][0]["start"]
        payload["cases"][0]["events"][0]["action"] = "clicked Submit"
        payload["cases"][0]["events"][0]["expected_result"] = "a result appears"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        audit = audit_manifest(manifest)

        self.assertEqual(1, audit["event_count"])
        self.assertEqual(1, audit["category_counts"]["action_failure"])
        self.assertEqual(1, audit["risk_counts"]["high"])
        self.assertEqual(1, audit["independent_transition_count"])
        self.assertEqual(0, audit["duplicated_transition_count"])
        self.assertEqual(1, audit["eligible_category_counts"]["action_failure"])
        self.assertEqual(
            PILOT60_TARGETS["action_failure"] - 1,
            audit["deficits"]["action_failure"],
        )
        self.assertFalse(audit["profile_complete"])

    def test_category_metrics_confidence_interval_and_false_confirmation(self) -> None:
        class FalseConfirmingInterpreter:
            def interpret(
                self,
                event: PerceptionEvent,
                goal: str,
                previous: SemanticResult | None,
            ) -> SemanticResult:
                return SemanticResult(
                    state="unchanged",
                    summary="The action succeeded.",
                    relevant=True,
                    confidence=1.0,
                    recommended_action="Continue.",
                    verification=(
                        "confirmed"
                        if event.reason == "action_verification"
                        else "not_applicable"
                    ),
                    input_tokens=10,
                    output_tokens=5,
                )

        manifest = self._manifest("failed-action")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["schema_version"] = 2
        payload["cases"][0]["events"][0]["category"] = "action_failure"
        payload["cases"][0]["events"][0]["risk"] = "critical"
        payload["cases"][0]["events"][0]["before_timestamp"] = 0.0
        payload["cases"][0]["events"][0]["after_timestamp"] = payload["cases"][0][
            "events"
        ][0]["start"]
        payload["cases"][0]["events"][0]["action"] = "clicked Submit"
        payload["cases"][0]["events"][0]["expected_result"] = "a result appears"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        output = self.root / "failed-action-evaluation"
        result = run_evaluation(
            manifest,
            output,
            config=GatewayConfig(min_event_interval_seconds=0.0),
            interpreter=FalseConfirmingInterpreter(),
        )

        interval = result["aggregate"]["signum"]["trigger_recall_ci95"]
        self.assertIsNotNone(interval)
        self.assertEqual(2, len(interval))
        self.assertEqual(
            1.0,
            result["by_category"]["signum"]["action_failure"]["trigger_recall"],
        )
        self.assertEqual(1, result["cases"][0]["forced_action_verifications"])
        self.assertEqual(
            0.0, result["aggregate"]["signum"]["verification_accuracy"]
        )
        self.assertEqual(
            1, result["aggregate"]["signum"]["automatic_false_confirmations"]
        )
        for method in ("signum", "uniform"):
            match = result["cases"][0]["methods"][method]["matches"][0]
            self.assertTrue(match["triggered"])
            self.assertEqual("action_verification", match["matched_reason"])

        review_path = output / "review-template.json"
        review = json.loads(review_path.read_text(encoding="utf-8"))
        for row in review["reviews"]:
            if row["triggered"]:
                row["evidence_visible"] = True
                row["semantic_correct"] = False
                row["task_state_correct"] = False
                row["false_confirmation"] = row["method"] == "signum"
        completed = output / "completed-review.json"
        completed.write_text(json.dumps(review), encoding="utf-8")
        score = score_reviews(output / "evaluation.json", completed)

        self.assertTrue(score["complete"])
        self.assertEqual(1.0, score["methods"]["signum"]["false_confirmation_rate"])
        self.assertEqual(0.0, score["methods"]["uniform"]["false_confirmation_rate"])
        self.assertEqual(
            1.0,
            score["by_category"]["signum"]["action_failure"][
                "false_confirmation_rate"
            ],
        )

    def test_audit_exposes_ineligible_and_reused_transitions(self) -> None:
        manifest = self._manifest("audit-transition-provenance")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["schema_version"] = 2
        event = payload["cases"][0]["events"][0]
        original_id = event["id"]
        event.update(
            {
                "category": "action_failure",
                "risk": "high",
                "before_timestamp": 0.0,
                "after_timestamp": event["start"],
                "action": "clicked Submit",
                "expected_result": "a result appears",
                "source_transition_id": "shared-transition",
                "real_world_eligible": False,
            }
        )
        duplicate = dict(event)
        duplicate["id"] = "second-label"
        payload["cases"][0]["events"].append(duplicate)
        manifest.write_text(json.dumps(payload), encoding="utf-8")

        audit = audit_manifest(manifest)

        self.assertEqual(2, audit["category_counts"]["action_failure"])
        self.assertEqual(0, audit["eligible_category_counts"]["action_failure"])
        self.assertEqual(1, audit["independent_transition_count"])
        self.assertEqual(1, audit["duplicated_transition_count"])
        self.assertEqual(
            [
                f"audit-transition-provenance/{original_id}",
                "audit-transition-provenance/second-label",
            ],
            audit["duplicated_transitions"]["shared-transition"],
        )

    def test_evaluate_cli_writes_machine_readable_summary(self) -> None:
        output = self.root / "cli-evaluation"
        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = main(
                [
                    "evaluate",
                    str(self._manifest("cli-flash")),
                    "--output",
                    str(output),
                    "--min-event-interval",
                    "0",
                ]
            )

        self.assertEqual(0, exit_code)
        summary = json.loads(stdout.getvalue())
        self.assertEqual(1.0, summary["signum_trigger_recall"])
        self.assertEqual(0.0, summary["uniform_trigger_recall"])

    def test_audit_manifest_cli_reports_deficits(self) -> None:
        manifest = self._manifest("audit-cli")
        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = main(["audit-manifest", str(manifest)])

        self.assertEqual(0, exit_code)
        summary = json.loads(stdout.getvalue())
        self.assertEqual("pilot60", summary["profile"])
        self.assertFalse(summary["profile_complete"])

    def test_claim180_profile_requires_180_events_and_30_cases(self) -> None:
        manifest = self._manifest("claim180-audit")

        audit = audit_manifest(manifest, profile="claim180")

        self.assertEqual(CLAIM180_TARGETS, audit["targets"])
        self.assertEqual(29, audit["case_deficit"])
        self.assertEqual(1, audit["eligible_independent_transition_count"])
        self.assertTrue(audit["require_unique_transitions"])
        self.assertFalse(audit["profile_complete"])


if __name__ == "__main__":
    unittest.main()
