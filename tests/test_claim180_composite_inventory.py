from __future__ import annotations

from collections import Counter
import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = (
    ROOT / "benchmark-protocol" / "claim180-composite-event-inventory.json"
)
FINAL_TARGETS = {
    "small_ui": 30,
    "action_success": 24,
    "action_failure": 24,
    "popup_notification": 18,
    "loading_completion": 18,
    "scroll_navigation": 15,
    "cursor_hover_focus": 15,
    "animation_game_hud": 18,
    "transient_event": 18,
}


class Claim180CompositeInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
        cls.events = [
            event for case in cls.inventory["cases"] for event in case["events"]
        ]

    def test_inventory_is_exactly_claim180(self) -> None:
        self.assertEqual(180, len(self.events))
        self.assertEqual(
            FINAL_TARGETS,
            dict(Counter(event["category"] for event in self.events)),
        )
        self.assertEqual(
            180, len({event["source_transition_id"] for event in self.events})
        )
        self.assertTrue(all(event["real_world_eligible"] for event in self.events))

    def test_inventory_combines_only_frozen_component_identities(self) -> None:
        for component in self.inventory["component_inventories"].values():
            path = INVENTORY_PATH.parent / component["path"]
            self.assertEqual(component["bytes"], path.stat().st_size)
            self.assertEqual(
                component["sha256"], hashlib.sha256(path.read_bytes()).hexdigest()
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(component["inventory_id"], payload["inventory_id"])

    def test_inventory_identity_is_reproducible_and_has_no_local_paths(self) -> None:
        canonical = json.dumps(
            {
                key: value
                for key, value in self.inventory.items()
                if key != "inventory_id"
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        self.assertEqual(
            hashlib.sha256(canonical).hexdigest(), self.inventory["inventory_id"]
        )
        serialized = json.dumps(self.inventory)
        self.assertNotIn("C:\\", serialized)
        self.assertNotIn("benchmark-output", serialized)


if __name__ == "__main__":
    unittest.main()
