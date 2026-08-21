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
DURATION_SECONDS = 12


def locator(by: str, value: str | None = None, **fields: Any) -> dict[str, Any]:
    result = {"by": by, **fields}
    if value is not None:
        result["value"] = value
    return result


def action(
    identifier: str,
    at: float,
    kind: str,
    *,
    expected_result: str,
    expected_outcome: str = "success",
    required: bool = True,
    **fields: Any,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "at_seconds": at,
        "type": kind,
        "expected_outcome": expected_outcome,
        "expected_result": expected_result,
        "required": required,
        **fields,
    }


def role(role_name: str, name: str, *, exact: bool = True, frame: str | None = None) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "role": role_name,
        "name": name,
        "exact": exact,
    }
    if frame:
        fields["frame"] = frame
    return locator("role", **fields)


def css(value: str, *, frame: str | None = None) -> dict[str, Any]:
    return locator("css", value, **({"frame": frame} if frame else {}))


IFRAME = "iframe#iframeResult"


def planned_actions() -> dict[str, list[dict[str, Any]]]:
    return {
        "workflow-01-dynamic-controls-remove": [
            action("remove-checkbox", 1, "click", locator=role("button", "Remove"), expected_result="the checkbox is removed after loading"),
            action("wait-checkbox-removed", 1.1, "wait_for", locator=css("#checkbox", frame=None), state="hidden", timeout_ms=4000, expected_result="the checkbox is absent"),
            action("click-absent-checkbox", 4.5, "click", locator=css("#checkbox"), timeout_ms=600, expected_outcome="failure", expected_result="the absent checkbox cannot be clicked", required=False),
            action("add-checkbox", 6, "click", locator=role("button", "Add"), expected_result="the checkbox is restored after loading"),
            action("wait-checkbox-restored", 6.1, "wait_for", locator=css("#checkbox"), state="visible", timeout_ms=4000, expected_result="the checkbox is visible again"),
        ],
        "workflow-02-dynamic-controls-enable": [
            action("fill-disabled-input", 1, "fill", locator=css("#input-example input"), value="rejected", timeout_ms=600, expected_outcome="failure", expected_result="the disabled input remains unchanged", required=False),
            action("enable-input", 2.5, "click", locator=role("button", "Enable"), expected_result="the input becomes enabled after loading"),
            action("wait-input-enabled", 2.6, "wait_for", locator=css("#input-example input:enabled"), state="visible", timeout_ms=4000, expected_result="the enabled input is visible"),
            action("fill-enabled-input", 6, "fill", locator=css("#input-example input"), value="enabled value", expected_result="the input contains enabled value"),
            action("disable-input", 8, "click", locator=role("button", "Disable"), expected_result="the input becomes disabled again"),
        ],
        "workflow-03-dynamic-loading-hidden": [
            action("start-loading", 1, "click", locator=role("button", "Start"), expected_result="a loading indicator appears"),
            action("wait-loading", 1.1, "wait_for", locator=css("#loading"), state="visible", timeout_ms=1500, expected_result="the loading indicator is visible"),
            action("click-hidden-start", 2, "click", locator=role("button", "Start"), timeout_ms=600, expected_outcome="failure", expected_result="the hidden Start control cannot be clicked", required=False),
            action("wait-finished", 3, "wait_for", locator=css("#finish h4"), state="visible", timeout_ms=6000, expected_result="Hello World is visible"),
        ],
        "workflow-04-dynamic-loading-rendered": [
            action("start-loading", 1, "click", locator=role("button", "Start"), expected_result="a loading indicator appears"),
            action("wait-loading", 1.1, "wait_for", locator=css("#loading"), state="visible", timeout_ms=1500, expected_result="the loading indicator is visible"),
            action("click-hidden-start", 2, "click", locator=role("button", "Start"), timeout_ms=600, expected_outcome="failure", expected_result="the hidden Start control cannot be clicked", required=False),
            action("wait-rendered-finish", 3, "wait_for", locator=css("#finish h4"), state="visible", timeout_ms=6000, expected_result="the newly rendered Hello World text is visible"),
        ],
        "workflow-05-add-remove-elements": [
            action("add-first", 1, "click", locator=role("button", "Add Element"), expected_result="one Delete button appears"),
            action("add-second", 2.5, "click", locator=role("button", "Add Element"), expected_result="a second Delete button appears"),
            action("delete-first", 4, "click", locator=role("button", "Delete"), expected_result="one Delete button is removed"),
            action("delete-last", 5.5, "click", locator=role("button", "Delete"), expected_result="the last Delete button is removed"),
            action("delete-absent", 7, "click", locator=role("button", "Delete"), timeout_ms=600, expected_outcome="failure", expected_result="no Delete button can be clicked", required=False),
            action("add-after-failure", 9, "click", locator=role("button", "Add Element"), expected_result="a Delete button appears again"),
        ],
        "workflow-06-notification-message": [
            action("request-message-one", 1, "click", locator=locator("text", "Click here", exact=True), expected_result="a notification message appears"),
            action("wait-flash-one", 1.2, "wait_for", locator=css("#flash"), state="visible", timeout_ms=2500, expected_result="the first notification is visible"),
            action("request-message-two", 4, "click", locator=locator("text", "Click here", exact=True), expected_result="a new notification replaces the prior message"),
            action("request-message-three", 7, "click", locator=locator("text", "Click here", exact=True), expected_result="another notification result is visible"),
        ],
        "workflow-07-auth-success": [
            action("fill-username", 1, "fill", locator=css("#username"), value="tomsmith", expected_result="the username field contains tomsmith"),
            action("fill-password", 2, "fill", locator=css("#password"), value="SuperSecretPassword!", expected_result="the password field is filled"),
            action("submit-login", 3, "click", locator=role("button", "Login"), expected_result="the secure area opens"),
            action("wait-logout", 3.2, "wait_for", locator=locator("text", "Logout", exact=False), state="visible", timeout_ms=5000, expected_result="the Logout action is visible"),
            action("click-missing-login", 8, "click", locator=role("button", "Login"), timeout_ms=600, expected_outcome="failure", expected_result="the login button is absent in the secure area", required=False),
        ],
        "workflow-08-auth-rejected": [
            action("fill-invalid-username", 1, "fill", locator=css("#username"), value="invalid-user", expected_result="the invalid username is visible"),
            action("fill-invalid-password", 2, "fill", locator=css("#password"), value="invalid-password", expected_result="the password field is filled"),
            action("submit-invalid-login", 3, "click", locator=role("button", "Login"), expected_outcome="failure", expected_result="access is rejected and an error notification appears"),
            action("wait-login-error", 3.2, "wait_for", locator=css("#flash.error"), state="visible", timeout_ms=4000, expected_result="the login error is visible"),
            action("dismiss-error", 7, "click", locator=css("#flash a.close"), expected_result="the error notification is dismissed"),
        ],
        "workflow-09-hover-card": [
            action("click-hidden-profile", 1, "click", locator=css(".figure:nth-of-type(1) a"), timeout_ms=600, expected_outcome="failure", expected_result="the hidden profile link is not activated", required=False),
            action("hover-first-profile", 2.5, "hover", locator=css(".figure:nth-of-type(1)"), expected_result="the first profile caption appears"),
            action("wait-first-caption", 2.7, "wait_for", locator=css(".figure:nth-of-type(1) .figcaption"), state="visible", timeout_ms=1500, expected_result="the first profile link is visible"),
            action("hover-second-profile", 5, "hover", locator=css(".figure:nth-of-type(2)"), expected_result="the second profile caption appears"),
            action("hover-third-profile", 7.5, "hover", locator=css(".figure:nth-of-type(3)"), expected_result="the third profile caption appears"),
        ],
        "workflow-10-checkbox-toggle": [
            action("check-first", 1, "check", locator=css("#checkboxes input:nth-of-type(1)"), expected_result="the first checkbox is checked"),
            action("uncheck-second", 3, "uncheck", locator=css("#checkboxes input:nth-of-type(2)"), expected_result="the second checkbox is unchecked"),
            action("uncheck-first", 5, "uncheck", locator=css("#checkboxes input:nth-of-type(1)"), expected_result="the first checkbox is unchecked"),
            action("check-second", 7, "check", locator=css("#checkboxes input:nth-of-type(2)"), expected_result="the second checkbox is checked"),
            action("check-second-again", 9, "check", locator=css("#checkboxes input:nth-of-type(2)"), expected_outcome="failure", expected_result="the already checked box remains visually unchanged"),
        ],
        "workflow-11-dropdown-select": [
            action("select-option-one", 1, "select", locator=css("#dropdown"), value="1", expected_result="Option 1 is selected"),
            action("select-option-two", 3, "select", locator=css("#dropdown"), value="2", expected_result="Option 2 is selected"),
            action("select-missing-option", 5, "select", locator=css("#dropdown"), value="missing", timeout_ms=600, expected_outcome="failure", expected_result="the selection remains Option 2", required=False),
            action("select-option-one-again", 7, "select", locator=css("#dropdown"), value="1", expected_result="Option 1 is selected again"),
        ],
        "workflow-12-key-press": [
            action("press-a", 1, "press", locator=css("body"), key="A", expected_result="the page reports A"),
            action("press-escape", 3, "press", locator=css("body"), key="Escape", expected_result="the page reports ESCAPE"),
            action("press-arrow-down", 5, "press", locator=css("body"), key="ArrowDown", expected_result="the page reports DOWN"),
            action("press-shift", 7, "press", locator=css("body"), key="Shift", expected_result="the page reports SHIFT"),
        ],
        "workflow-13-horizontal-slider": [
            action("slider-right-one", 1, "press", locator=css("input[type=range]"), key="ArrowRight", expected_result="the displayed slider value increases"),
            action("slider-right-two", 2, "press", locator=css("input[type=range]"), key="ArrowRight", expected_result="the displayed slider value increases again"),
            action("slider-left", 4, "press", locator=css("input[type=range]"), key="ArrowLeft", expected_result="the displayed slider value decreases"),
            action("slider-letter", 6, "press", locator=css("input[type=range]"), key="A", expected_outcome="failure", expected_result="a letter key leaves the slider value unchanged"),
            action("slider-end", 8, "press", locator=css("input[type=range]"), key="End", expected_result="the slider reaches its maximum value"),
        ],
        "workflow-14-infinite-scroll": [
            action("scroll-one", 1, "scroll", y=600, expected_result="the viewport moves down"),
            action("scroll-two", 3, "scroll", y=900, expected_result="additional content enters the viewport"),
            action("scroll-three", 5, "scroll", y=1200, expected_result="new infinite-scroll content is appended"),
            action("scroll-up", 8, "scroll", y=-700, expected_result="the viewport moves upward"),
        ],
        "workflow-15-disappearing-elements": [
            action("wait-navigation", 1, "wait_for", locator=css("ul li"), state="visible", timeout_ms=2000, expected_result="navigation controls are visible"),
            action("reload-one", 2, "reload", timeout_ms=5000, expected_result="the navigation controls are redrawn"),
            action("wait-gallery-optional", 3, "wait_for", locator=locator("text", "Gallery", exact=True), state="visible", timeout_ms=1000, expected_outcome="failure", expected_result="Gallery may remain absent after reload", required=False),
            action("reload-two", 5, "reload", timeout_ms=5000, expected_result="the page is reloaded again"),
            action("reload-three", 8, "reload", timeout_ms=5000, expected_result="the final navigation state is visible"),
        ],
        "workflow-16-selenium-form-valid": [
            action("fill-text", 1, "fill", locator=css("input[name=my-text]"), value="Signum valid form", expected_result="the text field contains Signum valid form"),
            action("fill-password", 2, "fill", locator=css("input[name=my-password]"), value="public-test-value", expected_result="the password field is filled"),
            action("fill-textarea", 3, "fill", locator=css("textarea[name=my-textarea]"), value="timestamped capture", expected_result="the textarea contains timestamped capture"),
            action("select-two", 4, "select", locator=css("select[name=my-select]"), value="2", expected_result="the second option is selected"),
            action("submit-form", 7, "click", locator=role("button", "Submit"), expected_result="the form submission success page opens"),
            action("wait-received", 7.2, "wait_for", locator=locator("text", "Received!", exact=False), state="visible", timeout_ms=4000, expected_result="the Received confirmation is visible"),
        ],
        "workflow-17-selenium-form-invalid": [
            action("fill-disabled", 1, "fill", locator=css("input[name=my-disabled]"), value="rejected", timeout_ms=600, expected_outcome="failure", expected_result="the disabled field remains unchanged", required=False),
            action("fill-readonly", 3, "fill", locator=css("input[name=my-readonly]"), value="rejected", timeout_ms=600, expected_outcome="failure", expected_result="the readonly field remains unchanged", required=False),
            action("focus-readonly", 5, "click", locator=css("input[name=my-readonly]"), expected_result="the readonly field receives focus without changing value"),
            action("press-readonly", 6, "press", locator=css("input[name=my-readonly]"), key="A", expected_outcome="failure", expected_result="the readonly value remains unchanged"),
            action("submit-unchanged", 8, "click", locator=role("button", "Submit"), expected_result="the submitted form opens without rejected edits"),
        ],
        "workflow-18-selenium-small-controls": [
            action("check-default-checkbox", 1, "check", locator=css("input[type=checkbox]:not(:checked)"), expected_result="the compact default checkbox becomes checked"),
            action("uncheck-checked-checkbox", 3, "uncheck", locator=css("input[type=checkbox]:checked"), expected_result="the compact checked checkbox becomes unchecked"),
            action("check-default-radio", 5, "check", locator=css("input[type=radio]:not(:checked)"), expected_result="the default radio becomes selected"),
            action("check-radio-again", 7, "check", locator=css("input[type=radio]:checked"), expected_outcome="failure", expected_result="the already selected radio remains unchanged"),
        ],
        "workflow-19-selenium-range": [
            action("range-right", 1, "press", locator=css("input[name=my-range]"), key="ArrowRight", expected_result="the range thumb moves right"),
            action("range-right-again", 2.5, "press", locator=css("input[name=my-range]"), key="ArrowRight", expected_result="the range thumb moves right again"),
            action("range-left", 4, "press", locator=css("input[name=my-range]"), key="ArrowLeft", expected_result="the range thumb moves left"),
            action("range-letter", 6, "press", locator=css("input[name=my-range]"), key="A", expected_outcome="failure", expected_result="the range thumb remains unchanged"),
            action("color-focus", 8, "click", locator=css("input[name=my-colors]"), timeout_ms=1000, expected_result="the compact color control receives focus", required=False),
        ],
        "workflow-20-selenium-datalist": [
            action("fill-datalist", 1, "fill", locator=css("input[name=my-datalist]"), value="New York", expected_result="the datalist field contains New York"),
            action("select-one", 3, "select", locator=css("select[name=my-select]"), value="1", expected_result="the first select option is chosen"),
            action("fill-datalist-missing", 5, "fill", locator=css("input[name=my-datalist]"), value="Not in list", expected_outcome="failure", expected_result="free text is visible but no datalist suggestion matches"),
            action("submit-form", 8, "click", locator=role("button", "Submit"), expected_result="the form submission result opens"),
        ],
        "workflow-21-todomvc-react-add": [
            action("add-first", 1, "fill", locator=css(".new-todo"), value="first task", expected_result="the new-todo field contains first task"),
            action("commit-first", 2, "press", locator=css(".new-todo"), key="Enter", expected_result="first task appears in the list"),
            action("add-second", 3.5, "fill", locator=css(".new-todo"), value="second task", expected_result="the field contains second task"),
            action("commit-second", 4.5, "press", locator=css(".new-todo"), key="Enter", expected_result="second task appears and the count changes"),
            action("commit-empty", 6, "press", locator=css(".new-todo"), key="Enter", expected_outcome="failure", expected_result="no empty todo is added"),
            action("complete-first", 8, "check", locator=css(".todo-list li:first-child .toggle"), expected_result="the first task is visibly completed"),
        ],
        "workflow-22-todomvc-vue-complete-filter": [
            action("add-active", 1, "fill", locator=css(".new-todo"), value="active item", expected_result="the input contains active item"),
            action("commit-active", 2, "press", locator=css(".new-todo"), key="Enter", expected_result="active item appears"),
            action("add-completed", 3, "fill", locator=css(".new-todo"), value="completed item", expected_result="the input contains completed item"),
            action("commit-completed", 4, "press", locator=css(".new-todo"), key="Enter", expected_result="completed item appears"),
            action("complete-second", 5, "check", locator=css(".todo-list li:nth-child(2) .toggle"), expected_result="the second item becomes completed"),
            action("show-completed", 7, "click", locator=locator("text", "Completed", exact=True), expected_result="only completed items are shown"),
            action("show-active", 9, "click", locator=locator("text", "Active", exact=True), expected_result="only active items are shown"),
        ],
        "workflow-23-todomvc-svelte-edit": [
            action("add-item", 1, "fill", locator=css(".new-todo"), value="editable item", expected_result="the input contains editable item"),
            action("commit-item", 2, "press", locator=css(".new-todo"), key="Enter", expected_result="editable item appears"),
            action("open-edit", 3.5, "double_click", locator=css(".todo-list li label"), expected_result="the todo enters edit mode"),
            action("replace-edit", 4.5, "fill", locator=css(".todo-list li .edit"), value="edited item", expected_result="the edit field contains edited item"),
            action("commit-edit", 5.5, "press", locator=css(".todo-list li .edit"), key="Enter", expected_result="edited item is committed"),
            action("open-cancel-edit", 7, "double_click", locator=css(".todo-list li label"), expected_result="the todo enters edit mode again"),
            action("cancel-edit", 8, "press", locator=css(".todo-list li .edit"), key="Escape", expected_outcome="failure", expected_result="the visible label remains edited item"),
        ],
        "workflow-24-todomvc-preact-clear": [
            action("add-first", 1, "fill", locator=css(".new-todo"), value="clear me", expected_result="the input contains clear me"),
            action("commit-first", 2, "press", locator=css(".new-todo"), key="Enter", expected_result="clear me appears"),
            action("add-second", 3, "fill", locator=css(".new-todo"), value="keep me", expected_result="the input contains keep me"),
            action("commit-second", 4, "press", locator=css(".new-todo"), key="Enter", expected_result="keep me appears"),
            action("complete-first", 5, "check", locator=css(".todo-list li:first-child .toggle"), expected_result="clear me is completed"),
            action("clear-completed", 7, "click", locator=css(".clear-completed"), expected_result="the completed item is removed"),
            action("clear-again", 9, "click", locator=css(".clear-completed"), timeout_ms=600, expected_outcome="failure", expected_result="no additional item is removed", required=False),
        ],
        "workflow-25-todomvc-lit-filter": [
            action("add-first", 1, "fill", locator=css(".new-todo"), value="active lit item", expected_result="the input contains active lit item"),
            action("commit-first", 2, "press", locator=css(".new-todo"), key="Enter", expected_result="active lit item appears"),
            action("add-second", 3, "fill", locator=css(".new-todo"), value="completed lit item", expected_result="the input contains completed lit item"),
            action("commit-second", 4, "press", locator=css(".new-todo"), key="Enter", expected_result="completed lit item appears"),
            action("complete-second", 5, "check", locator=css(".todo-list li:nth-child(2) .toggle"), expected_result="the second item is completed"),
            action("show-active", 7, "click", locator=locator("text", "Active", exact=True), expected_result="the active filter hides the completed item"),
            action("show-completed", 8.5, "click", locator=locator("text", "Completed", exact=True), expected_result="the completed filter shows the completed item"),
            action("show-all", 10, "click", locator=locator("text", "All", exact=True), expected_result="both items are visible again"),
        ],
        "workflow-26-w3-modal": [
            action("open-modal", 1, "click", locator=role("button", "Open Modal", exact=False, frame=IFRAME), expected_result="the modal overlay opens"),
            action("wait-modal", 1.2, "wait_for", locator=css("#myModal", frame=IFRAME), state="visible", timeout_ms=2000, expected_result="the modal content is visible"),
            action("close-modal", 4, "click", locator=css(".close", frame=IFRAME), expected_result="the modal closes"),
            action("close-hidden-modal", 6, "click", locator=css(".close", frame=IFRAME), timeout_ms=600, expected_outcome="failure", expected_result="the hidden close control cannot change the screen", required=False),
            action("open-modal-again", 8, "click", locator=role("button", "Open Modal", exact=False, frame=IFRAME), expected_result="the modal opens again"),
        ],
        "workflow-27-w3-tabs": [
            action("open-london", 1, "click", locator=css(".tablinks:nth-of-type(1)", frame=IFRAME), expected_result="the London tab content is visible"),
            action("open-paris", 3, "click", locator=css(".tablinks:nth-of-type(2)", frame=IFRAME), expected_result="the Paris tab content is visible"),
            action("open-tokyo", 5, "click", locator=css(".tablinks:nth-of-type(3)", frame=IFRAME), expected_result="the Tokyo tab content is visible"),
            action("click-missing-tab", 7, "click", locator=css(".tablinks:nth-of-type(4)", frame=IFRAME), timeout_ms=600, expected_outcome="failure", expected_result="no fourth tab opens", required=False),
            action("return-london", 9, "click", locator=css(".tablinks:nth-of-type(1)", frame=IFRAME), expected_result="the London content is visible again"),
        ],
        "workflow-28-w3-snackbar": [
            action("show-snackbar", 1, "click", locator=role("button", "Show Snackbar", exact=False, frame=IFRAME), expected_result="the snackbar appears"),
            action("wait-snackbar", 1.2, "wait_for", locator=css("#snackbar.show", frame=IFRAME), state="visible", timeout_ms=1500, expected_result="the snackbar message is visible"),
            action("wait-snackbar-hidden", 2, "wait_for", locator=css("#snackbar", frame=IFRAME), state="hidden", timeout_ms=5000, expected_result="the snackbar disappears automatically"),
            action("show-snackbar-again", 7, "click", locator=role("button", "Show Snackbar", exact=False, frame=IFRAME), expected_result="the snackbar appears again"),
        ],
        "workflow-29-w3-accordion": [
            action("open-first", 1, "click", locator=css(".accordion:nth-of-type(1)", frame=IFRAME), expected_result="the first accordion panel expands"),
            action("close-first", 3, "click", locator=css(".accordion:nth-of-type(1)", frame=IFRAME), expected_result="the first accordion panel collapses"),
            action("open-second", 5, "click", locator=css(".accordion:nth-of-type(2)", frame=IFRAME), expected_result="the second accordion panel expands"),
            action("open-third", 7, "click", locator=css(".accordion:nth-of-type(3)", frame=IFRAME), expected_result="the third accordion panel expands"),
            action("click-missing-fourth", 9, "click", locator=css(".accordion:nth-of-type(4)", frame=IFRAME), timeout_ms=600, expected_outcome="failure", expected_result="no fourth accordion panel opens", required=False),
        ],
        "workflow-30-w3-filter-list": [
            action("filter-a", 1, "fill", locator=css("#myInput", frame=IFRAME), value="A", expected_result="the list shows names matching A"),
            action("filter-al", 3, "fill", locator=css("#myInput", frame=IFRAME), value="Al", expected_result="the list narrows to names matching Al"),
            action("filter-no-match", 5, "fill", locator=css("#myInput", frame=IFRAME), value="NoSuchName", expected_outcome="failure", expected_result="no list item remains visible"),
            action("clear-filter", 7, "fill", locator=css("#myInput", frame=IFRAME), value="", expected_result="the full list is visible again"),
            action("filter-b", 9, "fill", locator=css("#myInput", frame=IFRAME), value="B", expected_result="the list shows names matching B"),
        ],
    }


def build_specs(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = plan.get("workflow_sources")
    case_ids = plan.get("case_ids")
    if not isinstance(sources, list) or not isinstance(case_ids, list):
        raise RuntimeError("plan must contain workflow_sources and case_ids")
    actions = planned_actions()
    if set(actions) != set(case_ids):
        raise RuntimeError(
            f"action cases differ from plan: missing={sorted(set(case_ids) - set(actions))}, "
            f"extra={sorted(set(actions) - set(case_ids))}"
        )
    source_by_id = {source["case_id"]: source for source in sources}
    result = {}
    for case_id in case_ids:
        source = source_by_id[case_id]
        rows = actions[case_id]
        identifiers = [row["id"] for row in rows]
        times = [row["at_seconds"] for row in rows]
        if len(identifiers) != len(set(identifiers)):
            raise RuntimeError(f"duplicate action ids in {case_id}")
        if times != sorted(times) or any(value >= DURATION_SECONDS for value in times):
            raise RuntimeError(f"invalid action schedule in {case_id}")
        result[case_id] = {
            "schema_version": 1,
            "case_id": case_id,
            "source_url": source["url"],
            "goal": source["goal"],
            "duration_seconds": DURATION_SECONDS,
            "capture_policy": CAPTURE_POLICY,
            "actions": rows,
        }
    return result


def write_specs(
    plan_path: Path,
    output_dir: Path,
    manifest_path: Path,
    *,
    collector_revision: str,
    check: bool,
) -> None:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    specs = build_specs(plan)
    output_dir.mkdir(parents=True, exist_ok=True)
    expected_names = {f"{case_id}.json" for case_id in specs}
    existing_names = {path.name for path in output_dir.glob("*.json")}
    unexpected = sorted(existing_names - expected_names)
    if unexpected:
        raise RuntimeError(f"unexpected action files: {unexpected}")
    changed = []
    for case_id, payload in specs.items():
        destination = output_dir / f"{case_id}.json"
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if check:
            if not destination.is_file() or destination.read_text(encoding="utf-8") != text:
                changed.append(destination.name)
        else:
            destination.write_text(text, encoding="utf-8")
    if changed:
        raise RuntimeError(f"action files are stale or missing: {changed}")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "kind": "signum_claim180_browser_actions",
        "collector_revision": collector_revision,
        "plan": plan_path.resolve().relative_to(manifest_path.parent.resolve()).as_posix(),
        "plan_bytes": plan_path.stat().st_size,
        "plan_sha256": sha256_file(plan_path),
        "capture_policy": CAPTURE_POLICY,
        "duration_seconds": DURATION_SECONDS,
        "cases": [
            {
                "case_id": case_id,
                "action_file": (output_dir / f"{case_id}.json")
                .resolve()
                .relative_to(manifest_path.parent.resolve())
                .as_posix(),
                "bytes": (output_dir / f"{case_id}.json").stat().st_size,
                "sha256": sha256_file(output_dir / f"{case_id}.json"),
            }
            for case_id in specs
        ],
    }
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if check:
        if (
            not manifest_path.is_file()
            or manifest_path.read_text(encoding="utf-8") != manifest_text
        ):
            raise RuntimeError("actions manifest is stale or missing")
    else:
        manifest_path.write_text(manifest_text, encoding="utf-8")
    print(
        json.dumps(
            {
                "cases": len(specs),
                "output": str(output_dir.resolve()),
                "manifest": str(manifest_path.resolve()),
                "check": check,
            }
        )
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the preregistered Claim 180 browser action files.")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--collector-revision", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if len(args.collector_revision) not in {40, 64} or any(
        character not in "0123456789abcdefABCDEF"
        for character in args.collector_revision
    ):
        raise RuntimeError("collector revision must be a full immutable hash")
    write_specs(
        args.plan,
        args.output,
        args.manifest,
        collector_revision=args.collector_revision,
        check=args.check,
    )


if __name__ == "__main__":
    main()
