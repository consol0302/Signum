from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

import numpy as np

from signum.gateway import GatewayConfig, PerceptionGateway
from signum.interpreters import CodexExecInterpreter


class CodexExecInterpreterTests(unittest.TestCase):
    def test_uses_read_only_ephemeral_codex_with_images_and_schema(self) -> None:
        captured: dict[str, object] = {}

        def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            captured["command"] = command
            captured["prompt"] = kwargs["input"]
            output_path = Path(command[command.index("--output-last-message") + 1])
            schema_path = Path(command[command.index("--output-schema") + 1])
            self.assertTrue(schema_path.is_file())
            image_paths = [
                Path(command[index + 1])
                for index, value in enumerate(command)
                if value == "--image"
            ]
            self.assertTrue(image_paths)
            self.assertTrue(all(path.is_file() for path in image_paths))
            output_path.write_text(
                json.dumps(
                    {
                        "state": "dialog_open",
                        "summary": "A dialog is visible.",
                        "relevant": True,
                        "confidence": 0.9,
                        "verification": "not_applicable",
                        "recommended_action": "Inspect the dialog.",
                        "evidence": ["Dialog title is visible"],
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        frame = np.zeros((32, 32, 3), dtype=np.uint8)
        event = PerceptionGateway(GatewayConfig(analysis_width=32)).observe_frame(
            frame, 0.0, goal="inspect", frame_index=0
        )
        assert event is not None
        interpreter = CodexExecInterpreter(
            command="codex-test", model="test-model", runner=fake_runner
        )

        result = interpreter.interpret(event.event, "inspect", None)

        command = captured["command"]
        assert isinstance(command, list)
        self.assertEqual(["codex-test", "exec"], command[:2])
        self.assertIn("--ephemeral", command)
        self.assertIn("--ignore-user-config", command)
        self.assertEqual("read-only", command[command.index("--sandbox") + 1])
        self.assertEqual("test-model", command[command.index("--model") + 1])
        self.assertEqual("dialog_open", result.state)
        self.assertAlmostEqual(0.9, result.confidence)
        self.assertEqual("not_applicable", result.verification)
        self.assertIn("Do not use tools", str(captured["prompt"]))

    def test_action_verification_prompt_requires_visible_confirmation(self) -> None:
        captured_prompt = ""

        def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            nonlocal captured_prompt
            captured_prompt = str(kwargs["input"])
            output_path = Path(command[command.index("--output-last-message") + 1])
            output_path.write_text(
                json.dumps(
                    {
                        "state": "saved",
                        "summary": "A saved confirmation is visible.",
                        "relevant": True,
                        "confidence": 0.95,
                        "verification": "confirmed",
                        "recommended_action": "Continue.",
                        "evidence": ["Saved label"],
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        frame = np.zeros((32, 32, 3), dtype=np.uint8)
        gateway = PerceptionGateway(GatewayConfig(analysis_width=32))
        gateway.observe_frame(frame, 0.0, goal="save", frame_index=0)
        event = gateway.verify_after_action(
            frame,
            frame,
            0.1,
            goal="save",
            action="clicked Save",
            expected_result="a saved confirmation is visible",
            frame_index=1,
        )

        result = CodexExecInterpreter(runner=fake_runner).interpret(
            event.event, "save", None
        )

        self.assertEqual("confirmed", result.verification)
        self.assertIn("clicked Save", captured_prompt)
        self.assertIn("a saved confirmation is visible", captured_prompt)
        self.assertIn("confirmed only when", captured_prompt)


if __name__ == "__main__":
    unittest.main()
