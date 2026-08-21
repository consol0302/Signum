# Real-world perception evaluation

The labeled replay evaluator measures whether Signum catches events in real screen recordings and whether the saved evidence is useful to a computer-use controller. It deliberately separates measurements that code can make from judgments that require a person.

## 1. Prepare recordings and labels

Record complete, unedited sessions. Include quiet periods as well as dialogs, toasts, small text changes, progress completion, disabled controls, scrolling, animation, and short open-close transitions. Keep the original frame rate.

Copy `examples/real-evaluation.example.json`, place the recordings at the referenced paths, and edit the labels. The manifest has this shape:

```json
{
  "schema_version": 1,
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
          "notes": "The completion message and file name must be legible."
        }
      ]
    }
  ]
}
```

Times are seconds on the source timeline. `tolerance` is only for annotation uncertainty; do not enlarge it to improve results. Regions use normalized full-frame coordinates. `acceptable_states` is optional and produces an exact normalized state diagnostic when Codex is enabled. The human semantic verdict remains authoritative because free-form state names are not a complete accuracy measure.

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

Use `true` or `false`, not a confidence score. Untriggered events are automatic failures and need no manual verdict. For a publishable comparison, review rows in a method-blind order and have a second reviewer resolve disagreements.

Then score the completed file:

```bash
signum score evaluation-with-codex/evaluation.json \
  --reviews evaluation-with-codex/completed-review.json
```

`score.json` reports evidence recall, semantic accuracy, task-state accuracy, and end-to-end success for both methods. A rate remains `null` until all required triggered rows have been reviewed. End-to-end success requires all three verdicts for an event; a detector miss always fails. The review template contains a hash of the exact evaluation run, and the scorer rejects a review copied from a different run.

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
