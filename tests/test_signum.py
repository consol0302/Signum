from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import numpy as np

from signum.cli import main
from signum.config import SamplerConfig
from signum.models import Candidate
from signum.pipeline import analyze_video
from signum.selector import hybrid_select
from signum.signals import analyze_candidates
from signum.synthetic import generate_suite
from signum.video import candidate_indices, probe_video


def candidate(index: int, timestamp: float, value: int, importance: float) -> Candidate:
    return Candidate(
        frame_index=index,
        timestamp=timestamp,
        source_start=max(0.0, timestamp - 0.1),
        source_end=timestamp + 0.1,
        importance=importance,
        signature=np.full((9, 16), value, dtype=np.uint8),
    )


class SelectorTests(unittest.TestCase):
    def test_budget_invariant_and_determinism(self) -> None:
        candidates = [candidate(i, i * 0.25, i * 10, float(i % 3)) for i in range(12)]
        config = SamplerConfig(budget=5, min_distance_seconds=0.5)
        first = hybrid_select(candidates, config)
        second = hybrid_select(candidates, config)
        self.assertEqual(5, len(first))
        self.assertEqual(
            [item.frame_index for item in first],
            [item.frame_index for item in second],
        )

    def test_duplicate_is_skipped_when_distinct_alternative_exists(self) -> None:
        candidates = [
            candidate(0, 0.0, 10, 1.0),
            candidate(1, 1.0, 10, 0.9),
            candidate(2, 2.0, 200, 0.8),
        ]
        config = SamplerConfig(
            budget=2,
            coverage_fraction=0.0,
            min_distance_seconds=0.0,
            duplicate_threshold=0.01,
        )
        selected = hybrid_select(candidates, config)
        self.assertEqual([0, 2], [item.frame_index for item in selected])


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_context = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp_context.name)
        cls.generated = generate_suite(cls.root / "media")
        cls.case, cls.video = cls.generated[0]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_context.cleanup()

    def test_pipeline_budget_timestamps_and_artifacts(self) -> None:
        output = self.root / "analysis"
        config = SamplerConfig(budget=5)
        result = analyze_video(self.video, output, config)
        observations = result["timeline"]["observations"]
        fps = result["timeline"]["source"]["fps"]
        self.assertEqual(5, len(observations))
        for observation in observations:
            self.assertAlmostEqual(
                observation["timestamp"], observation["frame_index"] / fps
            )
            self.assertTrue((output / observation["frame_file"]).is_file())
        self.assertTrue((output / "timeline.json").is_file())
        self.assertTrue((output / "report.json").is_file())
        counts = result["report"]["counts"]
        self.assertEqual(counts["source_frames"], counts["coarse_scanned_frames"])
        self.assertLessEqual(counts["scheduled_candidates"], counts["analyzed_candidates"])

    def test_pipeline_deterministic_indices(self) -> None:
        config = SamplerConfig(budget=6)
        left = analyze_video(self.video, self.root / "left", config)
        right = analyze_video(self.video, self.root / "right", config)
        left_indices = [
            item["frame_index"] for item in left["timeline"]["observations"]
        ]
        right_indices = [
            item["frame_index"] for item in right["timeline"]["observations"]
        ]
        self.assertEqual(left_indices, right_indices)

    def test_cli_smoke(self) -> None:
        output = self.root / "cli"
        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = main(
                [
                    "analyze",
                    str(self.video),
                    "--budget",
                    "4",
                    "--output",
                    str(output),
                ]
            )
        self.assertEqual(0, exit_code)
        summary = json.loads(stdout.getvalue())
        self.assertEqual(4, summary["selected"])

    def test_spike_guard_recovers_between_sample_flash(self) -> None:
        flash_case, flash_video = self.generated[3]
        metadata = probe_video(flash_video)
        config = SamplerConfig(budget=flash_case.budget)
        indices = candidate_indices(metadata, config.candidate_hz)
        guarded = analyze_candidates(metadata, indices, config)
        unguarded = analyze_candidates(
            metadata, indices, replace(config, spike_guard=False)
        )

        guarded_selected = hybrid_select(guarded.candidates, config)
        unguarded_selected = hybrid_select(unguarded.candidates, config)

        def captured(selected: list[Candidate]) -> bool:
            event = flash_case.events[0]
            return any(
                event.start - event.tolerance
                <= item.timestamp
                <= event.end + event.tolerance
                for item in selected
            )

        self.assertEqual(1, guarded.promoted_spike_count)
        self.assertEqual("spike_guard", next(
            item.discovery
            for item in guarded.candidates
            if item.frame_index == 52
        ))
        self.assertTrue(captured(guarded_selected))
        self.assertFalse(captured(unguarded_selected))


if __name__ == "__main__":
    unittest.main()
