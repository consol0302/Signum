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


def loc(by: str, value: str | None = None, **fields: Any) -> dict[str, Any]:
    result = {"by": by, **fields}
    if value is not None:
        result["value"] = value
    return result


def css(value: str, *, frame: str | None = None) -> dict[str, Any]:
    return loc("css", value, **({"frame": frame} if frame else {}))


def role(role_name: str, name: str, *, exact: bool = True) -> dict[str, Any]:
    return loc("role", role=role_name, name=name, exact=exact)


def label(value: str, *, exact: bool = False) -> dict[str, Any]:
    return loc("label", value, exact=exact)


def placeholder(value: str, *, exact: bool = False) -> dict[str, Any]:
    return loc("placeholder", value, exact=exact)


def text(value: str, *, exact: bool = True) -> dict[str, Any]:
    return loc("text", value, exact=exact)


def action(
    identifier: str,
    at_seconds: float,
    kind: str,
    *,
    expected_result: str,
    expected_outcome: str = "success",
    required: bool = True,
    **fields: Any,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "at_seconds": at_seconds,
        "type": kind,
        "expected_outcome": expected_outcome,
        "expected_result": expected_result,
        "required": required,
        **fields,
    }


def candidate(
    case_id: str,
    url: str,
    goal: str,
    actions: list[dict[str, Any]],
    *,
    duration_seconds: int = 12,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "url": url,
        "goal": goal,
        "duration_seconds": duration_seconds,
        "actions": actions,
    }


def build_candidates() -> list[dict[str, Any]]:
    expand = "https://practice.expandtesting.com"
    practice = "https://practice-automation.com"
    todo = "https://demo.playwright.dev/todomvc/"
    rows = [
        candidate("v3-01-expand-inputs", f"{expand}/inputs", "Enter four input types, display their values, and clear the form.", [
            action("fill-number", 1, "fill", locator=css("input[type=number]"), value="42", expected_result="number input shows 42"),
            action("fill-text", 2, "fill", locator=css("input[type=text]"), value="Signum input", expected_result="text input shows Signum input"),
            action("fill-password", 3, "fill", locator=css("input[type=password]"), value="VisibleState9!", expected_result="password input is populated"),
            action("fill-date", 4, "fill", locator=css("input[type=date]"), value="2026-08-21", expected_result="date input shows the frozen date"),
            action("display", 6, "click", locator=role("button", "Display Inputs"), expected_result="entered values are displayed"),
            action("clear", 9, "click", locator=role("button", "Clear Inputs"), expected_result="inputs and displayed values are cleared"),
        ]),
        candidate("v3-02-expand-login-success", f"{expand}/login", "Log in with the site's published practice credentials and verify the secure state.", [
            action("fill-user", 1, "fill", locator=css("#username"), value="practice", expected_result="username is populated"),
            action("fill-password", 2, "fill", locator=css("#password"), value="SuperSecretPassword!", expected_result="password is populated"),
            action("login", 3, "click", locator=role("button", "Login"), expected_result="the secure page opens"),
            action("wait-secure", 5, "wait_for", locator=text("You logged into a secure area!", exact=False), timeout_ms=5000, expected_result="the success message is visible"),
        ]),
        candidate("v3-03-expand-login-bad-user", f"{expand}/login", "Submit an invalid username and verify that access is rejected.", [
            action("fill-user", 1, "fill", locator=css("#username"), value="wrongUser", expected_result="invalid username is populated"),
            action("fill-password", 2, "fill", locator=css("#password"), value="SuperSecretPassword!", expected_result="password is populated"),
            action("login", 3, "click", locator=role("button", "Login"), expected_outcome="failure", expected_result="login remains rejected"),
            action("wait-error", 5, "wait_for", locator=text("Invalid username.", exact=False), timeout_ms=5000, expected_result="invalid username message is visible"),
        ]),
        candidate("v3-04-expand-login-bad-password", f"{expand}/login", "Submit an invalid password and verify that access is rejected.", [
            action("fill-user", 1, "fill", locator=css("#username"), value="practice", expected_result="username is populated"),
            action("fill-password", 2, "fill", locator=css("#password"), value="WrongPassword", expected_result="invalid password is populated"),
            action("login", 3, "click", locator=role("button", "Login"), expected_outcome="failure", expected_result="login remains rejected"),
            action("wait-error", 5, "wait_for", locator=text("Invalid password.", exact=False), timeout_ms=5000, expected_result="invalid password message is visible"),
        ]),
        candidate("v3-05-expand-radio", f"{expand}/radio-buttons", "Change color and sport radio selections and observe the small control states.", [
            action("red", 1, "check", locator=label("Red", exact=True), expected_result="Red is selected"),
            action("football", 3, "check", locator=label("Football", exact=True), expected_result="Football is selected"),
            action("green", 5, "check", locator=label("Green", exact=True), expected_result="Green replaces Red"),
            action("tennis", 7, "check", locator=label("Tennis", exact=True), expected_result="Tennis replaces Football"),
        ]),
        candidate("v3-06-expand-form-invalid", f"{expand}/form-validation", "Submit an empty validation form, then partially fill it and retain visible errors.", [
            action("empty-submit", 1, "click", locator=role("button", "Register", exact=False), expected_outcome="failure", expected_result="required field errors appear"),
            action("fill-name", 3, "fill", locator=label("Contact Name"), value="Signum Tester", expected_result="contact name becomes valid"),
            action("fill-number", 5, "fill", locator=label("Contact number"), value="invalid", expected_outcome="failure", expected_result="contact number remains invalid"),
            action("partial-submit", 7, "click", locator=role("button", "Register", exact=False), expected_outcome="failure", expected_result="remaining validation errors stay visible"),
        ]),
        candidate("v3-07-expand-add-remove", f"{expand}/add-remove-elements", "Add three elements and remove them one by one.", [
            action("add-1", 1, "click", locator=role("button", "Add Element"), expected_result="one Delete button appears"),
            action("add-2", 2, "click", locator=role("button", "Add Element"), expected_result="a second Delete button appears"),
            action("add-3", 3, "click", locator=role("button", "Add Element"), expected_result="a third Delete button appears"),
            action("delete-1", 5, "click", locator=css("button.added-manually >> nth=0"), expected_result="one added element is removed"),
            action("delete-2", 7, "click", locator=css("button.added-manually >> nth=0"), expected_result="a second added element is removed"),
            action("delete-3", 9, "click", locator=css("button.added-manually >> nth=0"), expected_result="all added elements are removed"),
        ]),
        candidate("v3-08-expand-notification", f"{expand}/notification-message", "Request successive notification messages and observe transient feedback.", [
            action("message-1", 1, "click", locator=role("link", "Click here", exact=False), expected_result="a notification message is rendered"),
            action("message-2", 4, "click", locator=role("link", "Click here", exact=False), expected_result="a new notification message is rendered"),
            action("message-3", 7, "click", locator=role("link", "Click here", exact=False), expected_result="another notification message is rendered"),
        ]),
        candidate("v3-09-expand-autocomplete", f"{expand}/autocomplete", "Type country prefixes, choose a suggestion, and submit it.", [
            action("type-prefix", 1, "fill", locator=placeholder("Country name"), value="Uni", expected_result="matching country suggestions appear"),
            action("choose-country", 3, "click", locator=text("United States", exact=True), expected_result="United States is selected"),
            action("submit", 5, "click", locator=role("button", "Submit"), expected_result="the selected country is submitted"),
        ]),
        candidate("v3-10-expand-challenging-dom", f"{expand}/challenging-dom", "Exercise small generated controls and table actions on a dense page.", [
            action("baz", 1, "click", locator=text("baz", exact=True), expected_result="the baz control responds"),
            action("foo", 3, "click", locator=text("foo", exact=True), expected_result="the foo control responds"),
            action("first-edit", 5, "click", locator=css("table tbody tr:nth-child(1) a >> nth=0"), expected_result="the first row edit action is selected"),
            action("first-delete", 7, "click", locator=css("table tbody tr:nth-child(1) a >> nth=1"), expected_result="the first row delete action is selected"),
        ]),
        candidate("v3-11-expand-checkboxes", f"{expand}/checkboxes", "Toggle both checkboxes through opposite states.", [
            action("check-first", 1, "check", locator=css("input[type=checkbox] >> nth=0"), expected_result="Checkbox 1 is checked"),
            action("uncheck-second", 3, "uncheck", locator=css("input[type=checkbox] >> nth=1"), expected_result="Checkbox 2 is unchecked"),
            action("uncheck-first", 5, "uncheck", locator=css("input[type=checkbox] >> nth=0"), expected_result="Checkbox 1 is unchecked"),
            action("check-second", 7, "check", locator=css("input[type=checkbox] >> nth=1"), expected_result="Checkbox 2 is checked"),
        ]),
        candidate("v3-12-expand-keypress", f"{expand}/key-presses", "Send several keys and observe the reported key after each press.", [
            action("escape", 1, "press", locator=css("input"), key="Escape", expected_result="Escape is reported"),
            action("space", 3, "press", locator=css("input"), key="Space", expected_result="Space is reported"),
            action("arrow-down", 5, "press", locator=css("input"), key="ArrowDown", expected_result="ArrowDown is reported"),
            action("enter", 7, "press", locator=css("input"), key="Enter", expected_result="Enter is reported"),
        ]),
        candidate("v3-13-expand-dropdowns", f"{expand}/dropdown", "Change the simple, page-size, and country dropdown selections.", [
            action("simple-one", 1, "select", locator=css("select >> nth=0"), value="1", expected_result="Option 1 is selected"),
            action("simple-two", 3, "select", locator=css("select >> nth=0"), value="2", expected_result="Option 2 replaces Option 1"),
            action("page-size", 5, "select", locator=css("select >> nth=1"), value="20", expected_result="the page size changes"),
            action("country", 7, "select", locator=css("select >> nth=2"), value="US", expected_result="United States is selected"),
        ]),
        candidate("v3-14-expand-slider", f"{expand}/horizontal-slider", "Move the focused range control right and left while observing its value.", [
            action("focus", 1, "click", locator=css("input[type=range]"), expected_result="the range control is focused"),
            action("right-1", 2, "press", locator=css("input[type=range]"), key="ArrowRight", expected_result="the value increases"),
            action("right-2", 3, "press", locator=css("input[type=range]"), key="ArrowRight", expected_result="the value increases again"),
            action("left", 5, "press", locator=css("input[type=range]"), key="ArrowLeft", expected_result="the value decreases"),
        ]),
        candidate("v3-15-expand-hovers", f"{expand}/hovers", "Reveal each user card's small hover overlay in sequence.", [
            action("hover-user-1", 1, "hover", locator=css(".figure >> nth=0"), expected_result="user1 details appear"),
            action("hover-user-2", 3, "hover", locator=css(".figure >> nth=1"), expected_result="user2 details replace user1"),
            action("hover-user-3", 5, "hover", locator=css(".figure >> nth=2"), expected_result="user3 details replace user2"),
        ]),
        candidate("v3-16-expand-tooltips", f"{expand}/tooltips", "Reveal tooltips at several small button positions.", [
            action("top", 1, "hover", locator=role("button", "Tooltip on top"), expected_result="the top tooltip appears"),
            action("end", 3, "hover", locator=role("button", "Tooltip on end"), expected_result="the end tooltip appears"),
            action("bottom", 5, "hover", locator=role("button", "Tooltip on bottom"), expected_result="the bottom tooltip appears"),
            action("html", 7, "hover", locator=role("button", "Tooltip with HTML"), expected_result="the HTML tooltip appears"),
        ]),
        candidate("v3-17-expand-scrollbars", f"{expand}/scrollbars", "Locate and click the button hidden inside a small scroll area.", [
            action("hover-hidden", 1, "hover", locator=role("button", "Hiding Button"), expected_result="the scroll area reveals the hidden button"),
            action("click-hidden", 3, "click", locator=role("button", "Hiding Button"), expected_result="the hidden button is clicked"),
            action("click-again", 6, "click", locator=role("button", "Hiding Button"), expected_result="the button responds again"),
        ]),
        candidate("v3-18-expand-random", f"{expand}/random-number", "Observe a generated number, reload once, and observe its replacement.", [
            action("wait-initial", 1, "wait_for", locator=role("heading", "Random Number for Automation Testing"), expected_result="the initial random-number page is visible"),
            action("reload", 4, "reload", timeout_ms=5000, expected_result="the page generates a replacement number"),
            action("wait-reloaded", 6, "wait_for", locator=role("heading", "Random Number for Automation Testing"), expected_result="the reloaded random-number page is visible"),
        ]),
        candidate("v3-19-expand-bmi", f"{expand}/bmi", "Calculate a BMI after changing age, height, and weight.", [
            action("age", 1, "fill", locator=label("Age", exact=False), value="29", expected_result="age shows 29"),
            action("height", 2, "fill", locator=label("Height", exact=False), value="175", expected_result="height shows 175"),
            action("weight", 3, "fill", locator=label("Weight", exact=False), value="68", expected_result="weight shows 68"),
            action("calculate", 5, "click", locator=role("button", "Calculate"), expected_result="a BMI report appears"),
        ]),
        candidate("v3-20-expand-bmi-clear", f"{expand}/bmi", "Calculate a different BMI and then clear the calculator.", [
            action("age", 1, "fill", locator=label("Age", exact=False), value="45", expected_result="age shows 45"),
            action("height", 2, "fill", locator=label("Height", exact=False), value="182", expected_result="height shows 182"),
            action("weight", 3, "fill", locator=label("Weight", exact=False), value="92", expected_result="weight shows 92"),
            action("calculate", 5, "click", locator=role("button", "Calculate"), expected_result="a BMI report appears"),
            action("clear", 8, "click", locator=role("button", "Clear"), expected_result="the calculator and report are cleared"),
        ]),
        candidate("v3-21-expand-password", f"{expand}/secure-password-checker", "Enter weak and strong passwords and observe live requirement indicators.", [
            action("weak", 1, "fill", locator=label("Password"), value="short", expected_outcome="failure", expected_result="several password requirements remain unmet"),
            action("mixed", 4, "fill", locator=label("Password"), value="LongerPassword", expected_outcome="failure", expected_result="the number or special-character requirement remains unmet"),
            action("strong", 7, "fill", locator=label("Password"), value="LongerPassword9!", expected_result="all password requirements are met"),
        ]),
        candidate("v3-22-expand-dynamic-table", f"{expand}/dynamic-table", "Observe the shuffled process table before and after one reload.", [
            action("wait-table", 1, "wait_for", locator=text("Chrome CPU:", exact=False), expected_result="the Chrome CPU label is visible"),
            action("reload", 4, "reload", timeout_ms=5000, expected_result="table positions and values are regenerated"),
            action("wait-new-table", 6, "wait_for", locator=text("Chrome CPU:", exact=False), expected_result="the replacement Chrome CPU label is visible"),
        ]),
        candidate("v3-23-expand-infinite-scroll", f"{expand}/infinite-scroll", "Scroll through successive dynamically appended content regions.", [
            action("scroll-1", 1, "scroll", x=0, y=650, expected_result="lower content enters view"),
            action("scroll-2", 3, "scroll", x=0, y=900, expected_result="more content is appended or revealed"),
            action("scroll-3", 5, "scroll", x=0, y=1200, expected_result="a later content region enters view"),
            action("scroll-up", 8, "scroll", x=0, y=-700, expected_result="an earlier content region returns"),
        ]),
        candidate("v3-24-expand-floating-menu", f"{expand}/floating-menu", "Scroll a long page while verifying the floating navigation remains available.", [
            action("scroll-down", 1, "scroll", x=0, y=900, expected_result="the document moves while the floating menu remains"),
            action("scroll-further", 3, "scroll", x=0, y=1100, expected_result="later content appears beneath the floating menu"),
            action("hover-home", 6, "hover", locator=role("link", "Home"), expected_result="the floating Home link receives hover focus"),
            action("scroll-up", 8, "scroll", x=0, y=-1200, expected_result="earlier content returns"),
        ]),
        candidate("v3-25-expand-add-remove-alt", f"{expand}/add-remove-elements", "Add two controls, attempt an unavailable third delete after removal, and preserve the failure.", [
            action("add-1", 1, "click", locator=role("button", "Add Element"), expected_result="one Delete button appears"),
            action("add-2", 2, "click", locator=role("button", "Add Element"), expected_result="two Delete buttons are visible"),
            action("delete-1", 4, "click", locator=css("button.added-manually >> nth=0"), expected_result="one Delete button remains"),
            action("delete-2", 6, "click", locator=css("button.added-manually >> nth=0"), expected_result="no Delete button remains"),
            action("delete-missing", 8, "click", locator=css("button.added-manually >> nth=0"), timeout_ms=600, required=False, expected_outcome="failure", expected_result="the absent Delete button cannot be clicked"),
        ]),
        candidate("v3-26-practice-delay", f"{practice}/javascript-delays/", "Start the countdown and observe the delayed Liftoff state.", [
            action("start", 1, "click", locator=text("Start", exact=True), expected_result="the countdown starts"),
            action("wait-liftoff", 1.2, "wait_for", locator=text("Liftoff!", exact=False), timeout_ms=11000, expected_result="Liftoff becomes visible after the delay"),
        ], duration_seconds=14),
        candidate("v3-27-practice-slider", f"{practice}/slider/", "Move the range slider and observe its live value.", [
            action("focus", 1, "click", locator=css("input[type=range]"), expected_result="the slider is focused"),
            action("right", 2, "press", locator=css("input[type=range]"), key="ArrowRight", expected_result="the value increases"),
            action("right-again", 3, "press", locator=css("input[type=range]"), key="ArrowRight", expected_result="the value increases again"),
            action("left", 5, "press", locator=css("input[type=range]"), key="ArrowLeft", expected_result="the value decreases"),
        ]),
        candidate("v3-28-practice-click-events", f"{practice}/click-events/", "Click four animal controls and observe their changing response text.", [
            action("cat", 1, "click", locator=text("Cat", exact=True), expected_result="cat response text appears"),
            action("dog", 3, "click", locator=text("Dog", exact=True), expected_result="dog response replaces cat"),
            action("pig", 5, "click", locator=text("Pig", exact=True), expected_result="pig response replaces dog"),
            action("cow", 7, "click", locator=text("Cow", exact=True), expected_result="cow response replaces pig"),
        ]),
        candidate("v3-29-practice-iframes", f"{practice}/iframes/", "Move focus among embedded frame regions and scroll the surrounding page.", [
            action("hover-frame-1", 1, "hover", locator=css("iframe >> nth=0"), expected_result="the first embedded region receives pointer focus"),
            action("scroll", 3, "scroll", x=0, y=500, expected_result="the second embedded region enters view"),
            action("hover-frame-2", 5, "hover", locator=css("iframe >> nth=1"), expected_result="the second embedded region receives pointer focus"),
            action("scroll-up", 8, "scroll", x=0, y=-400, expected_result="the first embedded region returns"),
        ]),
        candidate("v3-30-practice-accordion", f"{practice}/accordions/", "Expand and collapse the accordion while observing its content.", [
            action("open", 1, "click", locator=text("Click to see more", exact=True), expected_result="accordion content expands"),
            action("wait-content", 2, "wait_for", locator=text("This is an accordion item.", exact=True), expected_result="accordion content is visible"),
            action("close", 5, "click", locator=text("Click to see more", exact=True), expected_result="accordion content collapses"),
            action("open-again", 8, "click", locator=text("Click to see more", exact=True), expected_result="accordion content expands again"),
        ]),
        candidate("v3-31-practice-form", f"{practice}/form-fields/", "Fill a mixed-control form and submit it.", [
            action("name", 1, "fill", locator=label("Name", exact=True), value="Signum Tester", expected_result="name is populated"),
            action("password", 2, "fill", locator=label("Password", exact=True), value="FormPass9!", expected_result="password is populated"),
            action("coffee", 3, "check", locator=label("Coffee", exact=True), expected_result="Coffee is selected"),
            action("blue", 4, "check", locator=label("Blue", exact=True), expected_result="Blue is selected"),
            action("automation", 5, "select", locator=css("select"), value="yes", expected_result="automation preference is selected"),
            action("submit", 8, "click", locator=role("button", "Submit"), expected_result="the form is submitted"),
        ]),
        candidate("v3-32-practice-modals", f"{practice}/modals/", "Open and close the simple modal, then open the form modal.", [
            action("open-simple", 1, "click", locator=role("button", "Simple Modal"), expected_result="the simple modal opens"),
            action("wait-simple", 2, "wait_for", locator=text("Hi, I’m a simple modal.", exact=True), expected_result="simple modal text is visible"),
            action("close-simple", 4, "click", locator=css(".pum-close:visible >> nth=0"), expected_result="the simple modal closes"),
            action("open-form", 6, "click", locator=role("button", "Form Modal"), expected_result="the form modal opens"),
            action("wait-form", 7, "wait_for", locator=text("Modal Containing A Form", exact=True), expected_result="the form modal heading is visible"),
        ]),
        candidate("v3-33-practice-hover", f"{practice}/hover/", "Reveal and dismiss the hover transformation several times.", [
            action("hover-target", 1, "hover", locator=text("Mouse over me", exact=True), expected_result="hover styling or content appears"),
            action("hover-heading", 3, "hover", locator=role("heading", "Hover"), expected_result="the target hover state clears"),
            action("hover-target-again", 5, "hover", locator=text("Mouse over me", exact=True), expected_result="the hover state appears again"),
        ]),
        candidate("v3-34-practice-ads", f"{practice}/ads/", "Observe and close the page advertisement if it appears.", [
            action("wait-ad", 1, "wait_for", locator=css(".pum-container"), timeout_ms=5000, expected_result="the advertisement popup becomes visible"),
            action("close-ad", 4, "click", locator=css(".pum-close:visible >> nth=0"), expected_result="the advertisement popup closes"),
            action("click-closed-ad", 7, "click", locator=css(".pum-close:visible >> nth=0"), timeout_ms=600, required=False, expected_outcome="failure", expected_result="the closed popup cannot be closed again"),
        ]),
        candidate("v3-35-practice-popup-tooltip", f"{practice}/popups/", "Reveal and dismiss the non-dialog tooltip without accepting browser popups.", [
            action("hover-tooltip", 1, "hover", locator=text("<< click me to see a tooltip >>", exact=True), expected_result="the Cool text tooltip appears"),
            action("wait-tooltip", 2, "wait_for", locator=text("Cool text", exact=True), expected_result="Cool text is visible"),
            action("hover-heading", 4, "hover", locator=role("heading", "Popups"), expected_result="the tooltip disappears"),
            action("hover-again", 7, "hover", locator=text("<< click me to see a tooltip >>", exact=True), expected_result="the tooltip appears again"),
        ]),
    ]

    def todo_case(number: int, suffix: str, goal: str, todo_actions: list[dict[str, Any]]) -> dict[str, Any]:
        return candidate(f"v3-{number:02d}-todo-{suffix}", todo, goal, todo_actions)

    new_todo = css(".new-todo")
    rows.extend([
        todo_case(36, "add", "Add three todos and leave all active.", [
            action("add-one", 1, "fill", locator=new_todo, value="alpha task", expected_result="first todo text is entered"), action("submit-one", 1.5, "press", locator=new_todo, key="Enter", expected_result="first todo appears"),
            action("add-two", 3, "fill", locator=new_todo, value="beta task", expected_result="second todo text is entered"), action("submit-two", 3.5, "press", locator=new_todo, key="Enter", expected_result="second todo appears"),
            action("add-three", 5, "fill", locator=new_todo, value="gamma task", expected_result="third todo text is entered"), action("submit-three", 5.5, "press", locator=new_todo, key="Enter", expected_result="third todo appears"),
        ]),
        todo_case(37, "complete", "Add two todos and complete the first one.", [
            action("add-one", 1, "fill", locator=new_todo, value="complete me", expected_result="first todo text is entered"), action("submit-one", 1.5, "press", locator=new_todo, key="Enter", expected_result="first todo appears"),
            action("add-two", 3, "fill", locator=new_todo, value="stay active", expected_result="second todo text is entered"), action("submit-two", 3.5, "press", locator=new_todo, key="Enter", expected_result="second todo appears"),
            action("complete-one", 5, "check", locator=css(".todo-list li .toggle >> nth=0"), expected_result="the first todo is completed"),
        ]),
        todo_case(38, "edit", "Add a todo, edit its text, and leave the edited state visible.", [
            action("add", 1, "fill", locator=new_todo, value="draft task", expected_result="draft text is entered"), action("submit", 1.5, "press", locator=new_todo, key="Enter", expected_result="draft todo appears"),
            action("edit", 3, "double_click", locator=css(".todo-list li label"), expected_result="the todo enters edit mode"), action("replace", 4, "fill", locator=css(".todo-list li .edit"), value="edited task", expected_result="edited text is entered"), action("commit", 5, "press", locator=css(".todo-list li .edit"), key="Enter", expected_result="the edited todo is committed"),
        ]),
        todo_case(39, "delete", "Add two todos and delete the first via its hover control.", [
            action("add-one", 1, "fill", locator=new_todo, value="delete me", expected_result="first todo text is entered"), action("submit-one", 1.5, "press", locator=new_todo, key="Enter", expected_result="first todo appears"),
            action("add-two", 3, "fill", locator=new_todo, value="keep me", expected_result="second todo text is entered"), action("submit-two", 3.5, "press", locator=new_todo, key="Enter", expected_result="second todo appears"),
            action("hover-first", 5, "hover", locator=css(".todo-list li >> nth=0"), expected_result="the first delete control appears"), action("delete-first", 6, "click", locator=css(".todo-list li .destroy >> nth=0"), expected_result="the first todo is removed"),
        ]),
        todo_case(40, "toggle-all", "Add three todos, toggle all complete, then return all to active.", [
            action("add-a", 1, "fill", locator=new_todo, value="one", expected_result="first text is entered"), action("submit-a", 1.4, "press", locator=new_todo, key="Enter", expected_result="first todo appears"),
            action("add-b", 2.5, "fill", locator=new_todo, value="two", expected_result="second text is entered"), action("submit-b", 2.9, "press", locator=new_todo, key="Enter", expected_result="second todo appears"),
            action("add-c", 4, "fill", locator=new_todo, value="three", expected_result="third text is entered"), action("submit-c", 4.4, "press", locator=new_todo, key="Enter", expected_result="third todo appears"),
            action("complete-all", 6, "check", locator=css("#toggle-all"), expected_result="all todos are completed"), action("activate-all", 8, "uncheck", locator=css("#toggle-all"), expected_result="all todos return to active"),
        ]),
        todo_case(41, "clear-completed", "Add two todos, complete both, and clear the completed list.", [
            action("add-a", 1, "fill", locator=new_todo, value="clear one", expected_result="first text is entered"), action("submit-a", 1.5, "press", locator=new_todo, key="Enter", expected_result="first todo appears"),
            action("add-b", 3, "fill", locator=new_todo, value="clear two", expected_result="second text is entered"), action("submit-b", 3.5, "press", locator=new_todo, key="Enter", expected_result="second todo appears"),
            action("complete-all", 5, "check", locator=css("#toggle-all"), expected_result="both todos are completed"), action("clear", 7, "click", locator=css(".clear-completed"), expected_result="all completed todos are removed"),
        ]),
        todo_case(42, "active-filter", "Create active and completed todos, then show only active items.", [
            action("add-a", 1, "fill", locator=new_todo, value="done item", expected_result="first text is entered"), action("submit-a", 1.5, "press", locator=new_todo, key="Enter", expected_result="first todo appears"),
            action("add-b", 3, "fill", locator=new_todo, value="active item", expected_result="second text is entered"), action("submit-b", 3.5, "press", locator=new_todo, key="Enter", expected_result="second todo appears"),
            action("complete-first", 5, "check", locator=css(".todo-list li .toggle >> nth=0"), expected_result="the first todo is completed"), action("active", 7, "click", locator=role("link", "Active"), expected_result="only the active todo remains visible"),
        ]),
        todo_case(43, "completed-filter", "Create active and completed todos, then show only completed items.", [
            action("add-a", 1, "fill", locator=new_todo, value="finished item", expected_result="first text is entered"), action("submit-a", 1.5, "press", locator=new_todo, key="Enter", expected_result="first todo appears"),
            action("add-b", 3, "fill", locator=new_todo, value="unfinished item", expected_result="second text is entered"), action("submit-b", 3.5, "press", locator=new_todo, key="Enter", expected_result="second todo appears"),
            action("complete-first", 5, "check", locator=css(".todo-list li .toggle >> nth=0"), expected_result="the first todo is completed"), action("completed", 7, "click", locator=role("link", "Completed"), expected_result="only the completed todo remains visible"),
        ]),
        todo_case(44, "edit-cancel", "Enter edit mode, change text, cancel it, and retain the original todo.", [
            action("add", 1, "fill", locator=new_todo, value="original task", expected_result="original text is entered"), action("submit", 1.5, "press", locator=new_todo, key="Enter", expected_result="original todo appears"),
            action("edit", 3, "double_click", locator=css(".todo-list li label"), expected_result="the todo enters edit mode"), action("replace", 4, "fill", locator=css(".todo-list li .edit"), value="cancelled edit", expected_result="replacement text is present in edit mode"), action("cancel", 5, "press", locator=css(".todo-list li .edit"), key="Escape", expected_outcome="failure", expected_result="the edit is cancelled and original text remains"),
        ]),
        todo_case(45, "filter-cycle", "Create mixed todo states and cycle through all filters.", [
            action("add-a", 1, "fill", locator=new_todo, value="cycle done", expected_result="first text is entered"), action("submit-a", 1.5, "press", locator=new_todo, key="Enter", expected_result="first todo appears"),
            action("add-b", 2.5, "fill", locator=new_todo, value="cycle active", expected_result="second text is entered"), action("submit-b", 3, "press", locator=new_todo, key="Enter", expected_result="second todo appears"),
            action("complete-first", 4.5, "check", locator=css(".todo-list li .toggle >> nth=0"), expected_result="the first todo is completed"), action("active", 6, "click", locator=role("link", "Active"), expected_result="only active items are shown"), action("completed", 8, "click", locator=role("link", "Completed"), expected_result="only completed items are shown"), action("all", 10, "click", locator=role("link", "All"), expected_result="all items are shown again"),
        ]),
    ])
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
    if len(candidates) != 45 or len(case_ids) != len(set(case_ids)):
        raise RuntimeError("v3 must contain exactly 45 unique candidates")
    sources = {
        "schema_version": 1,
        "kind": "signum_claim180_v3_candidate_sources",
        "case_ids": case_ids,
        "workflow_sources": [
            {"case_id": row["case_id"], "url": row["url"], "goal": row["goal"]}
            for row in candidates
        ],
    }
    actions_dir.mkdir(parents=True, exist_ok=True)
    sources_path.parent.mkdir(parents=True, exist_ok=True)
    expected_files: dict[Path, str] = {sources_path: json_text(sources)}
    for row in candidates:
        action_ids = [item["id"] for item in row["actions"]]
        times = [item["at_seconds"] for item in row["actions"]]
        if not row["actions"] or len(action_ids) != len(set(action_ids)):
            raise RuntimeError(f"invalid action ids in {row['case_id']}")
        if times != sorted(times) or any(
            value < 0 or value >= row["duration_seconds"] for value in times
        ):
            raise RuntimeError(f"invalid action schedule in {row['case_id']}")
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
        raise RuntimeError(f"unexpected v3 action files: {unexpected}")
    stale = []
    for path, expected in expected_files.items():
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                stale.append(path.name)
        else:
            path.write_text(expected, encoding="utf-8")
    if stale:
        raise RuntimeError(f"v3 files are stale or missing: {stale}")
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
    manifest_content = json_text(manifest)
    if check:
        if not manifest_path.is_file() or manifest_path.read_text(encoding="utf-8") != manifest_content:
            raise RuntimeError("v3 actions manifest is stale or missing")
    else:
        manifest_path.write_text(manifest_content, encoding="utf-8")
    print(json.dumps({"candidates": len(candidates), "check": check, "manifest": str(manifest_path.resolve())}))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the ordered Claim 180 v3 candidate pool.")
    parser.add_argument("--sources", type=Path, required=True)
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
        args.actions,
        args.manifest,
        args.collector_revision,
        check=args.check,
    )


if __name__ == "__main__":
    main()
