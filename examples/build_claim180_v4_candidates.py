from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable


CAPTURE_POLICY = {
    "requested_fps": 15,
    "width": 1280,
    "height": 720,
    "minimum_average_fps": 10,
    # Full-document navigation can pause Chromium screenshots briefly even when
    # the run sustains the requested average rate. Keep the bound explicit and
    # record every timestamp so downstream extraction can audit the gap.
    "maximum_gap_seconds": 0.75,
    "screenshot_timeout_ms": 200,
}

CATEGORY_TARGETS = {
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


def css(value: str) -> dict[str, Any]:
    return {"by": "css", "value": value}


def role(role_name: str, name: str, *, exact: bool = True) -> dict[str, Any]:
    return {
        "by": "role",
        "role": role_name,
        "name": name,
        "exact": exact,
    }


class Flow:
    def __init__(self, case_id: str, slot_id: str, url: str, goal: str) -> None:
        self.case_id = case_id
        self.slot_id = slot_id
        self.url = url
        self.goal = goal
        self.actions: list[dict[str, Any]] = []
        self.targets: list[dict[str, str]] = []
        self.time = 0.35
        self.sequence = 0

    def add(
        self,
        name: str,
        kind: str,
        *,
        expected_result: str,
        delay: float = 0.55,
        target_category: str | None = None,
        expected_outcome: str = "success",
        required: bool = True,
        **fields: Any,
    ) -> str:
        self.time += delay
        self.sequence += 1
        action_id = f"{self.sequence:02d}-{name}"
        self.actions.append(
            {
                "id": action_id,
                "at_seconds": round(self.time, 2),
                "type": kind,
                "expected_outcome": expected_outcome,
                "expected_result": expected_result,
                "required": required,
                **fields,
            }
        )
        if target_category is not None:
            self.targets.append(
                {"action_id": action_id, "category": target_category}
            )
        return action_id

    def prepare(self, name: str, kind: str, **fields: Any) -> str:
        return self.add(
            name,
            kind,
            expected_result=f"preparation step {name} completes",
            **fields,
        )

    def target(self, category: str, name: str, kind: str, **fields: Any) -> str:
        action_id = self.add(name, kind, target_category=category, **fields)
        # Reserve a post-action observation window before any following action.
        # Independent verification later requires at least one captured frame in
        # this settled interval; this is part of evidence quality, not sampling.
        self.time += 0.75
        return action_id

    def finish(self) -> dict[str, Any]:
        if len(self.targets) != 6:
            raise RuntimeError(f"{self.case_id} must bind exactly six target events")
        return {
            "case_id": self.case_id,
            "slot_id": self.slot_id,
            "url": self.url,
            "goal": self.goal,
            "duration_seconds": max(14, int(self.time + 3.5)),
            "actions": self.actions,
            "target_events": self.targets,
        }


def category_templates() -> list[list[str]]:
    a = [
        "popup_notification",
        "small_ui",
        "action_failure",
        "loading_completion",
        "action_success",
        "scroll_navigation",
    ]
    b = [
        "popup_notification",
        "small_ui",
        "action_failure",
        "loading_completion",
        "action_success",
        "cursor_hover_focus",
    ]
    c = [
        "small_ui",
        "action_failure",
        "animation_game_hud",
        "action_success",
        "transient_event",
        "scroll_navigation",
    ]
    d = [
        "small_ui",
        "action_failure",
        "animation_game_hud",
        "action_success",
        "transient_event",
        "cursor_hover_focus",
    ]
    e = [
        "popup_notification",
        "small_ui",
        "loading_completion",
        "animation_game_hud",
        "transient_event",
        "scroll_navigation",
    ]
    f = [
        "popup_notification",
        "small_ui",
        "action_failure",
        "loading_completion",
        "action_success",
        "cursor_hover_focus",
    ]
    g = [
        "small_ui",
        "action_failure",
        "animation_game_hud",
        "action_success",
        "transient_event",
        "cursor_hover_focus",
    ]
    h = [
        "small_ui",
        "cursor_hover_focus",
        "animation_game_hud",
        "animation_game_hud",
        "transient_event",
        "transient_event",
    ]
    templates = [*([a] * 5), *([b] * 5), *([c] * 5), *([d] * 5)]
    templates.extend([e] * 5)
    templates.extend([f] * 3)
    templates.extend([g, h])
    totals = Counter(category for row in templates for category in row)
    if len(templates) != 30 or dict(totals) != CATEGORY_TARGETS:
        raise RuntimeError("v4 category templates do not match Claim 180")
    return [list(row) for row in templates]


def _playlab_candidate(
    case_id: str,
    slot_id: str,
    template: list[str],
    variant: int,
) -> dict[str, Any]:
    flow = Flow(
        case_id,
        slot_id,
        "https://playwrightlab.github.io/index.html",
        f"Exercise six frozen PlayLab states for balanced slot {slot_id}.",
    )
    animation_index = 0
    transient_index = 0
    for category in template:
        if category == "small_ui":
            target = ("#toggleBold", "bold formatting") if variant % 2 else ("#toggleItalic", "italic formatting")
            flow.prepare("show-format-controls", "hover", locator=css("#interactions"))
            flow.target(
                category,
                f"toggle-{target[1].split()[0]}",
                "click",
                locator=css(target[0]),
                expected_result=f"the {target[1]} control becomes active",
            )
        elif category == "action_success":
            flow.prepare("show-dynamic-add", "hover", locator=css("#addElementBtn"))
            flow.target(
                category,
                "add-dynamic-element",
                "click",
                locator=css("#addElementBtn"),
                expected_result="a new dynamic element appears",
            )
        elif category == "action_failure":
            flow.prepare("show-registration", "hover", locator=css("#fullName"))
            flow.target(
                category,
                "reject-empty-registration",
                "click",
                locator=css("#forms button[type=submit]"),
                expected_outcome="failure",
                expected_result="empty registration remains rejected with validation feedback",
            )
        elif category == "popup_notification":
            flow.prepare("show-modal-control", "hover", locator=css("#openModalBtn"))
            flow.target(
                category,
                "open-modal",
                "click",
                locator=css("#openModalBtn"),
                expected_result="the modal dialog is visible",
            )
            flow.prepare("close-modal", "click", locator=css("#modalClose"))
        elif category == "loading_completion":
            flow.prepare("show-delayed-loader", "hover", locator=css("#loadDelayedBtn"))
            flow.prepare(
                "select-one-second-delay",
                "select",
                locator=css("#delayTime"),
                value={"label": "1 second"},
            )
            flow.prepare("start-delayed-load", "click", locator=css("#loadDelayedBtn"))
            flow.target(
                category,
                "observe-delayed-content",
                "wait_for",
                locator=css("#delayedContent"),
                timeout_ms=3500,
                expected_result="delayed content is fully visible",
            )
        elif category == "scroll_navigation":
            flow.target(
                category,
                "scroll-document",
                "scroll",
                x=0,
                y=520 if variant % 2 else 640,
                expected_result="a later PlayLab region enters the viewport",
            )
        elif category == "cursor_hover_focus":
            flow.prepare("show-tooltip-region", "hover", locator=css("#interactions"))
            flow.target(
                category,
                "hover-tooltip",
                "hover",
                locator=css("#tooltipBtn"),
                expected_result="the hover tooltip appears",
            )
        elif category == "animation_game_hud":
            controls = [
                ("#startProgressBtn", "start-download-progress", "download progress starts moving"),
                ("#startTimerBtn", "start-live-timer", "the live timer begins updating"),
                ("#carouselNext", "advance-carousel", "the carousel animates to the next slide"),
                ("#toggleSpinnerBtn", "toggle-spinner", "the circular loading HUD appears"),
            ]
            selector, name, result = controls[(variant + animation_index) % len(controls)]
            animation_index += 1
            flow.prepare(f"show-{name}", "hover", locator=css(selector))
            flow.target(
                category,
                name,
                "click",
                locator=css(selector),
                expected_result=result,
            )
        elif category == "transient_event":
            controls = [
                ("#toastSuccess", "success-toast", "a temporary success toast appears"),
                ("#toastWarning", "warning-toast", "a temporary warning toast appears"),
                ("#toastInfo", "info-toast", "a temporary info toast appears"),
            ]
            selector, name, result = controls[(variant + transient_index) % len(controls)]
            transient_index += 1
            flow.prepare(f"show-{name}", "hover", locator=css(selector))
            flow.target(
                category,
                name,
                "click",
                locator=css(selector),
                expected_result=result,
            )
        else:
            raise RuntimeError(f"unsupported PlayLab category: {category}")
    return flow.finish()


def _qah_nav(flow: Flow, section: str) -> None:
    flow.prepare(
        f"open-{section}",
        "click",
        locator=css(f"a[href='#{section}'] >> nth=0"),
    )
    flow.prepare(f"wait-{section}", "wait_for", locator=css(f"#{section}"))


def _qah_candidate(
    case_id: str,
    slot_id: str,
    template: list[str],
    variant: int,
) -> dict[str, Any]:
    flow = Flow(
        case_id,
        slot_id,
        "https://qapracticehub.com/",
        f"Exercise six frozen QA Practice Hub states for balanced slot {slot_id}.",
    )
    flow.prepare("dismiss-cookie-banner", "click", locator=css("#cookie-decline"))
    animation_index = 0
    transient_index = 0
    for category in template:
        if category == "small_ui":
            _qah_nav(flow, "selection")
            selector = "#skill-playwright" if variant % 2 else "#skill-cypress"
            flow.target(
                category,
                "toggle-small-skill",
                "check",
                locator=css(selector),
                expected_result="one small skill checkbox becomes selected",
            )
        elif category == "action_success":
            _qah_nav(flow, "dynamic")
            flow.target(
                category,
                "add-list-item",
                "click",
                locator=css("#btn-add-element"),
                expected_result="a new list item appears",
            )
        elif category == "action_failure":
            _qah_nav(flow, "forms")
            flow.prepare(
                "fill-invalid-user",
                "fill",
                locator=css("#login-username"),
                value=f"invalid-{variant}",
            )
            flow.prepare(
                "fill-invalid-password",
                "fill",
                locator=css("#login-password"),
                value="wrong-password",
            )
            flow.target(
                category,
                "reject-login",
                "click",
                locator=css("#login-submit"),
                expected_outcome="failure",
                expected_result="login remains rejected with an error message",
            )
        elif category == "popup_notification":
            _qah_nav(flow, "buttons")
            flow.target(
                category,
                "open-click-info",
                "click",
                locator=css("#info-btn-click"),
                expected_result="the click information popup is visible",
            )
        elif category == "loading_completion":
            _qah_nav(flow, "dynamic")
            flow.prepare("start-data-load", "click", locator=css("#btn-load-data"))
            flow.target(
                category,
                "observe-loaded-data",
                "wait_for",
                locator=css("#loaded-data"),
                timeout_ms=4000,
                expected_result="the delayed data completion message is visible",
            )
        elif category == "scroll_navigation":
            _qah_nav(flow, "shopping")
            flow.target(
                category,
                "scroll-products",
                "scroll",
                x=0,
                y=480 if variant % 2 else 620,
                expected_result="later products enter the viewport",
            )
        elif category == "cursor_hover_focus":
            _qah_nav(flow, "buttons")
            flow.target(
                category,
                "hover-feedback-button",
                "hover",
                locator=css("#btn-hover"),
                expected_result="hover feedback becomes visible",
            )
        elif category == "animation_game_hud":
            _qah_nav(flow, "advanced")
            selector = "#btn-progress-inc" if animation_index % 2 == 0 else "#btn-progress-dec"
            name = "increase-progress" if animation_index % 2 == 0 else "decrease-progress"
            animation_index += 1
            flow.target(
                category,
                name,
                "click",
                locator=css(selector),
                expected_result="the progress HUD visibly changes by ten percent",
            )
        elif category == "transient_event":
            _qah_nav(flow, "buttons")
            controls = [
                ("#info-btn-hover", "hover-info", "a temporary hover info bubble appears", "hover"),
                ("#btn-click-counter", "click-counter-feedback", "brief click feedback and a new count appear", "click"),
            ]
            selector, name, result, kind = controls[transient_index % 2]
            transient_index += 1
            flow.target(
                category,
                name,
                kind,
                locator=css(selector),
                expected_result=result,
            )
        else:
            raise RuntimeError(f"unsupported QA Practice Hub category: {category}")
    return flow.finish()


def _testpages_candidate(
    case_id: str,
    slot_id: str,
    template: list[str],
    variant: int,
) -> dict[str, Any]:
    has_popup = "popup_notification" in template
    needs_server = any(
        category in template
        for category in ("action_failure", "loading_completion")
    )
    if has_popup:
        url = "https://testpages.eviltester.com/pages/basics/alerts-not-javascript/"
        mode = "alert"
    elif needs_server:
        url = "https://testpages.eviltester.com/apps/server-side-calculator/"
        mode = "server"
    else:
        url = "https://testpages.eviltester.com/apps/countdown-timer/"
        mode = "timer"
    flow = Flow(
        case_id,
        slot_id,
        url,
        f"Exercise six frozen TestPages states for balanced slot {slot_id}.",
    )
    timer_running = False
    animation_index = 0
    transient_index = 0

    def navigate(target: str) -> None:
        nonlocal mode
        if mode == target:
            return
        url, heading = {
            "server": (
                "https://testpages.eviltester.com/apps/server-side-calculator/",
                "Server Side Calculator",
            ),
            "timer": (
                "https://testpages.eviltester.com/apps/countdown-timer/",
                "Countdown Timer",
            ),
        }[target]
        flow.prepare(
            f"open-{target}-app",
            "navigate",
            url=url,
            timeout_ms=5000,
        )
        flow.prepare(
            f"wait-{target}-app",
            "wait_for",
            locator=role("heading", heading, exact=True),
            timeout_ms=4000,
        )
        mode = target

    def prepare_server_values(left: str, right: str = "3") -> None:
        navigate("server")
        flow.prepare("fill-first-number", "fill", locator=css("#number1"), value=left)
        flow.prepare("fill-second-number", "fill", locator=css("#number2"), value=right)

    for category in template:
        if category == "popup_notification":
            flow.target(
                category,
                "open-fake-alert",
                "click",
                locator=css("#fakealert"),
                expected_result="the non-JavaScript modal alert is visible",
            )
            flow.prepare("close-fake-alert", "click", locator=css("#dialog-ok"))
        elif category == "small_ui":
            if needs_server:
                navigate("server")
                flow.target(
                    category,
                    "enter-compact-number",
                    "fill",
                    locator=css("#number1"),
                    value=str((variant % 9) + 1),
                    expected_result="a compact numeric value is visible in the first field",
                )
            else:
                navigate("timer")
                flow.target(
                    category,
                    "set-compact-timer",
                    "fill",
                    locator=css("#timer-seconds"),
                    value=str(4 + variant % 3),
                    expected_result="the compact seconds field shows the configured value",
                )
        elif category == "action_failure":
            prepare_server_values(f"invalid-{variant % 10}")
            flow.target(
                category,
                "reject-invalid-calculation",
                "click",
                locator=css("#calculate"),
                expected_outcome="failure",
                expected_result="the server visibly returns an unknown-token error",
            )
        elif category == "loading_completion":
            prepare_server_values(str(variant + 2))
            flow.target(
                category,
                "calculate-on-server",
                "click",
                locator=css("#calculate"),
                timeout_ms=5000,
                expected_result="the server-rendered calculation answer is visible",
            )
        elif category == "action_success":
            if "animation_game_hud" in template:
                navigate("timer")
                flow.prepare(
                    "set-success-timer",
                    "fill",
                    locator=css("#timer-seconds"),
                    value=str(6 + variant % 3),
                )
                flow.target(
                    category,
                    "accept-timer-reset",
                    "click",
                    locator=css("#reset-timer"),
                    expected_result="the timer accepts the value and visibly resets its HUD",
                )
                timer_running = False
            else:
                prepare_server_values("2", "3")
                flow.target(
                    category,
                    "complete-valid-calculation",
                    "click",
                    locator=css("#calculate"),
                    expected_result="the server visibly shows the correct calculation result",
                )
        elif category == "scroll_navigation":
            flow.target(
                category,
                "scroll-test-page",
                "scroll",
                x=0,
                y=520 if variant % 2 else 650,
                expected_result="a later part of the TestPages document enters view",
            )
        elif category == "cursor_hover_focus":
            if mode == "timer":
                locator = css("#start-timer")
                name = "hover-timer-control"
                result = "the timer control receives visible pointer focus"
            else:
                navigate("server")
                locator = css("#calculate")
                name = "hover-calculation-control"
                result = "the calculation control receives visible pointer focus"
            flow.target(
                category,
                name,
                "hover",
                locator=locator,
                expected_result=result,
            )
        elif category == "animation_game_hud":
            navigate("timer")
            flow.prepare(
                "set-short-timer",
                "fill",
                locator=css("#timer-seconds"),
                value=str(4 + variant % 3),
            )
            if animation_index % 2 == 0:
                flow.target(
                    category,
                    "start-countdown",
                    "click",
                    locator=css("#start-timer"),
                    expected_result="the countdown HUD begins updating",
                )
                timer_running = True
            else:
                flow.target(
                    category,
                    "reset-countdown",
                    "click",
                    locator=css("#reset-timer"),
                    expected_result="the countdown HUD visibly resets",
                )
            animation_index += 1
        elif category == "transient_event":
            navigate("timer")
            if not timer_running:
                flow.prepare(
                    "set-transient-timer",
                    "fill",
                    locator=css("#timer-seconds"),
                    value="5",
                )
                flow.prepare("start-transient-timer", "click", locator=css("#start-timer"))
                timer_running = True
            if transient_index % 2 == 0:
                flow.target(
                    category,
                    "stop-countdown",
                    "click",
                    locator=css("#stop-timer"),
                    expected_result="the actively changing countdown briefly stops",
                )
                timer_running = False
            else:
                flow.target(
                    category,
                    "clear-countdown",
                    "click",
                    locator=css("#clear-timer"),
                    expected_result="the countdown display disappears",
                )
                timer_running = False
            transient_index += 1
        else:
            raise RuntimeError(f"unsupported TestPages category: {category}")
    return flow.finish()


FACTORIES: dict[str, Callable[[str, str, list[str], int], dict[str, Any]]] = {
    "playlab": _playlab_candidate,
    "qah": _qah_candidate,
    "testpages": _testpages_candidate,
}


def build_candidates() -> list[dict[str, Any]]:
    domains = ["playlab", "qah", "testpages"]
    rows = []
    for slot_index, template in enumerate(category_templates(), start=1):
        slot_id = f"v4-slot-{slot_index:02d}"
        primary = domains[(slot_index - 1) % len(domains)]
        alternate = domains[slot_index % len(domains)]
        for variant_name, domain, offset in (
            ("a", primary, 0),
            ("b", alternate, 30),
        ):
            case_id = f"v4-{slot_index:02d}{variant_name}-{domain}"
            rows.append(
                FACTORIES[domain](
                    case_id,
                    slot_id,
                    template,
                    slot_index + offset,
                )
            )
    return rows


def json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_outputs(
    sources_path: Path,
    actions_dir: Path,
    manifest_path: Path,
    collector_revision: str,
    *,
    check: bool,
) -> None:
    candidates = build_candidates()
    case_ids = [row["case_id"] for row in candidates]
    if len(candidates) != 60 or len(case_ids) != len(set(case_ids)):
        raise RuntimeError("v4 must contain exactly 60 unique candidates")
    slots = []
    target_events = []
    for index in range(0, len(candidates), 2):
        pair = candidates[index : index + 2]
        if pair[0]["slot_id"] != pair[1]["slot_id"]:
            raise RuntimeError("v4 candidates must be adjacent slot pairs")
        slots.append(
            {
                "slot_id": pair[0]["slot_id"],
                "candidate_ids": [row["case_id"] for row in pair],
                "category_template": [
                    row["category"] for row in pair[0]["target_events"]
                ],
            }
        )
        for row in pair:
            target_events.append(
                {
                    "case_id": row["case_id"],
                    "slot_id": row["slot_id"],
                    "events": row["target_events"],
                }
            )
    sources = {
        "schema_version": 1,
        "kind": "signum_claim180_v4_candidate_sources",
        "case_ids": case_ids,
        "slots": slots,
        "target_events": target_events,
        "workflow_sources": [
            {
                "case_id": row["case_id"],
                "slot_id": row["slot_id"],
                "url": row["url"],
                "goal": row["goal"],
            }
            for row in candidates
        ],
    }
    actions_dir.mkdir(parents=True, exist_ok=True)
    sources_path.parent.mkdir(parents=True, exist_ok=True)
    expected_files: dict[Path, str] = {sources_path: json_text(sources)}
    for row in candidates:
        payload = {
            "schema_version": 1,
            "case_id": row["case_id"],
            "slot_id": row["slot_id"],
            "source_url": row["url"],
            "goal": row["goal"],
            "duration_seconds": row["duration_seconds"],
            "capture_policy": CAPTURE_POLICY,
            "target_events": row["target_events"],
            "actions": row["actions"],
        }
        expected_files[actions_dir / f"{row['case_id']}.json"] = json_text(payload)
    expected_names = {f"{case_id}.json" for case_id in case_ids}
    unexpected = sorted(
        path.name for path in actions_dir.glob("*.json") if path.name not in expected_names
    )
    if unexpected:
        raise RuntimeError(f"unexpected v4 action files: {unexpected}")
    stale = []
    for path, expected in expected_files.items():
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                stale.append(path.name)
        else:
            path.write_text(expected, encoding="utf-8")
    if stale:
        raise RuntimeError(f"v4 files are stale or missing: {stale}")
    manifest = {
        "schema_version": 1,
        "kind": "signum_claim180_browser_actions",
        "collector_revision": collector_revision,
        "candidate_count": len(candidates),
        "slot_count": len(slots),
        "source_catalog": {
            "path": sources_path.resolve().relative_to(manifest_path.parent.resolve()).as_posix(),
            "bytes": sources_path.stat().st_size,
            "sha256": sha256_file(sources_path),
        },
        "capture_policy": CAPTURE_POLICY,
        "cases": [
            {
                "case_id": case_id,
                "action_file": (actions_dir / f"{case_id}.json").resolve().relative_to(manifest_path.parent.resolve()).as_posix(),
                "bytes": (actions_dir / f"{case_id}.json").stat().st_size,
                "sha256": sha256_file(actions_dir / f"{case_id}.json"),
            }
            for case_id in case_ids
        ],
    }
    content = json_text(manifest)
    if check:
        if not manifest_path.is_file() or manifest_path.read_text(encoding="utf-8") != content:
            raise RuntimeError("v4 actions manifest is stale or missing")
    else:
        manifest_path.write_text(content, encoding="utf-8")
    print(
        json.dumps(
            {
                "candidates": len(candidates),
                "slots": len(slots),
                "check": check,
                "manifest": str(manifest_path.resolve()),
            },
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the balanced Claim 180 v4 candidate slots."
    )
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--actions", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--collector-revision", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if len(args.collector_revision) not in {40, 64} or any(
        character not in "0123456789abcdefABCDEF"
        for character in args.collector_revision
    ):
        raise RuntimeError("collector revision must be a full immutable hash")
    build_outputs(
        args.sources,
        args.actions,
        args.manifest,
        args.collector_revision,
        check=args.check,
    )


if __name__ == "__main__":
    main()
