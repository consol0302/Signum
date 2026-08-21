# Timestamped browser capture

Claim 180 uses real browser timelines, not still images repeated for fixed
durations. The collector is isolated under `examples/`; Playwright and Chrome
are benchmark dependencies and do not enter Signum's deterministic core.

## Before held-out collection

Validate the collector only on development pages that are absent from the
preregistered suite. The tracked development fixture uses Selenium's separate
dynamic-elements page:

```powershell
$env:SIGNUM_NODE_MODULES = "C:\path\to\node_modules"
node examples/browser_capture.cjs `
  --url https://www.selenium.dev/selenium/web/dynamic.html `
  --case-id development-selenium-dynamic `
  --goal "Validate timestamped browser capture without touching held-out workflows." `
  --output benchmark-output/capture-development `
  --actions examples/development-capture-actions.json `
  --browser-executable "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --fps 15 `
  --duration 7 `
  --width 1280 `
  --height 720 `
  --minimum-average-fps 10 `
  --maximum-gap-seconds 0.25
```

`SIGNUM_NODE_MODULES` must contain Playwright. The output directory must be new
or empty; the collector never overwrites an earlier run.

The action file is data rather than executable JavaScript. It freezes the case
id, source URL, goal, duration, viewport, frame-rate limits, and typed
operations such as click, fill, key press, select, check, hover, scroll,
reload, and wait-for. Each locator, expected result, expected outcome, timeout,
and required/optional status is frozen in JSON. Before held-out capture, every
workflow action file must be committed and pushed. Do not repair locators after
viewing a held-out recording; a broken action remains a recorded failure or
the workflow becomes ineligible under the preregistered rules.

Claim 180's 30 action files are generated deterministically from the public
workflow plan and locked by a hash manifest:

```powershell
python examples/build_claim180_actions.py `
  --plan benchmark-protocol/claim180-plan.json `
  --output benchmark-protocol/actions `
  --manifest benchmark-protocol/claim180-actions-manifest.json `
  --collector-revision 0a51dce0a7d1768456065fbe4cc8c5189edbff34 `
  --check
```

The check fails if a generated file is missing, edited, added, or differs from
the generator; it also recomputes every file's byte count and SHA-256. The
revision identifies the exact development-validated collector. A later
collector change requires a new manifest and preregistration before collection.

## Recorded evidence

The capture directory contains:

```text
capture/
  actions.json
  capture.json
  frames/
    frame_000000.png
    ...
```

For every PNG, `capture.json` records the monotonic midpoint of the screenshot
request, wall-clock UTC time, capture duration, byte count, and SHA-256. It also
records action start/completion times and failures, navigation response,
viewport, Chrome version and executable hash, Playwright and Node versions,
frame-rate statistics, and every rejected policy condition. A navigation or
startup error creates `failure.json`; it is not represented as an empty or
zero-cost success.

The capture is valid only when:

- all screenshot attempts completed;
- effective average capture rate is at least 10fps;
- no adjacent retained frames are more than 250ms apart;
- at least two frames exist;
- every action marked `required` completed.

The 250ms ceiling is a separate dropout guard, not a redefinition of the 10fps
average. Both measurements are published. Events whose evidence overlaps any
invalid capture are ineligible; they are not moved to a convenient timestamp.

Independently recompute file hashes, dimensions, timing, action coverage, and
policy status:

```powershell
python examples/verify_browser_capture.py `
  benchmark-output/capture-development/capture.json `
  --case-id development-selenium-dynamic `
  --output benchmark-output/capture-development/verification.json
```

## Video encoding

The evaluator currently accepts constant-rate video. Encoding therefore uses
zero-order hold: every output timestamp receives the latest captured frame,
never a future frame. The sidecar maps each encoded frame back to its original
PNG sequence and timestamp.

```powershell
python examples/encode_timestamped_capture.py `
  benchmark-output/capture-development/capture.json `
  --output benchmark-output/capture-development/capture.avi `
  --fps 30
```

The encoder refuses invalid captures and existing outputs. It reopens the MJPEG
video, verifies its dimensions and frame count, hashes it, reports unused
source frames, and records maximum source-frame age. The original PNG timeline
remains the authoritative capture; the AVI is a reproducible evaluation view.

## Development measurement

The first complete development validation captured 105 lossless 1280×720
frames over seven seconds. Independent verification measured 14.997 average
fps, an 82.8ms maximum adjacent-frame gap, zero action failures, and no hash or
dimension failures. The 30fps encoding contained 210 frames, referenced all 105
source PNGs, and had an 82.3ms maximum source-frame age. This validates the
capture mechanics only. It contains no held-out workflow and contributes no
accuracy evidence.
