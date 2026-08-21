from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from signum.claims import assess_claim
from signum.evaluation import CLAIM180_TARGETS, EvaluationError
from signum.freeze import freeze_manifest, preregister_heldout
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
        payload = {
            "schema_version": 1,
            "freeze": lock.name,
            "freeze_id": freeze_id,
            "requirements": {"bootstrap_samples": 100},
            "review": {
                "method": "human_blind",
                "reviewers": ["reviewer-a", "reviewer-b"],
                "adjudicated": True,
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
                    "events": events,
                },
            ],
        }
        path = self.root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
