from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


CAPTURE_POLICY = {
    "requested_fps": 15,
    "width": 1280,
    "height": 720,
    "minimum_average_fps": 10,
    "maximum_gap_seconds": 0.25,
}


def css(value: str) -> dict[str, Any]:
    return {"by": "css", "value": value}


def text(value: str, *, exact: bool = False) -> dict[str, Any]:
    return {"by": "text", "value": value, "exact": exact}


def role(role_name: str, name: str, *, exact: bool = True) -> dict[str, Any]:
    return {"by": "role", "role": role_name, "name": name, "exact": exact}


def action(
    action_id: str,
    at_seconds: float,
    action_type: str,
    *,
    expected_result: str,
    expected_outcome: str = "success",
    **fields: Any,
) -> dict[str, Any]:
    return {
        "id": action_id,
        "at_seconds": at_seconds,
        "type": action_type,
        "required": True,
        "expected_outcome": expected_outcome,
        "expected_result": expected_result,
        **fields,
    }


def loading_case(
    number: int,
    slug: str,
    url: str,
    goal: str,
    completion_locator: dict[str, Any],
    expected_result: str,
    *,
    trigger_locator: dict[str, Any] | None = None,
    duration_seconds: int = 12,
    timeout_ms: int = 10_000,
) -> dict[str, Any]:
    actions = []
    if trigger_locator is not None:
        actions.append(
            action(
                "trigger",
                1.0,
                "click",
                locator=trigger_locator,
                expected_result="the asynchronous operation starts",
            )
        )
    actions.append(
        action(
            "completion",
            1.1 if trigger_locator is not None else 0.5,
            "wait_for",
            locator=completion_locator,
            state="visible",
            timeout_ms=timeout_ms,
            expected_result=expected_result,
        )
    )
    return {
        "case_id": f"s1-{number:02d}-{slug}",
        "category": "loading_completion",
        "target_action_id": "completion",
        "url": url,
        "goal": goal,
        "duration_seconds": duration_seconds,
        "actions": actions,
    }


def failure_case(
    number: int,
    slug: str,
    url: str,
    goal: str,
    target_locator: dict[str, Any],
    expected_result: str,
    *,
    setup: list[dict[str, Any]] | None = None,
    target_type: str = "click",
    duration_seconds: int = 9,
    timeout_ms: int = 6_000,
) -> dict[str, Any]:
    setup_actions = list(setup or [])
    target_at = max(
        [2.0, *(float(row["at_seconds"]) + 0.75 for row in setup_actions)]
    )
    actions = [
        *setup_actions,
        action(
            "failure",
            target_at,
            target_type,
            locator=target_locator,
            state="visible" if target_type == "wait_for" else None,
            timeout_ms=timeout_ms,
            expected_outcome="failure",
            expected_result=expected_result,
        ),
    ]
    if target_type != "wait_for":
        actions[-1].pop("state")
    return {
        "case_id": f"s1-{number:02d}-{slug}",
        "category": "action_failure",
        "target_action_id": "failure",
        "url": url,
        "goal": goal,
        "duration_seconds": duration_seconds,
        "actions": actions,
    }


def fill(action_id: str, at_seconds: float, selector: str, value: str) -> dict[str, Any]:
    return action(
        action_id,
        at_seconds,
        "fill",
        locator=css(selector),
        value=value,
        expected_result=f"the setup field {action_id} is populated",
    )


def select(action_id: str, at_seconds: float, selector: str, value: str) -> dict[str, Any]:
    return action(
        action_id,
        at_seconds,
        "select",
        locator=css(selector),
        value=value,
        expected_result=f"the setup selection {action_id} is applied",
    )


def build_loading_candidates() -> list[dict[str, Any]]:
    qa = "https://qaplayground.vercel.app/"
    expand = "https://practice.expandtesting.com"
    selenium = "https://www.selenium.dev/selenium/web/dynamic.html"
    practice_delay = "https://practice-automation.com/javascript-delays/"
    demoqa_progress = "https://demoqa.com/progress-bar"
    demoqa_dynamic = "https://demoqa.com/dynamic-properties"
    cases = [
        loading_case(1, "qa-delayed-element", qa, "Trigger a delayed element and wait for it to appear.", css("#delayed-elem"), "the delayed element becomes visible", trigger_locator=css("#btn-trigger-appear")),
        loading_case(2, "qa-loaded-content", qa, "Request asynchronous content and wait for the response text.", text("Loaded content #1"), "the asynchronously loaded content appears", trigger_locator=css("#btn-load-content")),
        loading_case(3, "qa-spinner", qa, "Start the loading spinner and wait for its completion result.", css("#spinner-result"), "the spinner is replaced by its loaded result", trigger_locator=css("#btn-spinner")),
        loading_case(4, "qa-three-second-wait", qa, "Trigger the three-second wait and observe the delayed element.", css("#wait-elem"), "the three-second delayed element becomes visible", trigger_locator=css("#btn-wait3")),
        loading_case(5, "qa-progress", qa, "Start the progress simulation and wait for completion.", text("100% — Complete"), "the progress display reaches 100% complete", trigger_locator=css("#btn-progress")),
        loading_case(6, "qa-delayed-text", qa, "Start a delayed text update and wait for the replacement.", text("Text changed after 2 seconds"), "the delayed replacement text appears", trigger_locator=css("#btn-text-delay")),
        loading_case(7, "qa-dynamic-dropdown", qa, "Load dropdown choices asynchronously and wait for the result.", text("Dynamic dropdown loaded with 5 options"), "the dynamic dropdown reports five loaded options", trigger_locator=css("#btn-load-dropdown")),
        loading_case(8, "qa-delayed-enable", qa, "Request delayed button enablement and wait for its visible confirmation.", text("Button is now enabled"), "the delayed button enablement confirmation appears", trigger_locator=css("#btn-enable-trigger")),
        loading_case(9, "qa-api-fast", qa, "Call the fast simulated API and wait for its response.", text("Response received after 500ms"), "the fast API success response appears", trigger_locator=css("#btn-api-fast")),
        loading_case(10, "qa-api-medium", qa, "Call the medium simulated API and wait for its response.", text("Response received after 2000ms"), "the medium API success response appears", trigger_locator=css("#btn-api-medium")),
        loading_case(11, "qa-api-slow", qa, "Call the slow simulated API and wait for its response.", text("Response received after 5000ms"), "the slow API success response appears", trigger_locator=css("#btn-api-slow"), duration_seconds=14, timeout_ms=11_000),
        loading_case(12, "expand-hidden", f"{expand}/dynamic-loading/1", "Start the hidden-element loader and wait for Hello World.", css("#finish"), "the previously hidden Hello World result becomes visible", trigger_locator=role("button", "Start")),
        loading_case(13, "expand-rendered", f"{expand}/dynamic-loading/2", "Start the dynamic renderer and wait for Hello World.", css("#finish"), "the newly rendered Hello World result appears", trigger_locator=role("button", "Start")),
        loading_case(14, "expand-remove", f"{expand}/dynamic-controls", "Remove the checkbox asynchronously and wait for confirmation.", text("It's gone!", exact=True), "the removal confirmation appears after the checkbox disappears", trigger_locator=role("button", "Remove")),
        loading_case(15, "expand-enable", f"{expand}/dynamic-controls", "Enable the input asynchronously and wait for confirmation.", text("It's enabled!", exact=True), "the input-enabled confirmation appears", trigger_locator=role("button", "Enable")),
        loading_case(16, "selenium-add", selenium, "Request a delayed red box and wait for it to be added.", css("#box0"), "the delayed red box is added to the page", trigger_locator=css("#adder"), duration_seconds=8, timeout_ms=5_000),
        loading_case(17, "selenium-reveal", selenium, "Request a delayed input and wait for it to become visible.", css("#revealed"), "the delayed input becomes visible", trigger_locator=css("#reveal"), duration_seconds=8, timeout_ms=5_000),
        loading_case(18, "practice-liftoff", practice_delay, "Start the countdown and wait for Liftoff.", text("Liftoff!", exact=True), "the countdown finishes with Liftoff", trigger_locator=css("#start"), duration_seconds=16, timeout_ms=13_000),
        loading_case(19, "demoqa-progress", demoqa_progress, "Start the progress bar and wait for its Reset state.", role("button", "Reset"), "the progress bar reaches 100% and exposes Reset", trigger_locator=css("#startStopButton"), duration_seconds=16, timeout_ms=14_000),
        loading_case(20, "demoqa-visible", demoqa_dynamic, "Wait for the page's automatically delayed Visible After control.", css("#visibleAfter"), "the Visible After control appears", duration_seconds=10, timeout_ms=8_000),
    ]
    repeats = [
        (21, "qa-delayed-element-repeat", cases[0]),
        (22, "qa-spinner-repeat", cases[2]),
        (23, "qa-progress-repeat", cases[4]),
        (24, "selenium-add-repeat", cases[15]),
        (25, "demoqa-progress-repeat", cases[18]),
        (26, "expand-hidden-repeat", cases[11]),
    ]
    for number, slug, original in repeats:
        cases.append(
            {
                **original,
                "case_id": f"s1-{number:02d}-{slug}",
                "goal": f"Independent repeat capture: {original['goal']}",
            }
        )
    return cases


def build_failure_candidates() -> list[dict[str, Any]]:
    sauce = "https://www.saucedemo.com/"
    qa = "https://qaplayground.vercel.app/"
    expand = "https://practice.expandtesting.com"
    sauce_submit = css("#login-button")
    qa_submit = css("#btn-login")

    def sauce_case(number: int, slug: str, username: str | None, password: str | None, result: str) -> dict[str, Any]:
        setup = []
        if username is not None:
            setup.append(fill("username", 0.7, "#user-name", username))
        if password is not None:
            setup.append(fill("password", 1.2, "#password", password))
        return failure_case(number, slug, sauce, "Submit rejected Sauce Demo credentials and retain the visible error.", sauce_submit, result, setup=setup)

    def qa_auth_case(number: int, slug: str, username: str | None, password: str | None) -> dict[str, Any]:
        setup = []
        if username is not None:
            setup.append(fill("username", 0.7, "#auth-username", username))
        if password is not None:
            setup.append(fill("password", 1.2, "#auth-password", password))
        return failure_case(number, slug, qa, "Submit rejected QA Playground credentials and retain the visible error.", qa_submit, "the invalid-credentials error is visible and no dashboard is entered", setup=setup)

    cases = [
        sauce_case(27, "sauce-missing-username", None, "secret_sauce", "the Username is required error appears"),
        sauce_case(28, "sauce-missing-password", "standard_user", None, "the Password is required error appears"),
        sauce_case(29, "sauce-bad-username", "wrong_user", "secret_sauce", "the username/password mismatch error appears"),
        sauce_case(30, "sauce-bad-password", "standard_user", "wrong_password", "the username/password mismatch error appears"),
        sauce_case(31, "sauce-locked-user", "locked_out_user", "secret_sauce", "the locked-out user error appears"),
        sauce_case(32, "sauce-empty", None, None, "the Username is required error appears"),
        qa_auth_case(33, "qa-empty", None, None),
        qa_auth_case(34, "qa-missing-password", "admin", None),
        qa_auth_case(35, "qa-missing-username", None, "admin123"),
        qa_auth_case(36, "qa-bad-both", "wrong", "wrong"),
        qa_auth_case(37, "qa-bad-username", "wrong", "admin123"),
        qa_auth_case(38, "qa-bad-password", "admin", "wrong"),
        failure_case(39, "qa-api-error", qa, "Call the simulated failing API and wait for its visible 500 result.", text("Error 500: Internal Server Error"), "the simulated API exposes its visible 500 error", setup=[action("trigger-error", 0.8, "click", locator=css("#btn-api-error"), expected_result="the simulated failing API call starts")], target_type="wait_for", timeout_ms=8_000, duration_seconds=11),
        failure_case(40, "expand-form-empty", f"{expand}/form-validation", "Submit an empty validation form and retain all required-field errors.", role("button", "Register"), "required-field errors are visible and registration is rejected"),
        failure_case(41, "expand-form-phone", f"{expand}/form-validation", "Submit an otherwise incomplete form with an invalid phone value.", role("button", "Register"), "the invalid contact-number state remains visible", setup=[fill("name", 0.6, "input[name=ContactName]", "Signum"), fill("phone", 1.1, "input[name=contactnumber]", "bad")]),
        failure_case(42, "expand-form-date", f"{expand}/form-validation", "Submit valid contact fields without a pickup date.", role("button", "Register"), "the missing pickup-date error remains visible", setup=[fill("name", 0.5, "input[name=ContactName]", "Signum"), fill("phone", 1.0, "input[name=contactnumber]", "012-3456789"), select("payment", 1.5, "select[name=payment]", "card")]),
        failure_case(43, "expand-form-payment", f"{expand}/form-validation", "Submit valid contact fields and date without a payment method.", role("button", "Register"), "the missing payment-method error remains visible", setup=[fill("name", 0.5, "input[name=ContactName]", "Signum"), fill("phone", 1.0, "input[name=contactnumber]", "012-3456789"), fill("date", 1.5, "input[name=pickupdate]", "2026-09-01")]),
        failure_case(44, "demoqa-required", "https://demoqa.com/automation-practice-form", "Submit the empty required form and retain its invalid-field styling.", css("#submit"), "the required fields are marked invalid and no submission dialog opens", duration_seconds=10),
        failure_case(45, "practice-login-password", "https://practicetestautomation.com/practice-test-login/", "Submit the documented username with an invalid password.", css("#submit"), "the Your password is invalid error is visible", setup=[fill("username", 0.7, "#username", "student"), fill("password", 1.2, "#password", "incorrectPassword")], duration_seconds=11),
        sauce_case(46, "sauce-whitespace-username", " ", "secret_sauce", "the username/password mismatch error appears"),
        qa_auth_case(47, "qa-uppercase-username", "ADMIN", "admin123"),
        sauce_case(48, "sauce-uppercase-username", "STANDARD_USER", "secret_sauce", "the username/password mismatch error appears"),
        qa_auth_case(49, "qa-whitespace-username", " admin ", "admin123"),
        sauce_case(50, "sauce-bad-username-repeat", "another_wrong_user", "secret_sauce", "the username/password mismatch error appears"),
        qa_auth_case(51, "qa-bad-credentials-repeat", "invalid", "invalid"),
        failure_case(52, "qa-api-error-repeat", qa, "Repeat the simulated failing API in an independent capture.", text("Error 500: Internal Server Error"), "the simulated API exposes its visible 500 error", setup=[action("trigger-error", 0.8, "click", locator=css("#btn-api-error"), expected_result="the simulated failing API call starts")], target_type="wait_for", timeout_ms=8_000, duration_seconds=11),
    ]
    return cases


def json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_outputs(
    sources_path: Path,
    targets_path: Path,
    actions_dir: Path,
    manifest_path: Path,
    collector_revision: str,
    *,
    check: bool,
) -> None:
    candidates = [*build_loading_candidates(), *build_failure_candidates()]
    case_ids = [row["case_id"] for row in candidates]
    if len(candidates) != 52 or len(case_ids) != len(set(case_ids)):
        raise RuntimeError("supplement pool must contain exactly 52 unique candidates")
    category_counts = {
        category: sum(row["category"] == category for row in candidates)
        for category in ("loading_completion", "action_failure")
    }
    if category_counts != {"loading_completion": 26, "action_failure": 26}:
        raise RuntimeError(f"unexpected supplement candidate counts: {category_counts}")
    sources = {
        "schema_version": 1,
        "kind": "signum_claim180_supplement_candidate_sources",
        "case_ids": case_ids,
        "workflow_sources": [
            {"case_id": row["case_id"], "url": row["url"], "goal": row["goal"]}
            for row in candidates
        ],
    }
    targets = {
        "schema_version": 1,
        "kind": "signum_claim180_supplement_target_events",
        "category_candidate_counts": category_counts,
        "target_events": [
            {
                "case_id": row["case_id"],
                "action_id": row["target_action_id"],
                "category": row["category"],
                "expected_result": next(
                    action_row["expected_result"]
                    for action_row in row["actions"]
                    if action_row["id"] == row["target_action_id"]
                ),
            }
            for row in candidates
        ],
    }
    actions_dir.mkdir(parents=True, exist_ok=True)
    expected_files = {
        sources_path: json_text(sources),
        targets_path: json_text(targets),
    }
    for row in candidates:
        payload = {
            "schema_version": 1,
            "case_id": row["case_id"],
            "source_url": row["url"],
            "goal": row["goal"],
            "duration_seconds": row["duration_seconds"],
            "capture_policy": CAPTURE_POLICY,
            "actions": row["actions"],
        }
        expected_files[actions_dir / f"{row['case_id']}.json"] = json_text(payload)
    expected_names = {f"{case_id}.json" for case_id in case_ids}
    unexpected = sorted(
        path.name for path in actions_dir.glob("*.json") if path.name not in expected_names
    )
    if unexpected:
        raise RuntimeError(f"unexpected supplement action files: {unexpected}")
    stale = []
    for path, expected in expected_files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                stale.append(path.name)
        else:
            path.write_text(expected, encoding="utf-8")
    if stale:
        raise RuntimeError(f"supplement files are stale or missing: {stale}")
    manifest = {
        "schema_version": 1,
        "kind": "signum_claim180_browser_actions",
        "collector_revision": collector_revision,
        "candidate_count": len(candidates),
        "source_catalog": {
            "path": sources_path.resolve().relative_to(manifest_path.parent.resolve()).as_posix(),
            "bytes": sources_path.stat().st_size,
            "sha256": sha256_file(sources_path),
        },
        "target_catalog": {
            "path": targets_path.resolve().relative_to(manifest_path.parent.resolve()).as_posix(),
            "bytes": targets_path.stat().st_size,
            "sha256": sha256_file(targets_path),
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
            raise RuntimeError("supplement actions manifest is stale or missing")
    else:
        manifest_path.write_text(content, encoding="utf-8")
    print(json.dumps({"candidates": len(candidates), "category_counts": category_counts, "check": check}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the ordered Claim 180 supplement candidate pool.")
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--actions", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--collector-revision", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if len(args.collector_revision) not in {40, 64} or any(
        character not in "0123456789abcdefABCDEF" for character in args.collector_revision
    ):
        raise RuntimeError("collector revision must be a full immutable hash")
    build_outputs(
        args.sources,
        args.targets,
        args.actions,
        args.manifest,
        args.collector_revision,
        check=args.check,
    )


if __name__ == "__main__":
    main()
