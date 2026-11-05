from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from signum.cli import main
from signum.comparison import _render_report, compare_video
from signum.config import SamplerConfig
from signum.synthetic import generate_suite


class ComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.context = tempfile.TemporaryDirectory()
        cls.root = Path(cls.context.name)
        cls.cases = generate_suite(cls.root / "media")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.context.cleanup()

    def test_true_uniform_baseline_and_source_evidence(self) -> None:
        _, video = self.cases[3]
        output = self.root / "flash"
        result = compare_video(video, output, SamplerConfig(budget=6))
        self.assertTrue(result["equal_observation_count"])
        self.assertEqual(6, result["effective_budget"])
        indices = {}
        for method in ("signum", "uniform"):
            timeline = json.loads((output / method / "timeline.json").read_text())
            indices[method] = [row["frame_index"] for row in timeline["observations"]]
            for row in timeline["observations"]:
                self.assertAlmostEqual(row["frame_index"] / 20, row["timestamp"])
                self.assertTrue((output / method / row["frame_file"]).is_file())
        self.assertEqual([0, 24, 48, 71, 95, 119], indices["uniform"])
        self.assertIn(52, indices["signum"])
        self.assertNotIn(52, indices["uniform"])
        report = json.loads((output / "uniform" / "report.json").read_text())
        self.assertEqual(0, report["counts"]["analyzed_candidates"])
        self.assertEqual(0, report["counts"]["coarse_scanned_frames"])
        markup = (output / "index.html").read_text(encoding="utf-8")
        self.assertIn("52", markup)
        self.assertEqual(12, markup.count("<figure>"))
        self.assertIn("semantic_accuracy", result["unmeasured"])

    def test_large_budget_keeps_actual_export_counts_equal(self) -> None:
        _, video = self.cases[3]
        result = compare_video(
            video, self.root / "large", SamplerConfig(budget=200, candidate_hz=0.1)
        )
        self.assertEqual(200, result["requested_budget"])
        self.assertLess(result["effective_budget"], 200)
        self.assertEqual(
            result["methods"]["signum"]["selected_observations"],
            result["methods"]["uniform"]["selected_observations"],
        )

    def test_single_observation_budget(self) -> None:
        result = compare_video(
            self.cases[0][1], self.root / "single", SamplerConfig(budget=1)
        )
        self.assertTrue(result["equal_observation_count"])
        self.assertEqual(1, result["effective_budget"])

    def test_cli_returns_report_and_handles_bad_input(self) -> None:
        output = self.root / "cli"
        stdout = StringIO()
        with redirect_stdout(stdout):
            status = main([
                "compare", str(self.cases[0][1]), "--budget", "4", "--output", str(output)
            ])
        self.assertEqual(0, status)
        summary = json.loads(stdout.getvalue())
        self.assertEqual(4, summary["selected_per_method"])
        self.assertTrue(Path(summary["html_report"]).is_file())
        for arguments in (
            ["compare", str(self.root / "missing.avi")],
            ["compare", str(self.cases[0][1]), "--budget", "0"],
        ):
            with self.subTest(arguments=arguments), redirect_stderr(StringIO()):
                self.assertEqual(2, main(arguments))

    def test_report_escapes_input_filename(self) -> None:
        report = _render_report(
            {
                "source": {
                    "path": "input&<script>.avi",
                    "duration_seconds": 1,
                    "frame_count": 20,
                },
                "requested_budget": 1,
                "effective_budget": 1,
            },
            {"timeline": {"observations": []}},
            {"timeline": {"observations": []}},
        )
        self.assertNotIn("<script>", report)
        self.assertIn("&lt;script&gt;", report)


if __name__ == "__main__":
    unittest.main()
