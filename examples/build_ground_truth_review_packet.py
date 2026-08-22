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


EXACT_REVIEW_EQUIVALENCE_FIELDS = (
    "before_sha256",
    "after_sha256",
    "proposed_category",
    "proposed_expected_result",
    "proposed_expected_outcome",
)


def exact_duplicate_review_groups(packet: dict[str, Any]) -> list[dict[str, Any]]:
    """Group only items whose evidence pixels and proposed labels are identical."""
    groups: list[dict[str, Any]] = []
    by_key: dict[tuple[object, ...], dict[str, Any]] = {}
    items = packet.get("items")
    if not isinstance(items, list):
        raise RuntimeError("review packet must contain an items array")
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("blinded_id"), str):
            raise RuntimeError("review packet items must have blinded ids")
        key = tuple(item.get(field) for field in EXACT_REVIEW_EQUIVALENCE_FIELDS)
        if any(value is None for value in key):
            raise RuntimeError("review packet item is missing an equivalence field")
        group = by_key.get(key)
        if group is None:
            group = {
                "group_id": f"exact-{len(groups) + 1:03d}",
                "representative_blinded_id": item["blinded_id"],
                "member_blinded_ids": [],
            }
            by_key[key] = group
            groups.append(group)
        group["member_blinded_ids"].append(item["blinded_id"])
    for group in groups:
        group["multiplicity"] = len(group["member_blinded_ids"])
    return groups


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


def korean_review_html(
    packet: dict[str, Any],
    review: dict[str, Any],
    *,
    strict: bool = False,
    deduplicate_exact: bool = False,
) -> str:
    """Render a Korean reviewer UI without changing the locked review schema."""
    packet_json = json.dumps(packet, ensure_ascii=False).replace("</", "<\\/")
    review_json = json.dumps(review, ensure_ascii=False).replace("</", "<\\/")
    field_labels = {
        "transition_visible": "전환 결과가 화면에서 확인됩니까?",
        "category_correct": "제안된 화면 변화 분류가 맞습니까?",
        "expected_result_correct": "제안된 변화 설명이 실제 화면과 일치합니까?",
        "before_after_order_correct": "작업 전/후 이미지 순서가 맞습니까?",
    }
    category_labels = {
        "action_failure": "작업 실패",
        "action_success": "작업 성공",
        "animation_game_hud": "애니메이션·게임 HUD",
        "cursor_hover_focus": "커서 호버·포커스",
        "loading_completion": "로딩 완료",
        "popup_notification": "팝업·알림",
        "scroll_navigation": "스크롤 이동",
        "small_ui": "작은 UI 요소",
        "transient_event": "일시적 이벤트",
    }
    result_labels = {
        "a compact numeric value is visible in the first field": "첫 번째 입력 칸에 작은 숫자 값이 표시된다",
        "a later part of the TestPages document enters view": "TestPages 문서의 뒤쪽 영역이 화면에 들어온다",
        "a later PlayLab region enters the viewport": "PlayLab의 뒤쪽 영역이 화면에 들어온다",
        "a new dynamic element appears": "새로운 동적 요소가 나타난다",
        "a new list item appears": "새 목록 항목이 나타난다",
        "a temporary hover info bubble appears": "호버 정보 말풍선이 잠시 나타난다",
        "a temporary success toast appears": "성공 토스트 알림이 잠시 나타난다",
        "a temporary warning toast appears": "경고 토스트 알림이 잠시 나타난다",
        "delayed content is fully visible": "지연된 콘텐츠가 완전히 표시된다",
        "download progress starts moving": "다운로드 진행 표시가 움직이기 시작한다",
        "empty registration remains rejected with validation feedback": "빈 등록 요청이 검증 안내와 함께 계속 거부된다",
        "hover feedback becomes visible": "호버 반응이 화면에 나타난다",
        "later products enter the viewport": "뒤쪽 상품들이 화면에 들어온다",
        "login remains rejected with an error message": "로그인이 오류 메시지와 함께 계속 거부된다",
        "one small skill checkbox becomes selected": "작은 스킬 체크박스 하나가 선택된다",
        "the actively changing countdown briefly stops": "변화 중이던 카운트다운이 잠시 멈춘다",
        "the bold formatting control becomes active": "굵게 서식 버튼이 활성화된다",
        "the calculation control receives visible pointer focus": "계산 컨트롤에 포인터 포커스가 표시된다",
        "the carousel animates to the next slide": "캐러셀이 다음 슬라이드로 움직인다",
        "the circular loading HUD appears": "원형 로딩 HUD가 나타난다",
        "the click information popup is visible": "클릭 정보 팝업이 표시된다",
        "the compact seconds field shows the configured value": "작은 초 입력 칸에 설정한 값이 표시된다",
        "the countdown display disappears": "카운트다운 표시가 사라진다",
        "the countdown HUD begins updating": "카운트다운 HUD가 갱신되기 시작한다",
        "the countdown HUD visibly resets": "카운트다운 HUD가 화면상 초기화된다",
        "the delayed data completion message is visible": "지연 데이터 완료 메시지가 표시된다",
        "the hover tooltip appears": "호버 툴팁이 나타난다",
        "the italic formatting control becomes active": "기울임꼴 서식 버튼이 활성화된다",
        "the live timer begins updating": "실시간 타이머가 갱신되기 시작한다",
        "the modal dialog is visible": "모달 대화상자가 표시된다",
        "the non-JavaScript modal alert is visible": "JavaScript를 사용하지 않는 모달 알림이 표시된다",
        "the progress HUD visibly changes by ten percent": "진행률 HUD가 화면상 10퍼센트 변한다",
        "the server visibly returns an unknown-token error": "서버가 알 수 없는 토큰 오류를 화면에 표시한다",
        "the server visibly shows the correct calculation result": "서버가 올바른 계산 결과를 화면에 표시한다",
        "the server-rendered calculation answer is visible": "서버에서 렌더링한 계산 답이 표시된다",
        "the timer accepts the value and visibly resets its HUD": "타이머가 값을 받아들이고 HUD를 화면상 초기화한다",
        "the timer control receives visible pointer focus": "타이머 컨트롤에 포인터 포커스가 표시된다",
    }
    outcome_labels = {"success": "성공", "failure": "실패"}
    translation_groups = {
        "categories": (
            category_labels,
            {item["proposed_category"] for item in packet["items"]},
        ),
        "results": (
            result_labels,
            {item["proposed_expected_result"] for item in packet["items"]},
        ),
        "outcomes": (
            outcome_labels,
            {item["proposed_expected_outcome"] for item in packet["items"]},
        ),
    }
    for group, (translations, values) in translation_groups.items():
        missing = sorted(values.difference(translations))
        if strict and missing:
            raise RuntimeError(f"missing Korean {group} translations: {missing}")
    labels_json = json.dumps(
        {
            "fields": field_labels,
            "categories": category_labels,
            "results": result_labels,
            "outcomes": outcome_labels,
        },
        ensure_ascii=False,
    ).replace("</", "<\\/")
    if deduplicate_exact:
        groups = exact_duplicate_review_groups(packet)
    else:
        groups = [
            {
                "group_id": f"item-{index:03d}",
                "representative_blinded_id": item["blinded_id"],
                "member_blinded_ids": [item["blinded_id"]],
                "multiplicity": 1,
            }
            for index, item in enumerate(packet["items"], start=1)
        ]
    groups_json = json.dumps(groups, ensure_ascii=False).replace("</", "<\\/")
    deduplicate_json = json.dumps(deduplicate_exact)
    if deduplicate_exact:
        mode_guide = (
            f"<p><b>정확히 동일한 중복 {packet['item_count'] - len(groups)}개를 숨겼습니다.</b> "
            f"고유 판정 {len(groups)}개만 검수하면 동일한 이미지·분류·설명의 원래 행에 "
            "같은 답이 자동 적용됩니다.</p>"
        )
    else:
        mode_guide = ""
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>Signum 정답 데이터 검수</title>
<style>
body{{font:16px system-ui;margin:0;background:#111827;color:#f3f4f6}}main{{max-width:1180px;margin:auto;padding:24px}}
.bar,.card,.guide{{background:#1f2937;border:1px solid #374151;border-radius:12px;padding:16px;margin-bottom:16px}}
.guide{{line-height:1.6}}.guide h1{{font-size:1.25rem;margin:0 0 8px}}.guide p{{margin:4px 0}}
.images{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}img{{width:100%;border:1px solid #4b5563}}
fieldset{{border:0;padding:8px 0}}label{{margin-right:18px}}button,input,textarea{{font:inherit}}
button{{padding:10px 16px;margin-right:8px}}textarea{{width:100%;min-height:70px}}.bad{{color:#fca5a5}}
@media (max-width:760px){{.images{{grid-template-columns:1fr}}}}
</style></head><body><main><section class="guide"><h1>Signum 독립 블라인드 검수</h1>
<p>Signum, 균등 샘플링, OpenAI 또는 Claude의 판독 결과는 확인하지 마세요.</p>
<p>각 항목에서 고정된 작업 전·후 이미지와 제안된 설명만 보고 네 질문에 모두 답하세요. 확실하지 않더라도 보이는 픽셀을 기준으로 예 또는 아니요를 선택하고, 아니요를 선택한 이유는 검수 메모에 적어 주세요.</p>
{mode_guide}
<p>검수자 A와 B는 서로 상의하지 않고 독립적으로 완료해야 합니다.</p></section>
<div class="bar"><label>검수자 이름 <input id="reviewer" autocomplete="off"></label>
<span id="progress"></span></div><div id="card" class="card"></div><div class="bar">
<button onclick="move(-1)">이전</button><button onclick="move(1)">저장하고 다음</button>
<button onclick="downloadProgress()">진행 상황 JSON 백업</button>
<button onclick="downloadReview()">완료한 JSON 내보내기</button><span id="message" class="bad"></span></div></main>
<script>const packet={packet_json};let review={review_json};const labels={labels_json};const groups={groups_json};const deduplicateExact={deduplicate_json};let index=0;
const fields=['transition_visible','category_correct','expected_result_correct','before_after_order_correct'];
const itemById=Object.fromEntries(packet.items.map(item=>[item.blinded_id,item]));
const storageKey=`signum-review:${{packet.packet_id}}:${{location.pathname}}`;
let restoredReviewer='';
try{{const saved=JSON.parse(localStorage.getItem(storageKey)||'null');if(saved&&saved.review&&saved.review.packet_id===packet.packet_id){{review=saved.review;restoredReviewer=saved.reviewer||'';index=Math.max(0,Math.min(groups.length-1,Number(saved.index)||0));}}}}catch(error){{document.getElementById('message').textContent=' 자동 저장을 사용할 수 없습니다. 진행 상황 JSON을 자주 백업하세요.';}}
const rowById=Object.fromEntries(review.reviews.map(row=>[row.blinded_id,row]));
document.getElementById('reviewer').value=restoredReviewer||review.reviewer||'';
function localized(group,value){{return labels[group][value]||value;}}
function completedGroupCount(){{return groups.filter(group=>fields.every(field=>typeof rowById[group.representative_blinded_id][field]==='boolean')).length;}}
function refreshProgress(){{const group=groups[index];document.getElementById('progress').textContent=` ${{index+1}} / ${{groups.length}} — 완료 ${{completedGroupCount()}}개 — ${{group.representative_blinded_id}}`;}}
function save(){{const group=groups[index];if(!document.getElementById('notes'))return;const values={{}};for(const field of fields){{const checked=document.querySelector(`input[name="${{field}}"]:checked`);values[field]=checked?checked.value==='true':null;}}const notes=document.getElementById('notes').value;for(const blindedId of group.member_blinded_ids){{const row=rowById[blindedId];for(const field of fields)row[field]=values[field];row.notes=notes;}}refreshProgress();}}
function persist(){{save();try{{localStorage.setItem(storageKey,JSON.stringify({{review,reviewer:document.getElementById('reviewer').value.trim(),index}}));}}catch(error){{document.getElementById('message').textContent=' 자동 저장에 실패했습니다. 진행 상황 JSON을 백업하세요.';}}}}
function show(){{const group=groups[index],item=itemById[group.representative_blinded_id],row=rowById[group.representative_blinded_id];let verdicts='';for(const field of fields){{verdicts+=`<fieldset><strong>${{labels.fields[field]}}</strong> <label><input type="radio" name="${{field}}" value="true" ${{row[field]===true?'checked':''}}>예</label><label><input type="radio" name="${{field}}" value="false" ${{row[field]===false?'checked':''}}>아니요</label></fieldset>`;}}const duplicateNote=group.multiplicity>1?`<p><b>이 판정은 완전히 동일한 ${{group.multiplicity}}개 원본 항목에 적용됩니다.</b></p>`:'';document.getElementById('card').innerHTML=`<h2>${{item.blinded_id}}</h2>${{duplicateNote}}<p><b>제안된 분류:</b> ${{localized('categories',item.proposed_category)}}<br><b>제안된 변화 설명:</b> ${{localized('results',item.proposed_expected_result)}}<br><b>예상 작업 결과:</b> ${{localized('outcomes',item.proposed_expected_outcome)}}</p><div class="images"><div><h3>작업 전</h3><img src="${{item.before_image}}" alt="작업 전 화면"></div><div><h3>작업 후</h3><img src="${{item.after_image}}" alt="작업 후 화면"></div></div>${{verdicts}}<label>검수 메모 (선택 사항)<textarea id="notes"></textarea></label>`;document.getElementById('notes').value=row.notes||'';refreshProgress();}}
function move(delta){{persist();index=Math.max(0,Math.min(groups.length-1,index+delta));show();try{{localStorage.setItem(storageKey,JSON.stringify({{review,reviewer:document.getElementById('reviewer').value.trim(),index}}));}}catch(error){{}}window.scrollTo(0,0);}}
function prepareExport(){{persist();review.reviewer=document.getElementById('reviewer').value.trim();review.review_method=deduplicateExact?'independent_blind_before_after_exact_duplicate_propagation':'independent_blind_before_after';review.deduplication={{enabled:deduplicateExact,equivalence_fields:{json.dumps(list(EXACT_REVIEW_EQUIVALENCE_FIELDS))},original_item_count:packet.item_count,unique_decision_count:groups.length,propagated_item_count:packet.item_count-groups.length,groups:groups.map(group=>({{group_id:group.group_id,representative_blinded_id:group.representative_blinded_id,member_blinded_ids:group.member_blinded_ids}}))}};}}
function downloadJson(filename){{const blob=new Blob([JSON.stringify(review,null,2)+'\\n'],{{type:'application/json'}});const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=filename;link.click();URL.revokeObjectURL(link.href);}}
function downloadProgress(){{prepareExport();downloadJson('ground-truth-review-progress.json');document.getElementById('message').textContent=` 진행 상황을 백업했습니다. 고유 항목 ${{completedGroupCount()}} / ${{groups.length}}개 완료.`;}}
function downloadReview(){{prepareExport();const incomplete=groups.length-completedGroupCount();if(!review.reviewer||incomplete){{document.getElementById('message').textContent=` 검수자 이름을 입력해야 하며, 미완료 고유 항목이 ${{incomplete}}개 있습니다.`;return;}}review.reviewed_at_utc=new Date().toISOString();downloadJson('completed-ground-truth-review.json');document.getElementById('message').textContent=' 완료한 JSON 파일을 내보냈습니다.';}}
document.getElementById('card').addEventListener('change',persist);document.getElementById('card').addEventListener('input',persist);document.getElementById('reviewer').addEventListener('input',persist);window.addEventListener('beforeunload',persist);show();</script></body></html>"""


def build_packet(
    inventory_path: Path,
    roots: dict[str, Path],
    output_root: Path,
    *,
    seed: str,
    expected_items: int = 180,
) -> dict[str, Any]:
    if output_root.exists() and any(output_root.iterdir()):
        raise RuntimeError(f"refusing to overwrite non-empty review root: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    evidence_root = output_root / "evidence"
    evidence_root.mkdir()
    inventory = read_object(inventory_path)
    if inventory.get("eligible_events") != expected_items:
        raise RuntimeError(
            f"ground-truth packet requires exactly {expected_items} inventory events"
        )
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
    if len(rows) != expected_items:
        raise RuntimeError(f"inventory did not expand to {expected_items} review rows")
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
        (output_root / f"{reviewer_name}.ko.html").write_text(
            korean_review_html(packet, review), encoding="utf-8"
        )
        (output_root / f"{reviewer_name}.unique.ko.html").write_text(
            korean_review_html(packet, review, deduplicate_exact=True),
            encoding="utf-8",
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
    parser.add_argument("--reserve-v2-root", type=Path)
    parser.add_argument("--expected-items", type=int, default=180)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", required=True)
    args = parser.parse_args()
    roots = {
        name: path.resolve()
        for name, path in {
            "v3": args.v3_root,
            "supplement": args.supplement_root,
            "v4": args.v4_root,
            "v4_visibility_reserve_v2": args.reserve_v2_root,
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
        expected_items=args.expected_items,
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
