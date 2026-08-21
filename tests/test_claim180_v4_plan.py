from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from signum.freeze import preregister_heldout


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
