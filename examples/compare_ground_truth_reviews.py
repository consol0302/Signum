from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


VERDICT_FIELDS = (
    "transition_visible",
    "category_correct",
    "expected_result_correct",
    "before_after_order_correct",
)


def read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return payload


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare_reviews(
    packet_path: Path,
    review_a_path: Path,
    review_b_path: Path,
) -> dict[str, Any]:
    packet = read_object(packet_path)
    reviews = [read_object(review_a_path), read_object(review_b_path)]
    packet_id = packet.get("packet_id")
    reviewers = []
    indexes = []
    for review in reviews:
        if review.get("packet_id") != packet_id:
            raise RuntimeError("review does not belong to the packet")
        reviewer = review.get("reviewer")
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise RuntimeError("reviewer identity must be non-empty")
        reviewers.append(reviewer.strip())
        rows = review.get("reviews")
        if not isinstance(rows, list):
            raise RuntimeError("review must contain a reviews array")
        index = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("blinded_id"), str):
                raise RuntimeError("review rows must have blinded ids")
            if row["blinded_id"] in index:
                raise RuntimeError("review contains duplicate blinded ids")
            for field in VERDICT_FIELDS:
                if not isinstance(row.get(field), bool):
                    raise RuntimeError(f"review verdict {field!r} must be completed")
            index[row["blinded_id"]] = row
        indexes.append(index)
    if reviewers[0] == reviewers[1]:
        raise RuntimeError("independent reviews require distinct reviewer identities")
    item_ids = [item["blinded_id"] for item in packet.get("items", [])]
    if any(set(index) != set(item_ids) for index in indexes):
        raise RuntimeError("review rows do not exactly cover the packet")
    agreements = []
    disagreements = []
    for blinded_id in item_ids:
        left = indexes[0][blinded_id]
        right = indexes[1][blinded_id]
        verdict_agreement = all(left[field] == right[field] for field in VERDICT_FIELDS)
        correction_agreement = (
            left.get("corrected_category") == right.get("corrected_category")
            and left.get("corrected_expected_result")
            == right.get("corrected_expected_result")
        )
        negative_verdict = any(
            not review[field] for review in (left, right) for field in VERDICT_FIELDS
        )
        row = {
            "blinded_id": blinded_id,
            "reviewer_a": {field: left.get(field) for field in VERDICT_FIELDS},
            "reviewer_b": {field: right.get(field) for field in VERDICT_FIELDS},
            "correction_a": {
                "category": left.get("corrected_category"),
                "expected_result": left.get("corrected_expected_result"),
            },
            "correction_b": {
                "category": right.get("corrected_category"),
                "expected_result": right.get("corrected_expected_result"),
            },
        }
        requires_adjudication = (
            not verdict_agreement or not correction_agreement or negative_verdict
        )
        (disagreements if requires_adjudication else agreements).append(row)
    return {
        "schema_version": 1,
        "kind": "signum_ground_truth_review_comparison",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "packet_id": packet_id,
        "packet_sha256": sha256_file(packet_path),
        "reviewers": reviewers,
        "review_sha256": [sha256_file(review_a_path), sha256_file(review_b_path)],
        "item_count": len(item_ids),
        "agreement_count": len(agreements),
        "disagreement_count": len(disagreements),
        "complete_without_adjudication": not disagreements,
        "agreements": agreements,
        "adjudication_required": disagreements,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare two completed independent ground-truth reviews."
    )
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--review-a", type=Path, required=True)
    parser.add_argument("--review-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite comparison: {args.output}")
    payload = compare_reviews(
        args.packet.resolve(), args.review_a.resolve(), args.review_b.resolve()
    )
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "items": payload["item_count"],
                "agreements": payload["agreement_count"],
                "disagreements": payload["disagreement_count"],
                "complete_without_adjudication": payload[
                    "complete_without_adjudication"
                ],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
