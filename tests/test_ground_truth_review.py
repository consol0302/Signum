from __future__ import annotations

import base64
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_example(name: str):
    path = ROOT / "examples" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PACKET_MODULE = load_example("build_ground_truth_review_packet.py")
COMPARE_MODULE = load_example("compare_ground_truth_reviews.py")
LOCK_MODULE = load_example("lock_ground_truth_review_packet.py")


class GroundTruthReviewTests(unittest.TestCase):
    def test_published_exact_duplicate_review_lock_is_internally_complete(self) -> None:
        path = (
            ROOT
            / "benchmark-protocol"
            / "claim180-v4-exact-duplicate-review-lock.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        lock_id = payload.pop("lock_id")
        member_ids = [
            blinded_id
            for group in payload["groups"]
            for blinded_id in group["member_blinded_ids"]
        ]

        self.assertEqual(lock_id, PACKET_MODULE.packet_id(payload))
        self.assertEqual(180, payload["original_item_count"])
        self.assertEqual(108, payload["unique_decision_count"])
        self.assertEqual(72, payload["propagated_item_count"])
        self.assertEqual(180, len(member_ids))
        self.assertEqual(180, len(set(member_ids)))
        self.assertFalse(payload["method_outputs_included"])

    def test_exact_duplicate_review_groups_only_identical_evidence_and_labels(self) -> None:
        base = {
            "before_sha256": "before-a",
            "after_sha256": "after-a",
            "proposed_category": "small_ui",
            "proposed_expected_result": "a compact numeric value is visible in the first field",
            "proposed_expected_outcome": "success",
        }
        packet = {
            "packet_id": "packet-dedup",
            "item_count": 3,
            "items": [
                {"blinded_id": "gt-001", **base},
                {"blinded_id": "gt-002", **base},
                {
                    "blinded_id": "gt-003",
                    **base,
                    "after_sha256": "after-b",
                },
            ],
        }
        groups = PACKET_MODULE.exact_duplicate_review_groups(packet)

        self.assertEqual(2, len(groups))
        self.assertEqual(
            ["gt-001", "gt-002"], groups[0]["member_blinded_ids"]
        )
        self.assertEqual(2, groups[0]["multiplicity"])
        review = {
            "packet_id": "packet-dedup",
            "reviewer": "",
            "reviews": [
                {
                    "blinded_id": item["blinded_id"],
                    "transition_visible": None,
                    "category_correct": None,
                    "expected_result_correct": None,
                    "before_after_order_correct": None,
                    "notes": "",
                }
                for item in packet["items"]
            ],
        }
        html = PACKET_MODULE.korean_review_html(
            packet, review, strict=True, deduplicate_exact=True
        )
        self.assertIn("고유 판정 2개", html)
        self.assertIn("정확히 동일한 중복 1개", html)
        self.assertIn("진행 상황 JSON 백업", html)
        self.assertIn("independent_blind_before_after_exact_duplicate_propagation", html)

    def test_generated_validation_packet_is_method_blind_and_integrity_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capture_root = root / "captures"
            case_root = capture_root / "case-001"
            case_root.mkdir(parents=True)
            pixel = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
                "/x8AAusB9Y9ZFlcAAAAASUVORK5CYII="
            )
            (case_root / "before.png").write_bytes(pixel)
            (case_root / "after.png").write_bytes(pixel)
            (case_root / "capture.json").write_text(
                json.dumps(
                    {
                        "frames": [
                            {"sequence": 0, "file": "before.png"},
                            {"sequence": 1, "file": "after.png"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            inventory = {
                "inventory_id": "synthetic-inventory",
                "eligible_events": 180,
                "cases": [
                    {
                        "id": "case-001",
                        "evidence_collection": "v3",
                        "events": [
                            {
                                "id": f"event-{index:03d}",
                                "source_transition_id": f"transition-{index:03d}",
                                "category": "small_ui",
                                "expected_result": f"state {index} is visible",
                                "expected_outcome": "success",
                                "before_source_sequence": 0,
                                "after_source_sequence": 1,
                            }
                            for index in range(180)
                        ],
                    }
                ],
            }
            inventory_path = root / "inventory.json"
            inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
            output_root = root / "packet"
            packet = PACKET_MODULE.build_packet(
                inventory_path,
                {"v3": capture_root},
                output_root,
                seed="unit-test-seed",
            )

            self.assertEqual(180, packet["item_count"])
            self.assertFalse(packet["method_outputs_included"])
            self.assertEqual(180, len({row["blinded_id"] for row in packet["items"]}))
            self.assertTrue(all("source_transition_id" not in row for row in packet["items"]))
            self.assertTrue(all("case_id" not in row for row in packet["items"]))
            mapping = json.loads(
                (output_root / "mapping.json").read_text(encoding="utf-8")
            )
            self.assertTrue(mapping["coordinator_only"])
            self.assertEqual(packet["packet_id"], mapping["packet_id"])
            self.assertEqual(180, len(mapping["items"]))
            html = (output_root / "reviewer-a.html").read_text(encoding="utf-8")
            self.assertIn("Export completed JSON", html)
            self.assertNotIn("source_transition_id", html)
            korean_html = PACKET_MODULE.korean_review_html(
                packet,
                json.loads(
                    (output_root / "reviewer-a.json").read_text(encoding="utf-8")
                ),
            )
            self.assertIn('lang="ko"', korean_html)
            self.assertIn("완료한 JSON 내보내기", korean_html)
            self.assertIn("전환 결과가 화면에서 확인됩니까?", korean_html)
            self.assertNotIn("source_transition_id", korean_html)
            generated_korean_html = (
                output_root / "reviewer-a.ko.html"
            ).read_text(encoding="utf-8")
            self.assertIn("완료한 JSON 내보내기", generated_korean_html)
            self.assertNotIn("source_transition_id", generated_korean_html)
            for row in packet["items"]:
                for prefix in ("before", "after"):
                    path = output_root / row[f"{prefix}_image"]
                    self.assertTrue(path.is_file())
                    self.assertEqual(
                        row[f"{prefix}_sha256"], PACKET_MODULE.sha256_file(path)
                    )
            lock = LOCK_MODULE.build_lock(output_root)
            self.assertEqual(packet["packet_id"], lock["packet_id"])
            self.assertFalse(lock["method_outputs_included"])
            self.assertEqual(360, lock["evidence"]["file_count"])
            self.assertEqual(2, len(lock["reviewer_templates"]))

    def test_comparison_requires_complete_distinct_reviews_and_exposes_disagreement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet = {
                "packet_id": "packet-1",
                "items": [{"blinded_id": "gt-001"}, {"blinded_id": "gt-002"}],
            }
            packet_path = root / "packet.json"
            packet_path.write_text(json.dumps(packet), encoding="utf-8")

            def write_review(path: Path, reviewer: str, second_visible: bool) -> None:
                path.write_text(
                    json.dumps(
                        {
                            "packet_id": "packet-1",
                            "reviewer": reviewer,
                            "reviews": [
                                {
                                    "blinded_id": blinded_id,
                                    "transition_visible": (
                                        True if blinded_id == "gt-001" else second_visible
                                    ),
                                    "category_correct": True,
                                    "expected_result_correct": True,
                                    "before_after_order_correct": True,
                                    "corrected_category": None,
                                    "corrected_expected_result": None,
                                }
                                for blinded_id in ("gt-001", "gt-002")
                            ],
                        }
                    ),
                    encoding="utf-8",
                )

            review_a = root / "a.json"
            review_b = root / "b.json"
            write_review(review_a, "reviewer-a", True)
            write_review(review_b, "reviewer-b", False)

            comparison = COMPARE_MODULE.compare_reviews(
                packet_path, review_a, review_b
            )

            self.assertEqual(1, comparison["agreement_count"])
            self.assertEqual(1, comparison["disagreement_count"])
            self.assertFalse(comparison["complete_without_adjudication"])

    def test_matching_negative_verdicts_still_require_adjudication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet_path = root / "packet.json"
            packet_path.write_text(
                json.dumps(
                    {"packet_id": "packet-2", "items": [{"blinded_id": "gt-001"}]}
                ),
                encoding="utf-8",
            )
            paths = []
            for reviewer in ("reviewer-a", "reviewer-b"):
                path = root / f"{reviewer}.json"
                path.write_text(
                    json.dumps(
                        {
                            "packet_id": "packet-2",
                            "reviewer": reviewer,
                            "reviews": [
                                {
                                    "blinded_id": "gt-001",
                                    "transition_visible": False,
                                    "category_correct": True,
                                    "expected_result_correct": True,
                                    "before_after_order_correct": True,
                                    "corrected_category": None,
                                    "corrected_expected_result": None,
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                paths.append(path)

            comparison = COMPARE_MODULE.compare_reviews(
                packet_path, paths[0], paths[1]
            )

            self.assertEqual(0, comparison["agreement_count"])
            self.assertEqual(1, comparison["disagreement_count"])
            self.assertFalse(comparison["complete_without_adjudication"])


if __name__ == "__main__":
    unittest.main()
