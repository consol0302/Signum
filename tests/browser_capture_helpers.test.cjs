"use strict";

const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");

const {
  CaptureError,
  assessCapture,
  captureStatistics,
  parseArgs,
  readActionSpec,
} = require("../examples/browser_capture.cjs");


function frame(sequence, timestamp, duration = 0.02) {
  return {
    sequence,
    timestamp_seconds: timestamp,
    capture_duration_seconds: duration,
  };
}


const stats = captureStatistics([
  frame(0, 0.0),
  frame(1, 0.08),
  frame(2, 0.16),
  frame(3, 0.24),
]);
assert.strictEqual(stats.frame_count, 4);
assert(Math.abs(stats.effective_average_fps - 12.5) < 1e-9);
assert(Math.abs(stats.interval_seconds.maximum - 0.08) < 1e-9);

const valid = assessCapture(
  stats,
  { minimumAverageFps: 10, maximumGapSeconds: 0.25 },
  [],
  [{ id: "click", required: true, status: "completed" }],
);
assert.strictEqual(valid.valid, true);

const invalid = assessCapture(
  captureStatistics([frame(0, 0), frame(1, 0.4)]),
  { minimumAverageFps: 10, maximumGapSeconds: 0.25 },
  [{ sequence: 1, error: "failed" }],
  [{ id: "click", required: true, status: "failed" }],
);
assert.strictEqual(invalid.valid, false);
assert(invalid.reasons.includes("one or more screenshot attempts failed"));
assert(invalid.required_action_failures.includes("click"));

assert.throws(
  () => parseArgs(["--url", "http://example.test"]),
  CaptureError,
);

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "signum-capture-test-"));
try {
  const actionPath = path.join(temporary, "actions.json");
  fs.writeFileSync(
    actionPath,
    JSON.stringify({
      schema_version: 1,
      case_id: "case-a",
      actions: [
        { id: "first", at_seconds: 1, type: "reload" },
        { id: "second", at_seconds: 2, type: "scroll", y: 100 },
      ],
    }),
  );
  const loaded = readActionSpec(actionPath, "case-a", 3);
  assert.strictEqual(loaded.payload.actions.length, 2);
  assert.strictEqual(loaded.sha256.length, 64);
  assert.throws(() => readActionSpec(actionPath, "wrong-case", 3), CaptureError);
} finally {
  fs.rmSync(temporary, { recursive: true, force: true });
}

process.stdout.write("browser capture helper tests passed\n");
