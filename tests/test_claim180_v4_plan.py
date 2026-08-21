from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from signum.freeze import _verify_preregistration, preregister_heldout


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CANDIDATES = load_module(
    "build_claim180_v4_candidates_for_plan",
    ROOT / "examples" / "build_claim180_v4_candidates.py",
)
PLAN = load_module(
    "build_claim180_v4_plan",
    ROOT / "examples" / "build_claim180_v4_plan.py",
)


class Claim180V4PlanTests(unittest.TestCase):
    def test_published_preregistration_is_the_reproducible_plan_lock(self) -> None:
        plan_path = ROOT / "benchmark-protocol" / "claim180-plan-v4.json"
        published_path = (
            ROOT / "benchmark-protocol" / "claim180-preregistration-v4.json"
        )
        published = json.loads(published_path.read_text(encoding="utf-8"))
        verified = _verify_preregistration(published_path)
        self.assertEqual(published, verified)
        self.assertEqual(plan_path.stat().st_size, published["plan_bytes"])
        self.assertEqual(
            hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            published["plan_sha256"],
        )
        expected_id = hashlib.sha256(
            json.dumps(
                {
                    key: value
                    for key, value in published.items()
                    if key not in {"created_at_utc", "preregistration_id"}
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(expected_id, published["preregistration_id"])

    def test_published_plan_matches_generators_and_is_preregisterable(self) -> None:
        sources = ROOT / "benchmark-protocol" / "claim180-v4-candidate-sources.json"
        actions = ROOT / "benchmark-protocol" / "actions-v4"
        manifest = ROOT / "benchmark-protocol" / "claim180-v4-actions-manifest.json"
        plan_path = ROOT / "benchmark-protocol" / "claim180-plan-v4.json"
        collector_revision = "b6025b84d4498c682a76273e8540c63032d8e83e"
        protocol_revision = "67c821dc38bc07e38816a5f39030a607222a0f83"
        CANDIDATES.build_outputs(
            sources,
            actions,
            manifest,
            collector_revision,
            check=True,
        )
        expected = PLAN.build_plan(
            ROOT / "benchmark-protocol" / "claim180-plan-v3.json",
            sources,
            manifest,
            plan_path,
            protocol_revision,
        )
        self.assertEqual(
            PLAN.json_text(expected),
            plan_path.read_text(encoding="utf-8"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            locked = preregister_heldout(
                plan_path,
                Path(temporary) / "preregistration.json",
            )
        self.assertEqual(collector_revision, locked["actions_manifest"]["collector_revision"])
        self.assertEqual(protocol_revision, locked["protocol_revision"])

    def test_plan_and_preregistration_lock_slots_targets_and_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources.json"
            actions = root / "actions"
            manifest = root / "actions-manifest.json"
            plan_path = root / "plan.json"
            preregistration = root / "preregistration.json"
            collector_revision = "a" * 40
            protocol_revision = "b" * 40
            CANDIDATES.build_outputs(
                sources,
                actions,
                manifest,
                collector_revision,
                check=False,
            )
            plan = PLAN.build_plan(
                ROOT / "benchmark-protocol" / "claim180-plan-v3.json",
                sources,
                manifest,
                plan_path,
                protocol_revision,
            )
            plan_path.write_text(PLAN.json_text(plan), encoding="utf-8")
            locked = preregister_heldout(plan_path, preregistration)

            self.assertEqual(60, len(plan["case_ids"]))
            self.assertEqual(30, len(plan["collection_selection"]["slots"]))
            self.assertEqual(60, len(plan["target_events"]))
            self.assertEqual(collector_revision, plan["collector_revision"])
            self.assertEqual(protocol_revision, plan["protocol_revision"])
            self.assertEqual(
                "first_valid_per_slot_in_plan_order",
                locked["collection_selection"]["mode"],
            )
            self.assertEqual(plan["target_events"], locked["target_events"])
            self.assertEqual(60, locked["actions_manifest"]["case_count"])

    def test_plan_rejects_changed_source_catalog_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources.json"
            actions = root / "actions"
            manifest = root / "actions-manifest.json"
            CANDIDATES.build_outputs(
                sources,
                actions,
                manifest,
                "a" * 40,
                check=False,
            )
            sources.write_text(sources.read_text(encoding="utf-8") + " ", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "source catalog lock"):
                PLAN.build_plan(
                    ROOT / "benchmark-protocol" / "claim180-plan-v3.json",
                    sources,
                    manifest,
                    root / "plan.json",
                    "b" * 40,
                )


if __name__ == "__main__":
    unittest.main()
