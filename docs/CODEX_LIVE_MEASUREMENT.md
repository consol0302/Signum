# Measuring live Codex perception

This probe checks the complete Signum perception path without giving Signum control of the browser. A controller captures real browser frames, Signum detects and prepares relevant evidence, and an authenticated Codex CLI describes the selected events as structured observations.

The probe is intentionally small. It proves that the components work together and exposes latency and token costs. It is not a substitute for the labeled recording suite described in [Real-world perception evaluation](REAL_WORLD_EVALUATION.md).

## Test page and captures

The first probe used Selenium's public dynamic-elements page:

```text
https://www.selenium.dev/selenium/web/dynamic.html
```

Use a fixed 1280×720 browser viewport and save three lossless screenshots with identical dimensions:

1. `initial.png`: the page before either button is pressed;
2. `box-settled.png`: the stable page after **Add a box!** is pressed;
3. `input-settled.png`: the stable page after **Reveal a new input!** is pressed.

Keep the captures outside the source tree. Browser output and Codex result files belong in an ignored output directory.

Convert those captures into the first labeled replay and audit its coverage:

```powershell
python examples/build_live_web_pilot.py `
  --frames-dir benchmark-output/live-web `
  --output benchmark-output/live-web-pilot

signum audit-manifest benchmark-output/live-web-pilot/manifest.json
signum evaluate benchmark-output/live-web-pilot/manifest.json `
  --output benchmark-output/live-web-pilot-evaluation `
  --min-event-interval 0
```

The builder repeats each captured state for two seconds. It is a deterministic replay of real browser pixels, not an original-timing recording. Its generated manifest records the source frames and this limitation.

## Run the replay

Install the project and confirm that Codex uses the intended ChatGPT account:

```powershell
python -m pip install -e .
codex login status
```

Then run the tracked example with an explicit model:

```powershell
python examples/codex_live_web_probe.py `
  --frames-dir C:\path\to\captured-frames `
  --output live-web-output `
  --model gpt-5.6-sol
```

On Windows, Signum prefers `%APPDATA%\npm\codex.cmd` when the bare `codex` command would otherwise resolve to the protected desktop-app executable. Use `--codex-command` when more than one CLI installation exists or when running from a restricted host.

The example submits five frames without waiting for Codex. It then requests a focused crop around the small input and creates an explicit action-verification event using the before and after frames. The semantic worker processes these five observations in order:

| Sequence | Expected visible state |
| --- | --- |
| 0 | Neither the red box nor the new input is visible. |
| 1 | The red box is visible; the new input is absent. |
| 2 | Both the red box and the new input are visible. |
| 3 | The requested detail crop contains the new input. |
| 4 | The post-action image visibly confirms that the new input appeared. |

`measurement.json` records every prepared image, event reason, crop, structured Codex result, runtime-reported token count, semantic latency, detector time, queue depth, and failure. The `events/` directory contains the exact JPEG evidence sent for review.

## Review rule

Do not score free-form wording by string equality. Review each observation against only the saved event images and mark it correct when all of these conditions hold:

- the visible state is materially correct;
- absent elements are not invented;
- `verification` is appropriate for the event type;
- the recommendation is safe for the stated goal;
- uncertainty is used when the evidence is insufficient.

Add a negative action-verification case by supplying the same screenshot as both the before and after frame while claiming that the input should appear. The correct result is `not_confirmed`; `confirmed` is a critical false success.

## First measured result

The 2026-08-21 run used `codex-cli 0.148.0`, ChatGPT subscription authentication, and `gpt-5.6-sol`. Five positive observations and one separate failed-action observation all matched the visible labels. No interpretation failed and no queued event was dropped.

Across the six Codex calls, reported usage totaled 90,693 input tokens and 795 output tokens. Mean semantic latency was about 7.05 seconds, with observed calls ranging from 6.12 to 7.93 seconds. In the five-event streaming replay, maximum synchronous frame submission was 15.81 ms and the maximum semantic queue depth was four.

These six judgments came from one simple page. Report them as an end-to-end smoke result, not as a general success rate. The next suite must add repeated runs, cursor and focus-only changes, failed clicks, popups, scrolling, short-lived notifications, animations, loading states, and small text changes.

## Cost finding

The five-event replay transmitted only 37,894 bytes of JPEG data, but Codex reported 75,795 total tokens. Each event used a new ephemeral `codex exec` process, so agent context dominated the small image payload and cached input remained zero.

This result justifies a controlled comparison with a persistent Codex session or carefully batched events. Keep the detector, images, labels, model, and observation count fixed when testing either option. A cheaper transport is only an improvement if semantic accuracy and action-verification safety do not regress.
