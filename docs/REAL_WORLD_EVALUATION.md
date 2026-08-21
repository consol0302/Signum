# Real-world perception evaluation

The labeled replay evaluator measures whether Signum catches events in real screen recordings and whether the saved evidence is useful to a computer-use controller. It deliberately separates measurements that code can make from judgments that require a person.

## 1. Prepare recordings and labels

Record complete, unedited sessions. Include quiet periods as well as dialogs, toasts, small text changes, progress completion, disabled controls, scrolling, animation, and short open-close transitions. Keep the original frame rate.

Copy `examples/real-evaluation.example.json`, place the recordings at the referenced paths, and edit the labels. The manifest has this shape:

```json
{
  "schema_version": 2,
  "cases": [
    {
      "id": "export-finished",
      "video": "recordings/export-finished.mp4",
      "goal": "Detect when the export finishes and identify the next safe action",
      "events": [
        {
          "id": "completion-toast",
          "start": 12.40,
          "end": 13.15,
          "tolerance": 0.10,
          "region": {
            "x": 0.72,
            "y": 0.78,
            "width": 0.25,
            "height": 0.16
          },
          "acceptable_states": ["export_complete", "completion_toast_visible"],
          "category": "popup_notification",
          "risk": "normal",
          "notes": "The completion message and file name must be legible."
        }
      ]
    }
  ]
}
```

Times are seconds on the source timeline. `tolerance` is only for annotation uncertainty; do not enlarge it to improve results. Regions use normalized full-frame coordinates. `acceptable_states` is optional and produces an exact normalized state diagnostic when Codex is enabled. The human semantic verdict remains authoritative because free-form state names are not a complete accuracy measure.

Schema version 2 requires every event to declare one of the benchmark categories and accepts a `risk` of `low`, `normal`, `high`, or `critical`. Version 1 remains readable as legacy input and assigns its events to `other`; new suites should use version 2.

`action_success` and `action_failure` events also require explicit verification inputs:

```json
{
  "id": "submit-no-op",
  "start": 8.2,
  "end": 8.5,
  "category": "action_failure",
  "risk": "high",
  "before_timestamp": 7.9,
  "after_timestamp": 8.3,
  "action": "clicked Submit",
  "expected_result": "a submission confirmation is visible"
}
```

The evaluator extracts the nearest source frames and calls the explicit before/after verification path for both methods. These forced checks are added equally and are reported separately from the passive observation budget. `action_success` expects `confirmed`; `action_failure` expects `not_confirmed`. Exact verification accuracy and automatic `confirmed`-on-failure counts are written when Codex is enabled.

Before spending Codex usage, audit the planned 60-event pilot coverage:

```bash
signum audit-manifest real-evaluation.json
```

The command reports counts and deficits for small UI, successful and failed actions, popups, loading, scrolling, cursor/focus-only changes, animation/game HUD, and transient events. Passing the audit means only that the labels meet the planned distribution. It does not establish that recordings are real, independent, or correctly labeled.

## 2. Run the detector comparison

Start without Codex:

```bash
signum evaluate real-evaluation.json --output evaluation-output
```

For every case, the evaluator first runs Signum and then gives uniform temporal sampling exactly the same number of observations. Uniform timestamps are the centers of equal-width timeline bins. The initial Signum context call is included in the budget and false-call count.

The automatic report includes:

- trigger recall over labeled events;
- observations and calls per minute;
- observations that match no labeled event and false calls per minute;
- the matched current or preserved-peak image timestamp;
- equal-budget Signum and uniform results.
- two-sided 95% Wilson confidence intervals for binomial rates;
- trigger and exact-state results grouped by event category.
- exact action-verification accuracy and automatic false confirmations when Codex is enabled.

The Wilson intervals describe per-event uncertainty. They do not make repeated events from the same workflow independent; publish the number of recordings and applications as well as the event count.

An event matches when a current or preserved-peak image timestamp falls inside its labeled interval plus tolerance. This measures temporal capture, not whether small text survived resizing.

## 3. Run the semantic comparison

Once the detector-only output looks valid, run both methods through the same Codex configuration:

```bash
signum evaluate real-evaluation.json \
  --output evaluation-with-codex \
  --with-codex \
  --model MODEL_NAME
```

This consumes Codex subscription usage. The output keeps the requested model and timeout, each method's images, structured observations, latency, runtime-reported tokens, missing usage records, transmitted JPEG bytes, and 32-pixel patch counts. Always specify the model when comparing separate runs.

## 4. Review visible and semantic success

Copy `review-template.json` and fill the three verdicts for every triggered row:

- `evidence_visible`: the labeled evidence is legible in at least one saved image without reopening the source video;
- `semantic_correct`: the structured observation describes the labeled state without a material omission or hallucination;
- `task_state_correct`: the verification, relevance, and recommended next action are safe for the stated goal.
- `false_confirmation`: for `action_failure` events only, the observation incorrectly claims that the failed or ineffective action succeeded.

Use `true` or `false`, not a confidence score. Untriggered events are automatic failures and need no manual verdict. For a publishable comparison, review rows in a method-blind order and have a second reviewer resolve disagreements.

Fill `reviewer`, `review_method`, and `reviewed_at_utc`. Use a truthful method such as `human_blind`, `human_nonblind`, or `ai_assisted_visual`; an AI-assisted provisional score is not a substitute for the independent human review required for a publishable claim.

Then score the completed file:

```bash
signum score evaluation-with-codex/evaluation.json \
  --reviews evaluation-with-codex/completed-review.json
```

`score.json` reports evidence recall, semantic accuracy, task-state accuracy, end-to-end success, and false-confirmation rate for both methods, including category breakdowns. A rate remains `null` until all required triggered rows have been reviewed. An action-failure event also remains incomplete until `false_confirmation` is filled. End-to-end success requires all three verdicts for an event; a detector miss always fails. The review template contains a hash of the exact evaluation run, and the scorer rejects a review copied from a different run.

## Output layout

```text
evaluation-output/
  evaluation.json
  review-template.json
  score.json
  cases/
    export-finished/
      signum/
        observations.json
        events/*.jpg
      uniform/
        observations.json
        events/*.jpg
```

Do not report a single success percentage without the manifest, model, gateway configuration, review coverage, and equal-budget baseline. Synthetic fixtures validate the evaluator mechanics but do not establish real-world accuracy.
