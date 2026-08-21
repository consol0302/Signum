from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from signum.claims import assess_claim
from signum.evaluation import CLAIM180_TARGETS, EvaluationError
from signum.freeze import (
    _validate_collection_evidence,
    _validate_collection_selection,
    freeze_manifest,
    preregister_heldout,
)
from signum.synthetic import generate_suite


class ClaimAssessmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_context = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_context.name)
        generated = generate_suite(self.root / "source")
        self.source_video = generated[3][1]

    def tearDown(self) -> None:
        self.temp_context.cleanup()

    def test_cost_claim_requires_valid_held_out_freeze(self) -> None:
        manifest, events, preregistration = self._claim_manifest()
        held_out_lock = self.root / "held-out-freeze.json"
        frozen = freeze_manifest(
            manifest,
            held_out_lock,
            role="held_out",
            preregistration_path=preregistration,
        )
        comparison = self._comparison(held_out_lock, frozen["freeze_id"], events)

        result = assess_claim(comparison)

        self.assertTrue(result["claim_supported"])
        self.assertEqual(["native-baseline"], result["claimable_baselines"])
        row = result["comparisons"][0]
        self.assertFalse(row["accuracy_superiority"])
        self.assertTrue(row["accuracy_noninferiority"])
        self.assertTrue(row["cost_claim_supported"])
        self.assertEqual(30, result["frozen_evidence"]["unique_video_count"])

        development_lock = self.root / "development-freeze.json"
        development = freeze_manifest(manifest, development_lock, role="development")
        development_comparison = self._comparison(
            development_lock,
            development["freeze_id"],
            events,
            name="development-comparison.json",
        )
        blocked = assess_claim(development_comparison)
        self.assertFalse(blocked["claim_supported"])
        self.assertIn("freeze role is not held_out", blocked["global_reasons"])

    def test_held_out_freeze_requires_preregistration(self) -> None:
        manifest, _, _ = self._claim_manifest()

        with self.assertRaisesRegex(EvaluationError, "preregistration"):
            freeze_manifest(
                manifest,
                self.root / "unregistered-freeze.json",
                role="held_out",
            )

    def test_preregistration_verifies_every_frozen_action_file(self) -> None:
        case_ids = [f"workflow-{index:02d}" for index in range(30)]
        actions_dir = self.root / "actions"
        actions_dir.mkdir()
        action_rows = []
        for case_id in case_ids:
            action_path = actions_dir / f"{case_id}.json"
            action_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "case_id": case_id,
                        "actions": [],
                    }
                ),
                encoding="utf-8",
            )
            action_rows.append(
                {
                    "case_id": case_id,
                    "action_file": f"actions/{case_id}.json",
                    "bytes": action_path.stat().st_size,
                    "sha256": hashlib.sha256(action_path.read_bytes()).hexdigest(),
                }
            )
        actions_manifest = self.root / "actions-manifest.json"
        actions_manifest.write_text(
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
        plan = self.root / "action-plan.json"
        plan.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "protocol_id": "signum-claim180-actions-test",
                    "protocol_repository": "https://example.invalid/signum",
                    "protocol_revision": "a" * 40,
                    "case_ids": case_ids,
                    "category_targets": CLAIM180_TARGETS,
                    "evidence_policy": {"review": "human blind"},
                    "observation_budget": {"screenshots": 2},
                    "workflow_sources": [
                        {
                            "case_id": case_id,
                            "url": f"https://example.invalid/{case_id}",
                            "goal": "complete the frozen workflow",
                        }
                        for case_id in case_ids
                    ],
                    "actions_manifest": {
                        "path": actions_manifest.name,
                        "bytes": actions_manifest.stat().st_size,
                        "sha256": hashlib.sha256(
                            actions_manifest.read_bytes()
                        ).hexdigest(),
                    },
                }
            ),
            encoding="utf-8",
        )

        lock = preregister_heldout(plan, self.root / "actions-lock.json")
        self.assertEqual(30, lock["actions_manifest"]["case_count"])
        self.assertEqual("b" * 40, lock["actions_manifest"]["collector_revision"])

        (actions_dir / f"{case_ids[0]}.json").write_text(
            "changed after action freeze", encoding="utf-8"
        )
        with self.assertRaisesRegex(EvaluationError, "action file integrity"):
            preregister_heldout(plan, self.root / "tampered-lock.json")

    def test_candidate_pool_selects_first_valid_cases_and_preserves_failures(self) -> None:
        selection = _validate_collection_selection(
            {
                "mode": "first_valid_in_plan_order",
                "validity_source": "independent_capture_verification",
                "retain_all_attempts": True,
                "model_outputs_forbidden_before_selection": True,
                "required_valid_cases": 30,
                "candidate_count": 31,
            },
            31,
        )
        self.assertIsNotNone(selection)
        case_ids = [f"candidate-{index:02d}" for index in range(31)]
        collection_root = self.root / "candidate-captures"
        collection_root.mkdir()
        rows = []

        def identity(path: Path) -> dict[str, object]:
            return {
                "path": path.relative_to(collection_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }

        for case_id in case_ids[:30]:
            case_root = collection_root / case_id
            case_root.mkdir()
            capture = case_root / "capture.json"
            verification = case_root / "verification.json"
            capture.write_text(json.dumps({"case_id": case_id}), encoding="utf-8")
            verification.write_text(
                json.dumps({"case_id": case_id, "valid": True}),
                encoding="utf-8",
            )
            rows.append(
                {
                    "case_id": case_id,
                    "collection_status": "valid",
                    "eligible_for_claim": True,
                    "capture_artifact": identity(capture),
                    "verification_artifact": identity(verification),
                }
            )
        failed_id = case_ids[-1]
        failed_root = collection_root / failed_id
        failed_root.mkdir()
        failure = failed_root / "failure.json"
        failure.write_text(
            json.dumps({"case_id": failed_id, "failure": "startup failed"}),
            encoding="utf-8",
        )
        rows.append(
            {
                "case_id": failed_id,
                "collection_status": "startup_failed",
                "eligible_for_claim": False,
                "failure_artifact": identity(failure),
            }
        )
        preregistration = {
            "preregistration_id": "candidate-preregistration",
            "case_ids": case_ids,
            "collection_selection": selection,
        }
        summary = {
            "schema_version": 1,
            "kind": "signum_claim180_collection_summary",
            "generated_at_utc": "2026-08-21T00:00:00Z",
            "preregistration_id": "candidate-preregistration",
            "counts": {
                "valid": 30,
                "invalid": 0,
                "startup_failed": 1,
                "missing": 0,
            },
            "selection": {
                "mode": "first_valid_in_plan_order",
                "required_valid_cases": 30,
                "selected_case_ids": case_ids[:30],
            },
            "claim180_collection_complete": True,
            "unexpected_case_directories": [],
            "cases": rows,
        }
        summary["collection_id"] = hashlib.sha256(
            json.dumps(
                {
                    key: value
                    for key, value in summary.items()
                    if key not in {"generated_at_utc", "collection_id"}
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        summary_path = self.root / "candidate-summary.json"
        summary_path.write_text(json.dumps(summary), encoding="utf-8")

        evidence = _validate_collection_evidence(
            summary_path,
            collection_root,
            preregistration,
            case_ids[:30],
        )
        self.assertEqual(case_ids[:30], evidence["selected_case_ids"])
        self.assertEqual(61, len(evidence["artifacts"]))

        with self.assertRaisesRegex(EvaluationError, "first valid candidates"):
            _validate_collection_evidence(
                summary_path,
                collection_root,
                preregistration,
                list(reversed(case_ids[:30])),
            )
        (collection_root / case_ids[0] / "capture.json").write_text(
            "tampered", encoding="utf-8"
        )
        with self.assertRaisesRegex(EvaluationError, "artifact integrity"):
            _validate_collection_evidence(
                summary_path,
                collection_root,
                preregistration,
                case_ids[:30],
            )

    def test_slot_pool_preserves_balance_when_primary_candidates_fail(self) -> None:
        slots = [
            {
                "slot_id": f"slot-{index:02d}",
                "candidate_ids": [
                    f"slot-{index:02d}-primary",
                    f"slot-{index:02d}-alternate",
                ],
            }
            for index in range(30)
        ]
        case_ids = [
            case_id for slot in slots for case_id in slot["candidate_ids"]
        ]
        selection = _validate_collection_selection(
            {
                "mode": "first_valid_per_slot_in_plan_order",
                "validity_source": "independent_capture_verification",
                "retain_all_attempts": True,
                "model_outputs_forbidden_before_selection": True,
                "required_valid_cases": 30,
                "candidate_count": 60,
                "slots": slots,
            },
            60,
            case_ids,
        )
        self.assertIsNotNone(selection)
        collection_root = self.root / "slot-captures"
        collection_root.mkdir()
        rows = []

        def identity(path: Path) -> dict[str, object]:
            return {
                "path": path.relative_to(collection_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }

        selected_by_slot = []
        for index, slot in enumerate(slots):
            chosen = slot["candidate_ids"][index % 2]
            selected_by_slot.append(
                {"slot_id": slot["slot_id"], "case_id": chosen}
            )
            for case_id in slot["candidate_ids"]:
                case_root = collection_root / case_id
                case_root.mkdir()
                capture = case_root / "capture.json"
                verification = case_root / "verification.json"
                valid = case_id == chosen
                capture.write_text(
                    json.dumps({"case_id": case_id}), encoding="utf-8"
                )
                verification.write_text(
                    json.dumps({"case_id": case_id, "valid": valid}),
                    encoding="utf-8",
                )
                rows.append(
                    {
                        "case_id": case_id,
                        "collection_status": "valid" if valid else "invalid",
                        "eligible_for_claim": valid,
                        "capture_artifact": identity(capture),
                        "verification_artifact": identity(verification),
                    }
                )
        selected = [row["case_id"] for row in selected_by_slot]
        preregistration = {
            "preregistration_id": "slot-preregistration",
            "case_ids": case_ids,
            "collection_selection": selection,
        }
        summary = {
            "schema_version": 1,
            "kind": "signum_claim180_collection_summary",
            "generated_at_utc": "2026-08-21T00:00:00Z",
            "preregistration_id": "slot-preregistration",
            "counts": {
                "valid": 30,
                "invalid": 30,
                "startup_failed": 0,
                "missing": 0,
            },
            "selection": {
                "mode": "first_valid_per_slot_in_plan_order",
                "required_valid_cases": 30,
                "selected_case_ids": selected,
                "selected_by_slot": selected_by_slot,
            },
            "claim180_collection_complete": True,
            "unexpected_case_directories": [],
            "cases": rows,
        }
        summary["collection_id"] = hashlib.sha256(
            json.dumps(
                {
                    key: value
                    for key, value in summary.items()
                    if key not in {"generated_at_utc", "collection_id"}
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        summary_path = self.root / "slot-summary.json"
        summary_path.write_text(json.dumps(summary), encoding="utf-8")

        evidence = _validate_collection_evidence(
            summary_path, collection_root, preregistration, selected
        )

        self.assertEqual(selected, evidence["selected_case_ids"])
        self.assertEqual(120, len(evidence["artifacts"]))
        with self.assertRaisesRegex(EvaluationError, "frozen rule"):
            _validate_collection_evidence(
                summary_path,
                collection_root,
                preregistration,
                list(reversed(selected)),
            )

    def test_slot_pool_rejects_missing_duplicate_and_reordered_candidates(self) -> None:
        case_ids = [f"candidate-{index:02d}" for index in range(60)]
        slots = [
            {
                "slot_id": f"slot-{index:02d}",
                "candidate_ids": case_ids[index * 2 : index * 2 + 2],
            }
            for index in range(30)
        ]
        raw = {
            "mode": "first_valid_per_slot_in_plan_order",
            "validity_source": "independent_capture_verification",
            "retain_all_attempts": True,
            "model_outputs_forbidden_before_selection": True,
            "required_valid_cases": 30,
            "candidate_count": 60,
            "slots": slots,
        }
        reordered = json.loads(json.dumps(raw))
        reordered["slots"][0]["candidate_ids"].reverse()
        with self.assertRaisesRegex(EvaluationError, "order must match"):
            _validate_collection_selection(reordered, 60, case_ids)
        duplicate = json.loads(json.dumps(raw))
        duplicate["slots"][1]["candidate_ids"][0] = case_ids[0]
        with self.assertRaisesRegex(EvaluationError, "exactly once"):
            _validate_collection_selection(duplicate, 60, case_ids)

    def test_claim_is_blocked_when_a_run_artifact_changes(self) -> None:
        manifest, events, preregistration = self._claim_manifest()
        held_out_lock = self.root / "artifact-freeze.json"
        frozen = freeze_manifest(
            manifest,
            held_out_lock,
            role="held_out",
            preregistration_path=preregistration,
        )
        comparison = self._comparison(
            held_out_lock,
            frozen["freeze_id"],
            events,
            name="artifact-comparison.json",
        )
        payload = json.loads(comparison.read_text(encoding="utf-8"))
        run_path = self.root / payload["systems"][0]["run_artifacts"][0]["path"]
        run_path.write_text("changed after comparison assembly", encoding="utf-8")

        result = assess_claim(comparison)

        self.assertFalse(result["claim_supported"])
        self.assertIn(
            "one or more system run artifacts failed integrity checks",
            result["global_reasons"],
        )

    def _claim_manifest(
        self,
    ) -> tuple[Path, list[dict[str, object]], Path]:
        case_ids = [f"workflow-{index:02d}" for index in range(30)]
        plan = self.root / "heldout-plan.json"
        plan.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "protocol_id": "signum-claim180-test",
                    "protocol_repository": "https://example.invalid/signum",
                    "protocol_revision": "a" * 40,
                    "case_ids": case_ids,
                    "category_targets": CLAIM180_TARGETS,
                    "evidence_policy": {
                        "source": "original event-aligned frames",
                        "review": "human blind",
                    },
                    "observation_budget": {
                        "policy": "same maximum screenshots, zooms, and turns"
                    },
                    "workflow_sources": [
                        {
                            "case_id": case_id,
                            "url": f"https://example.invalid/{case_id}",
                            "goal": "complete the frozen test workflow",
                        }
                        for case_id in case_ids
                    ],
                }
            ),
            encoding="utf-8",
        )
        preregistration = self.root / "heldout-preregistration.json"
        preregister_heldout(plan, preregistration)
        cases = []
        events_for_system = []
        categories = [
            category
            for category, count in CLAIM180_TARGETS.items()
            for _ in range(count)
        ]
        source_bytes = self.source_video.read_bytes()
        for workflow_index, case_id in enumerate(case_ids):
            video = self.root / f"{case_id}.avi"
            video.write_bytes(source_bytes + bytes([workflow_index]))
            manifest_events = []
            case_categories = categories[workflow_index * 6 : (workflow_index + 1) * 6]
            for event_index, category in enumerate(case_categories):
                event_id = f"event-{event_index}"
                event = {
                    "id": event_id,
                    "start": 0.1,
                    "end": 0.2,
                    "category": category,
                    "risk": "high" if category == "action_failure" else "normal",
                    "acceptable_states": [f"state-{event_index}"],
                    "source_transition_id": f"{case_id}:{event_index}",
                    "real_world_eligible": True,
                }
                if category in {"action_failure", "action_success"}:
                    event.update(
                        {
                            "before_timestamp": 0.0,
                            "after_timestamp": 0.2,
                            "action": "performed the labeled action",
                            "expected_result": "the labeled result is visible",
                        }
                    )
                manifest_events.append(event)
                events_for_system.append(
                    {
                        "event_id": f"{case_id}/{event_id}",
                        "workflow_id": case_id,
                        "category": category,
                        "success": True,
                        "false_confirmation": False,
                    }
                )
            cases.append(
                {
                    "id": case_id,
                    "video": str(video),
                    "goal": "complete a frozen test workflow",
                    "events": manifest_events,
                }
            )
        manifest = self.root / "manifest.json"
        manifest.write_text(
            json.dumps({"schema_version": 2, "cases": cases}),
            encoding="utf-8",
        )
        return manifest, events_for_system, preregistration

    def _comparison(
        self,
        lock: Path,
        freeze_id: str,
        events: list[dict[str, object]],
        *,
        name: str = "comparison.json",
    ) -> Path:
        def artifact(name: str, payload: dict[str, object], *, reviewer: str | None = None) -> dict[str, object]:
            destination = self.root / name
            destination.write_text(json.dumps(payload), encoding="utf-8")
            data = destination.read_bytes()
            result: dict[str, object] = {
                "path": destination.name,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
            if reviewer is not None:
                result["reviewer"] = reviewer
            return result

        candidate_artifacts = [
            artifact(f"candidate-run-{index}.json", {"run": index, "system": "candidate"})
            for index in range(3)
        ]
        baseline_artifacts = [
            artifact(f"baseline-run-{index}.json", {"run": index, "system": "baseline"})
            for index in range(3)
        ]
        reviewer_artifacts = [
            artifact(
                f"review-{reviewer}.json",
                {"reviewer": reviewer, "method": "human_blind"},
                reviewer=reviewer,
            )
            for reviewer in ("reviewer-a", "reviewer-b")
        ]
        adjudication_artifact = artifact(
            "adjudication.json", {"adjudicated": True}
        )
        payload = {
            "schema_version": 1,
            "freeze": lock.name,
            "freeze_id": freeze_id,
            "requirements": {"bootstrap_samples": 100},
            "review": {
                "method": "human_blind",
                "reviewers": ["reviewer-a", "reviewer-b"],
                "adjudicated": True,
                "artifacts": reviewer_artifacts,
                "adjudication_artifact": adjudication_artifact,
            },
            "systems": [
                {
                    "id": "signum-candidate",
                    "kind": "candidate",
                    "provider": "test-provider",
                    "model": "fixed-model",
                    "cost_basis": "provider_invoice",
                    "cost_evidence": "test invoice hash candidate",
                    "billed_cost_usd_runs": [0.5, 0.5, 0.5],
                    "run_artifacts": candidate_artifacts,
                    "events": events,
                },
                {
                    "id": "native-baseline",
                    "kind": "baseline",
                    "provider": "test-provider",
                    "model": "fixed-model",
                    "cost_basis": "provider_invoice",
                    "cost_evidence": "test invoice hash baseline",
                    "billed_cost_usd_runs": [1.0, 1.0, 1.0],
                    "run_artifacts": baseline_artifacts,
                    "events": events,
                },
            ],
        }
        path = self.root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
