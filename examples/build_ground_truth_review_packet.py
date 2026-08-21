from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
from pathlib import Path
from typing import Any


def read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return payload


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def packet_id(payload: object) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def review_html(packet: dict[str, Any], review: dict[str, Any]) -> str:
    packet_json = json.dumps(packet, ensure_ascii=False).replace("</", "<\\/")
    review_json = json.dumps(review, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Signum ground-truth review</title>
<style>
body{{font:16px system-ui;margin:0;background:#111827;color:#f3f4f6}}main{{max-width:1180px;margin:auto;padding:24px}}
.bar,.card{{background:#1f2937;border:1px solid #374151;border-radius:12px;padding:16px;margin-bottom:16px}}
.images{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}img{{width:100%;border:1px solid #4b5563}}
fieldset{{border:0;padding:8px 0}}label{{margin-right:18px}}button,input,textarea{{font:inherit}}
button{{padding:10px 16px;margin-right:8px}}textarea{{width:100%;min-height:70px}}.bad{{color:#fca5a5}}
</style></head><body><main><div class="bar"><label>Reviewer <input id="reviewer"></label>
<span id="progress"></span></div><div id="card" class="card"></div><div class="bar">
<button onclick="move(-1)">Previous</button><button onclick="move(1)">Save & next</button>
<button onclick="downloadReview()">Export completed JSON</button><span id="message" class="bad"></span></div></main>
<script>const packet={packet_json};const review={review_json};let index=0;
const fields=['transition_visible','category_correct','expected_result_correct','before_after_order_correct'];
function save(){{const row=review.reviews[index];for(const field of fields){{const checked=document.querySelector(`input[name="${{field}}"]:checked`);row[field]=checked?checked.value==='true':null;}}row.notes=document.getElementById('notes').value;}}
function show(){{const item=packet.items[index],row=review.reviews[index];document.getElementById('progress').textContent=` ${{index+1}} / ${{packet.item_count}} — ${{item.blinded_id}}`;let verdicts='';for(const field of fields){{verdicts+=`<fieldset><strong>${{field.replaceAll('_',' ')}}</strong> <label><input type="radio" name="${{field}}" value="true" ${{row[field]===true?'checked':''}}>True</label><label><input type="radio" name="${{field}}" value="false" ${{row[field]===false?'checked':''}}>False</label></fieldset>`;}}document.getElementById('card').innerHTML=`<h2>${{item.blinded_id}}</h2><p><b>Category:</b> ${{item.proposed_category}}<br><b>Expected visible state:</b> ${{item.proposed_expected_result}}<br><b>Expected outcome:</b> ${{item.proposed_expected_outcome}}</p><div class="images"><div><h3>Before</h3><img src="${{item.before_image}}"></div><div><h3>After</h3><img src="${{item.after_image}}"></div></div>${{verdicts}}<label>Notes<textarea id="notes"></textarea></label>`;document.getElementById('notes').value=row.notes||'';}}
function move(delta){{save();index=Math.max(0,Math.min(packet.item_count-1,index+delta));show();}}
function downloadReview(){{save();const reviewer=document.getElementById('reviewer').value.trim();const incomplete=review.reviews.filter(row=>fields.some(field=>typeof row[field]!=='boolean'));if(!reviewer||incomplete.length){{document.getElementById('message').textContent=` Reviewer required; ${{incomplete.length}} items incomplete.`;return;}}review.reviewer=reviewer;review.reviewed_at_utc=new Date().toISOString();const blob=new Blob([JSON.stringify(review,null,2)+'\\n'],{{type:'application/json'}});const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download='completed-ground-truth-review.json';link.click();URL.revokeObjectURL(link.href);}}
show();</script></body></html>"""


def build_packet(
    inventory_path: Path,
    roots: dict[str, Path],
    output_root: Path,
    *,
    seed: str,
) -> dict[str, Any]:
    if output_root.exists() and any(output_root.iterdir()):
        raise RuntimeError(f"refusing to overwrite non-empty review root: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    evidence_root = output_root / "evidence"
    evidence_root.mkdir()
    inventory = read_object(inventory_path)
    if inventory.get("eligible_events") != 180:
        raise RuntimeError("ground-truth packet requires an exact 180-event inventory")
    rows = []
    for case in inventory.get("cases", []):
        origin = case.get("evidence_collection")
        if origin not in roots:
            raise RuntimeError(f"missing evidence root for {origin!r}")
        capture_path = roots[origin] / case["id"] / "capture.json"
        capture = read_object(capture_path)
        frames = {
            int(frame["sequence"]): frame for frame in capture.get("frames", [])
        }
        for event in case.get("events", []):
            before = frames.get(int(event["before_source_sequence"]))
            after = frames.get(int(event["after_source_sequence"]))
            if before is None or after is None:
                raise RuntimeError(f"event source frame is missing: {case['id']}/{event['id']}")
            rows.append(
                {
                    "case_id": case["id"],
                    "event_id": event["id"],
                    "source_transition_id": event["source_transition_id"],
                    "category": event["category"],
                    "expected_result": event["expected_result"],
                    "expected_outcome": event["expected_outcome"],
                    "before_source": roots[origin] / case["id"] / before["file"],
                    "after_source": roots[origin] / case["id"] / after["file"],
                }
            )
    if len(rows) != 180:
        raise RuntimeError("inventory did not expand to 180 review rows")
    randomizer = random.Random(seed)
    randomizer.shuffle(rows)
    public_rows = []
    mapping_rows = []
    for index, row in enumerate(rows, start=1):
        blinded_id = f"gt-{index:03d}"
        before_name = f"{blinded_id}-before.png"
        after_name = f"{blinded_id}-after.png"
        before_output = evidence_root / before_name
        after_output = evidence_root / after_name
        shutil.copyfile(row["before_source"], before_output)
        shutil.copyfile(row["after_source"], after_output)
        public_rows.append(
            {
                "blinded_id": blinded_id,
                "proposed_category": row["category"],
                "proposed_expected_result": row["expected_result"],
                "proposed_expected_outcome": row["expected_outcome"],
                "before_image": f"evidence/{before_name}",
                "before_sha256": sha256_file(before_output),
                "after_image": f"evidence/{after_name}",
                "after_sha256": sha256_file(after_output),
            }
        )
        mapping_rows.append(
            {
                "blinded_id": blinded_id,
                "case_id": row["case_id"],
                "event_id": row["event_id"],
                "source_transition_id": row["source_transition_id"],
            }
        )
    packet = {
        "schema_version": 1,
        "kind": "signum_ground_truth_review_packet",
        "inventory": {
            "path": inventory_path.name,
            "bytes": inventory_path.stat().st_size,
            "sha256": sha256_file(inventory_path),
            "inventory_id": inventory["inventory_id"],
        },
        "randomization_seed": seed,
        "method_outputs_included": False,
        "item_count": len(public_rows),
        "items": public_rows,
    }
    packet["packet_id"] = packet_id(packet)
    (output_root / "packet.json").write_text(
        json.dumps(packet, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    mapping = {
        "schema_version": 1,
        "kind": "signum_ground_truth_review_mapping",
        "packet_id": packet["packet_id"],
        "coordinator_only": True,
        "inventory_id": inventory["inventory_id"],
        "items": mapping_rows,
    }
    (output_root / "mapping.json").write_text(
        json.dumps(mapping, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    for reviewer_name in ("reviewer-a", "reviewer-b"):
        review = {
            "schema_version": 1,
            "kind": "signum_ground_truth_review",
            "packet_id": packet["packet_id"],
            "reviewer": "",
            "review_method": "independent_blind_before_after",
            "reviewed_at_utc": "",
            "instructions": (
                "Do not inspect Signum, uniform, OpenAI, or Claude outputs. For each "
                "item, judge the frozen before/after pixels and proposed label. Set "
                "every verdict to true or false; use corrections only when a verdict "
                "is false."
            ),
            "reviews": [
                {
                    "blinded_id": item["blinded_id"],
                    "transition_visible": None,
                    "category_correct": None,
                    "expected_result_correct": None,
                    "before_after_order_correct": None,
                    "corrected_category": None,
                    "corrected_expected_result": None,
                    "notes": "",
                }
                for item in public_rows
            ],
        }
        (output_root / f"{reviewer_name}.json").write_text(
            json.dumps(review, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (output_root / f"{reviewer_name}.html").write_text(
            review_html(packet, review), encoding="utf-8"
        )
    return packet


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a two-reviewer, method-blind ground-truth packet."
    )
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--v3-root", type=Path)
    parser.add_argument("--supplement-root", type=Path)
    parser.add_argument("--v4-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", required=True)
    args = parser.parse_args()
    roots = {
        name: path.resolve()
        for name, path in {
            "v3": args.v3_root,
            "supplement": args.supplement_root,
            "v4": args.v4_root,
        }.items()
        if path is not None
    }
    if not roots:
        parser.error("at least one evidence root is required")
    packet = build_packet(
        args.inventory.resolve(),
        roots,
        args.output.resolve(),
        seed=args.seed,
    )
    print(
        json.dumps(
            {
                "packet_id": packet["packet_id"],
                "items": packet["item_count"],
                "method_outputs_included": packet["method_outputs_included"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
