# Pilot 60 perception suite

The first real-world suite is a failure-discovery pilot, not a performance claim. It contains 60 independently labeled UI events from complete recordings with quiet time preserved.

## Required distribution

| Category | Events | Main failure under test |
| --- | ---: | --- |
| `small_ui` | 10 | Small text, icons, thin borders, and clipped crops |
| `action_success` | 8 | A completed action is visibly and safely confirmed |
| `action_failure` | 8 | No-op, wrong target, or rejected action is not called successful |
| `popup_notification` | 6 | Dialogs, toasts, warnings, and short-lived messages |
| `loading_completion` | 6 | Progress, disabled controls, and completion transitions |
| `scroll_navigation` | 5 | Large motion without losing the relevant destination state |
| `cursor_hover_focus` | 5 | Cursor, caret, hover, and focus-only changes do not cause noise |
| `animation_game_hud` | 6 | Repetitive motion and changing HUD values |
| `transient_event` | 6 | Brief events between ordinary candidate times |

Run `signum audit-manifest MANIFEST` to measure the manifest against this distribution. Extra events are allowed. `other` events do not satisfy a target category. A complete profile also requires 60 independent `source_transition_id` values and enough events with `real_world_eligible: true`; raw label totals alone are not sufficient.

## Collection rules

- Keep original frame rate and source timestamps.
- Keep quiet periods before and after an event.
- Do not crop or edit recordings to make detection easier.
- Use normalized regions only when the meaningful evidence has a defensible boundary.
- Use `tolerance` only for annotation uncertainty.
- Give every event an expected semantic state when a stable state name is meaningful.
- Label failed actions even when no pixels change. Action categories must include `before_timestamp`, `after_timestamp`, `action`, and `expected_result`; the evaluator forces the before/after check instead of relying on passive change detection.
- Do not duplicate one transition under several ids to fill a quota.
- Keep generated or synthetic cases outside the real-world total.
- Give every event a stable `source_transition_id` when two semantic labels can refer to the same captured transition. The audit reports every reused id.
- Set `real_world_eligible` to `false` for constructed no-ops, synthetic events, or evidence that cannot be traced to a distinct real interaction.

## Review rules

Reviewers see only the saved evidence and structured observation. For every triggered event they judge evidence visibility, semantic correctness, and task-state correctness. For `action_failure`, they additionally mark whether the system falsely claimed success.

Report category counts, review coverage, 95% confidence intervals, model version, gateway configuration, observation budget, token usage, and all excluded or failed cases. A complete 60-event pilot is still too small for a broad superiority claim; its purpose is to identify repeatable failures before the larger held-out suite.

The first local 60-label run, its failed audit, detector result, Codex transport measurements, and remaining blockers are recorded in [Pilot 60 local measurement](PILOT60_RESULTS.md).
