from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import cv2


FPS = 20.0
SECONDS_PER_STATE = 1.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the Pilot 60 replay suite from fixed-viewport browser captures."
    )
    parser.add_argument(
        "--captures",
        type=Path,
        required=True,
        help="root containing the per-page pilot60-captures directories",
    )
    parser.add_argument(
        "--selenium-frames",
        type=Path,
        required=True,
        help="directory containing the five Selenium dynamic-page captures",
    )
    parser.add_argument("--output", type=Path, default=Path("pilot60-output"))
    return parser.parse_args()


def passive(
    event_id: str,
    after: int,
    category: str,
    state: str,
    notes: str,
    *,
    risk: str = "normal",
) -> dict[str, Any]:
    return {
        "id": event_id,
        "after": after,
        "category": category,
        "risk": risk,
        "acceptable_states": [state],
        "notes": notes,
    }


def action(
    event_id: str,
    after: int,
    category: str,
    verb: str,
    expected: str,
    state: str,
    notes: str,
    *,
    risk: str = "normal",
    eligible: bool = True,
) -> dict[str, Any]:
    return {
        "id": event_id,
        "after": after,
        "category": category,
        "risk": risk,
        "acceptable_states": [state],
        "action": verb,
        "expected_result": expected,
        "real_world_eligible": eligible,
        "notes": notes,
    }


def case_specs(captures: Path, selenium: Path) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = [
        {
            "id": "selenium-dynamic",
            "url": "https://www.selenium.dev/selenium/web/dynamic.html",
            "root": selenium,
            "goal": "Detect the red box and small input, and verify the reveal action.",
            "states": [
                "initial.png",
                "box-added.png",
                "box-settled.png",
                "input-revealed.png",
                "input-settled.png",
            ],
            "events": [
                passive("red-box-pending", 1, "transient_event", "red_box_still_absent", "Immediately after Add a box, the red box is not visible yet."),
                passive("red-box-appeared", 2, "popup_notification", "red_box_visible", "The settled frame visibly contains the red result box."),
                passive("input-reveal-pending", 3, "transient_event", "input_still_absent", "Immediately after the request, the input has not appeared yet."),
                action("input-reveal-succeeded", 4, "action_success", "clicked Reveal a new input", "a text input appears", "input_visible", "The settled frame visibly contains the input."),
                passive("small-input-settled", 4, "small_ui", "small_input_visible", "The 170 by 21 input is stable and legible."),
            ],
        },
        {
            "id": "dynamic-controls",
            "url": "https://the-internet.herokuapp.com/dynamic_controls",
            "root": captures / "dynamic-controls",
            "goal": "Track loading, result messages, and enabled or disabled controls.",
            "states": [f"{index:02d}-{name}.png" for index, name in enumerate(("initial", "remove-loading", "removed", "add-loading", "added", "disabled-noop", "enable-loading", "enabled", "disabled"))],
            "events": [
                passive("remove-loading", 1, "transient_event", "loading_visible", "A loading indicator briefly replaces the control."),
                passive("checkbox-removed", 2, "popup_notification", "checkbox_removed_message", "Removal finishes and a result message appears."),
                passive("add-loading", 3, "transient_event", "loading_visible", "The add request enters a loading state."),
                passive("checkbox-added", 4, "loading_completion", "checkbox_added", "The checkbox returns after loading."),
                action("disabled-input-click", 5, "action_failure", "clicked the disabled input", "the input receives focus", "input_still_disabled", "The disabled input correctly ignores the click.", risk="high"),
                action("input-enabled", 7, "action_success", "clicked Enable", "the input becomes enabled", "input_enabled", "The enabled input is visibly editable."),
                action("input-disabled", 8, "action_success", "clicked Disable", "the input becomes disabled", "input_disabled", "The input returns to a disabled state."),
            ],
        },
    ]

    for variant in (1, 2):
        specs.append(
            {
                "id": f"dynamic-loading-{variant}",
                "url": f"https://the-internet.herokuapp.com/dynamic_loading/{variant}",
                "root": captures / f"dynamic-loading-{variant}",
                "goal": "Detect the loading interval and verify that Hello World appears.",
                "states": ["00-initial.png", "01-loading.png", "02-complete.png"],
                "events": [
                    passive(f"loading-started-{variant}", 1, "transient_event", "loading_visible", "The loading indicator is visible."),
                    passive(f"loading-finished-{variant}", 2, "loading_completion", "hello_world_visible", "Hello World is visible after loading."),
                    action(f"start-confirmed-{variant}", 2, "action_success", "clicked Start", "Hello World appears", "hello_world_visible", "Forced before/after verification shares the completion transition."),
                ],
            }
        )

    specs.extend(
        [
            {
                "id": "notification-messages",
                "url": "https://the-internet.herokuapp.com/notification_message_rendered",
                "root": captures / "notifications",
                "goal": "Read each notification and avoid calling unsuccessful actions successful.",
                "states": ["00-initial.png", "01-message.png", "02-message.png", "03-message.png", "04-message.png", "05-dismissed.png"],
                "events": [
                    passive("notification-unsuccessful-1", 1, "popup_notification", "unsuccessful_message_visible", "An unsuccessful notification appears.", risk="high"),
                    action("notification-action-failed-1", 1, "action_failure", "clicked Click here", "an action-successful message appears", "unsuccessful_message_visible", "The first request explicitly reports failure.", risk="critical"),
                    passive("notification-unsuccessful-2", 2, "popup_notification", "unsuccessful_message_visible", "A second unsuccessful notification is rendered."),
                    action("notification-action-failed-2", 2, "action_failure", "clicked Click here", "an action-successful message appears", "unsuccessful_message_visible", "The repeated request still reports failure.", risk="critical"),
                    action("notification-action-failed-3", 3, "action_failure", "clicked Click here", "an action-successful message appears", "unsuccessful_message_visible", "The third request still reports failure.", risk="critical"),
                    passive("notification-successful", 4, "popup_notification", "successful_message_visible", "The message changes to Action successful."),
                    passive("notification-dismissed", 5, "popup_notification", "notification_absent", "The notification is dismissed."),
                ],
            },
            {
                "id": "hover-profiles",
                "url": "https://the-internet.herokuapp.com/hovers",
                "root": captures / "hovers",
                "goal": "Track hover overlays without treating cursor motion as task completion.",
                "states": ["00-initial.png", "01-hover-1.png", "02-hover-2.png", "03-hover-3.png", "04-cleared.png"],
                "events": [
                    passive("hover-profile-1", 1, "cursor_hover_focus", "profile_1_hovered", "The first profile overlay appears."),
                    passive("hover-profile-2", 2, "cursor_hover_focus", "profile_2_hovered", "The second profile overlay appears."),
                    passive("hover-profile-3", 3, "cursor_hover_focus", "profile_3_hovered", "The third profile overlay appears."),
                    passive("hover-cleared", 4, "cursor_hover_focus", "hover_overlay_absent", "Moving away clears the overlay."),
                ],
            },
            {
                "id": "infinite-scroll",
                "url": "https://the-internet.herokuapp.com/infinite_scroll",
                "root": captures / "infinite-scroll",
                "goal": "Preserve newly loaded content while navigating a long page.",
                "states": [f"{index:02d}-{'initial' if index == 0 else f'scroll-{index}'}.png" for index in range(7)],
                "events": [
                    passive("scroll-load-1", 1, "loading_completion", "additional_content_loaded", "The first scroll loads more content."),
                    passive("scroll-load-2", 2, "loading_completion", "additional_content_loaded", "The second scroll loads more content."),
                    passive("scroll-load-3", 3, "loading_completion", "additional_content_loaded", "The third scroll loads another content block."),
                    passive("scroll-position-4", 4, "scroll_navigation", "new_scroll_position", "The viewport advances again."),
                    passive("scroll-position-5", 5, "scroll_navigation", "new_scroll_position", "The fifth captured position is visible."),
                    passive("scroll-position-6", 6, "scroll_navigation", "new_scroll_position", "The sixth captured position is visible."),
                ],
            },
            {
                "id": "key-presses",
                "url": "https://the-internet.herokuapp.com/key_presses",
                "root": captures / "key-presses",
                "goal": "Read small key-result text and separate focus changes from content changes.",
                "states": ["00-initial.png", "01-focus.png", "02-a.png", "03-enter.png", "04-escape.png", "05-tab.png"],
                "events": [
                    passive("input-focused", 1, "cursor_hover_focus", "input_focused", "The key input gains focus."),
                    passive("key-a-result", 2, "small_ui", "key_a_visible", "Small result text reports A."),
                    passive("key-enter-result", 3, "small_ui", "key_enter_visible", "Small result text reports ENTER."),
                    passive("key-escape-result", 4, "small_ui", "key_escape_visible", "Small result text reports ESCAPE."),
                    passive("key-tab-result", 5, "small_ui", "key_tab_visible", "Small result text reports TAB."),
                ],
            },
            {
                "id": "add-remove-controls",
                "url": "https://the-internet.herokuapp.com/add_remove_elements/",
                "root": captures / "add-remove",
                "goal": "Track small buttons and verify add or delete actions.",
                "states": [f"{index:02d}-{name}.png" for index, name in enumerate(("initial", "add-1", "add-2", "add-3", "add-4", "delete-1", "delete-2", "delete-3"))],
                "events": [
                    passive("delete-button-1", 1, "small_ui", "one_delete_button", "One small Delete button appears."),
                    passive("delete-button-2", 2, "small_ui", "two_delete_buttons", "A second small Delete button appears."),
                    passive("delete-button-3", 3, "small_ui", "three_delete_buttons", "A third small Delete button appears."),
                    passive("delete-button-4", 4, "small_ui", "four_delete_buttons", "A fourth small Delete button appears."),
                    passive("delete-button-count-3", 5, "small_ui", "three_delete_buttons", "One small button disappears while three remain."),
                    action("delete-confirmed-2", 6, "action_success", "clicked Delete", "one Delete button disappears", "two_delete_buttons", "The visible count decreases to two."),
                    action("delete-confirmed-1", 7, "action_success", "clicked Delete", "one Delete button disappears", "one_delete_button", "The visible count decreases to one."),
                ],
            },
            {
                "id": "todomvc-workflow",
                "url": "https://demo.playwright.dev/todomvc/",
                "root": captures / "todomvc",
                "goal": "Track changing todo counts, filters, and completion state.",
                "states": [f"{index:02d}-{name}.png" for index, name in enumerate(("initial", "add-1", "add-2", "add-3", "add-4", "checked", "active", "completed", "all", "cleared"))],
                "events": [
                    passive("todo-added-1", 1, "animation_game_hud", "todo_count_1", "The task HUD count changes after the first item."),
                    passive("todo-added-2", 2, "animation_game_hud", "todo_count_2", "The task HUD count changes after the second item."),
                    passive("todo-added-3", 3, "animation_game_hud", "todo_count_3", "The task HUD count changes after the third item."),
                    passive("todo-added-4", 4, "animation_game_hud", "todo_count_4", "The task HUD count changes after the fourth item."),
                    passive("todo-completed", 5, "animation_game_hud", "todo_count_3_active", "The remaining-items HUD decreases."),
                    passive("todo-active-filter", 6, "scroll_navigation", "active_filter_visible", "Navigation changes to the Active view."),
                    passive("todo-completed-filter", 7, "scroll_navigation", "completed_filter_visible", "Navigation changes to the Completed-only view."),
                    passive("todo-all-filter", 8, "animation_game_hud", "all_filter_visible", "The All view restores the combined task list."),
                    action("todo-clear-completed", 9, "action_success", "clicked Clear completed", "completed items disappear", "completed_items_absent", "The completed item is removed."),
                ],
            },
        ]
    )

    specs.append(
        {
            "id": "selenium-input-noop",
            "url": "https://www.selenium.dev/selenium/web/dynamic.html",
            "root": selenium,
            "goal": "Reject a constructed no-op reveal replay.",
            "states": ["box-settled.png", "box-settled.png"],
            "events": [
                action(
                    "selenium-input-noop",
                    1,
                    "action_failure",
                    "clicked Reveal a new input",
                    "a text input appears",
                    "input_absent",
                    "Constructed identical-frame replay of the measured negative check; excluded from real-world evidence.",
                    risk="high",
                    eligible=False,
                )
            ],
        }
    )

    constructed = (
        ("todomvc-selected-filter-noop", captures / "todomvc" / "08-all.png", "clicked the already selected All filter", "the selected filter changes", "all_filter_unchanged"),
        ("todomvc-empty-enter-noop", captures / "todomvc" / "09-cleared.png", "pressed Enter in an empty todo input", "a new todo appears", "todo_list_unchanged"),
        ("todomvc-checked-noop", captures / "todomvc" / "05-checked.png", "set an already checked todo to checked", "the remaining-items count decreases", "todo_count_unchanged"),
    )
    for case_id, image, verb, expected, state in constructed:
        specs.append(
            {
                "id": case_id,
                "url": "https://demo.playwright.dev/todomvc/",
                "root": image.parent,
                "goal": "Reject a constructed no-op action replay.",
                "states": [image.name, image.name],
                "events": [
                    action(
                        case_id,
                        1,
                        "action_failure",
                        verb,
                        expected,
                        state,
                        "Constructed identical-frame no-op; excluded from real-world evidence.",
                        risk="high",
                        eligible=False,
                    )
                ],
            }
        )
    return specs


def read_states(spec: dict[str, Any]) -> list[Any]:
    frames = []
    for name in spec["states"]:
        path = spec["root"] / name
        frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError(f"could not read captured browser frame: {path}")
        frames.append(frame)
    target_height = max(frame.shape[0] for frame in frames)
    target_width = max(frame.shape[1] for frame in frames)
    normalized = []
    for frame in frames:
        height, width = frame.shape[:2]
        normalized.append(
            cv2.copyMakeBorder(
                frame,
                0,
                target_height - height,
                0,
                target_width - width,
                cv2.BORDER_CONSTANT,
                value=(0, 0, 0),
            )
        )
    return normalized


def materialize_event(case_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    after = int(raw["after"])
    transition_id = f"{case_id}:{after - 1}->{after}"
    event = {key: value for key, value in raw.items() if key != "after"}
    is_action = raw["category"] in {"action_success", "action_failure"}
    center = after * SECONDS_PER_STATE + (0.5 if is_action else 0.1)
    event.update(
        {
            "start": round(center - 0.15, 3),
            "end": round(center + 0.15, 3),
            "tolerance": 0.05,
            "source_transition_id": transition_id,
        }
    )
    if is_action:
        event["before_timestamp"] = round((after - 1) * SECONDS_PER_STATE + 0.5, 3)
        event["after_timestamp"] = round(after * SECONDS_PER_STATE + 0.5, 3)
    return event


def main() -> None:
    args = parse_args()
    specs = case_specs(args.captures.resolve(), args.selenium_frames.resolve())
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_cases = []
    category_counts: Counter[str] = Counter()
    source_frames: list[str] = []
    frames_per_state = int(FPS * SECONDS_PER_STATE)

    for spec in specs:
        states = read_states(spec)
        video_path = args.output / f"{spec['id']}.avi"
        height, width = states[0].shape[:2]
        writer = cv2.VideoWriter(
            str(video_path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (width, height)
        )
        if not writer.isOpened():
            raise RuntimeError(f"could not create replay video: {video_path}")
        try:
            for frame in states:
                for _ in range(frames_per_state):
                    writer.write(frame)
        finally:
            writer.release()

        events = [materialize_event(spec["id"], raw) for raw in spec["events"]]
        category_counts.update(event["category"] for event in events)
        manifest_cases.append(
            {
                "id": spec["id"],
                "video": video_path.name,
                "goal": spec["goal"],
                "events": events,
            }
        )
        source_frames.extend(str((spec["root"] / name).resolve()) for name in spec["states"])

    manifest = {
        "schema_version": 2,
        "cases": manifest_cases,
        "provenance": {
            "capture_kind": "real_browser_screenshots_replayed_at_fixed_duration",
            "viewport": [1280, 720],
            "fps": FPS,
            "seconds_per_state": SECONDS_PER_STATE,
            "source_urls": sorted({spec["url"] for spec in specs}),
            "source_frames": source_frames,
            "limitations": [
                "Replays preserve captured pixels but not original transition timing.",
                "Frames within a case are right/bottom padded when browser chrome changed the captured viewport by a few pixels.",
                "Five action labels share a source transition with a passive label.",
                "Four constructed identical-frame no-ops are excluded from real-world evidence.",
                "The suite has 60 labels but only 55 independent source transitions.",
            ],
        },
    }
    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "manifest": str(manifest_path.resolve()),
                "cases": len(manifest_cases),
                "events": sum(category_counts.values()),
                "category_counts": dict(sorted(category_counts.items())),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
