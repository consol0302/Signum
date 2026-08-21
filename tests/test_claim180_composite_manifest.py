from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from signum.evaluation import audit_manifest, load_manifest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "examples" / "build_claim180_composite_manifest.py"
SPEC = importlib.util.spec_from_file_location("composite_manifest", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Claim180CompositeManifestTests(unittest.TestCase):
    def test_real_composite_builds_an_exact_claim180_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "manifest.json"
            payload = MODULE.build_manifest(
                ROOT
                / "benchmark-protocol"
                / "claim180-composite-event-inventory.json",
                ROOT / "benchmark-output" / "claim180-v3-captures",
                ROOT
                / "benchmark-output"
                / "claim180-supplement-final-captures",
                output,
            )
            output.write_text(MODULE.json.dumps(payload), encoding="utf-8")
            manifest = load_manifest(output)
            audit = audit_manifest(output, profile="claim180")

            self.assertEqual(67, len(manifest.cases))
            self.assertEqual(180, audit["eligible_independent_transition_count"])
            self.assertTrue(audit["profile_complete"])
            self.assertTrue(all(value == 0 for value in audit["eligible_deficits"].values()))


if __name__ == "__main__":
    unittest.main()
