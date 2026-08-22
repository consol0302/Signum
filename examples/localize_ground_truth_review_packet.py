from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_ground_truth_review_packet import korean_review_html


def read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return payload


def localize_packet(packet_root: Path) -> list[Path]:
    packet_path = packet_root / "packet.json"
    packet = read_object(packet_path)
    outputs = []
    for reviewer_name in ("reviewer-a", "reviewer-b"):
        review_path = packet_root / f"{reviewer_name}.json"
        review = read_object(review_path)
        if review.get("packet_id") != packet.get("packet_id"):
            raise RuntimeError(f"{reviewer_name} template belongs to a different packet")
        output = packet_root / f"{reviewer_name}.ko.html"
        output.write_text(
            korean_review_html(packet, review, strict=True), encoding="utf-8"
        )
        outputs.append(output)
        unique_output = packet_root / f"{reviewer_name}.unique.ko.html"
        unique_output.write_text(
            korean_review_html(
                packet, review, strict=True, deduplicate_exact=True
            ),
            encoding="utf-8",
        )
        outputs.append(unique_output)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add Korean reviewer interfaces without changing locked artifacts."
    )
    parser.add_argument("packet_roots", type=Path, nargs="+")
    args = parser.parse_args()
    for packet_root in args.packet_roots:
        for output in localize_packet(packet_root.resolve()):
            print(output)


if __name__ == "__main__":
    main()
