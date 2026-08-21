"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { performance } = require("perf_hooks");


class CaptureError extends Error {}


function parseArgs(argv) {
  const result = {
    fps: 15,
    durationSeconds: null,
    width: 1280,
    height: 720,
    headless: true,
    minimumAverageFps: 10,
    maximumGapSeconds: 0.25,
    screenshotTimeoutMs: 200,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const name = argv[index];
    if (name === "--headed") {
      result.headless = false;
      continue;
    }
    if (!name.startsWith("--")) {
      throw new CaptureError(`unexpected argument: ${name}`);
    }
    const value = argv[index + 1];
    if (value == null || value.startsWith("--")) {
      throw new CaptureError(`missing value for ${name}`);
    }
    index += 1;
    const key = {
      "--url": "url",
      "--case-id": "caseId",
      "--goal": "goal",
      "--output": "output",
      "--actions": "actions",
      "--browser-executable": "browserExecutable",
      "--fps": "fps",
      "--duration": "durationSeconds",
      "--width": "width",
      "--height": "height",
      "--minimum-average-fps": "minimumAverageFps",
      "--maximum-gap-seconds": "maximumGapSeconds",
      "--screenshot-timeout-ms": "screenshotTimeoutMs",
    }[name];
    if (!key) {
      throw new CaptureError(`unknown argument: ${name}`);
    }
    if (["fps", "durationSeconds", "width", "height", "minimumAverageFps", "maximumGapSeconds", "screenshotTimeoutMs"].includes(key)) {
      result[key] = Number(value);
    } else {
      result[key] = value;
    }
  }
  for (const key of ["url", "caseId", "goal", "output", "actions", "browserExecutable"]) {
    if (!result[key]) {
      throw new CaptureError(`--${key.replace(/[A-Z]/g, (match) => `-${match.toLowerCase()}`)} is required`);
    }
  }
  if (!result.url.startsWith("https://")) {
    throw new CaptureError("capture URL must use https");
  }
  for (const key of ["fps", "durationSeconds", "width", "height", "minimumAverageFps", "maximumGapSeconds", "screenshotTimeoutMs"]) {
    if (!Number.isFinite(result[key]) || result[key] <= 0) {
      throw new CaptureError(`${key} must be positive`);
    }
  }
  if (!Number.isInteger(result.width) || !Number.isInteger(result.height) || !Number.isInteger(result.screenshotTimeoutMs)) {
    throw new CaptureError("viewport dimensions and screenshot timeout must be integers");
  }
  return result;
}


function readActionSpec(filename, options) {
  const bytes = fs.readFileSync(filename);
  let payload;
  try {
    payload = JSON.parse(bytes.toString("utf8"));
  } catch (error) {
    throw new CaptureError(`action spec is invalid JSON: ${error.message}`);
  }
  if (!payload || payload.schema_version !== 1 || payload.case_id !== options.caseId) {
    throw new CaptureError("action spec schema_version or case_id does not match");
  }
  const frozenFields = [
    ["source_url", payload.source_url, options.url],
    ["goal", payload.goal, options.goal],
    ["duration_seconds", payload.duration_seconds, options.durationSeconds],
  ];
  const capturePolicy = payload.capture_policy;
  if (!capturePolicy || typeof capturePolicy !== "object") {
    throw new CaptureError("action spec must contain capture_policy");
  }
  frozenFields.push(
    ["capture_policy.requested_fps", capturePolicy.requested_fps, options.fps],
    ["capture_policy.width", capturePolicy.width, options.width],
    ["capture_policy.height", capturePolicy.height, options.height],
    ["capture_policy.minimum_average_fps", capturePolicy.minimum_average_fps, options.minimumAverageFps],
    ["capture_policy.maximum_gap_seconds", capturePolicy.maximum_gap_seconds, options.maximumGapSeconds],
    ["capture_policy.screenshot_timeout_ms", capturePolicy.screenshot_timeout_ms ?? 200, options.screenshotTimeoutMs],
  );
  for (const [name, frozen, requested] of frozenFields) {
    if (frozen !== requested) {
      throw new CaptureError(
        `action spec ${name} does not match the requested capture: ${JSON.stringify(frozen)} != ${JSON.stringify(requested)}`,
      );
    }
  }
  if (!Array.isArray(payload.actions)) {
    throw new CaptureError("action spec must contain an actions array");
  }
  let previous = -1;
  const ids = new Set();
  for (const action of payload.actions) {
    if (!action || typeof action !== "object") {
      throw new CaptureError("actions must be objects");
    }
    if (typeof action.id !== "string" || !action.id || ids.has(action.id)) {
      throw new CaptureError("action ids must be unique non-empty strings");
    }
    ids.add(action.id);
    if (!Number.isFinite(action.at_seconds) || action.at_seconds < previous) {
      throw new CaptureError("actions must use finite nondecreasing at_seconds");
    }
    if (action.at_seconds >= options.durationSeconds) {
      throw new CaptureError(`action ${action.id} is scheduled after capture duration`);
    }
    previous = action.at_seconds;
    if (typeof action.type !== "string" || !action.type) {
      throw new CaptureError(`action ${action.id} has no type`);
    }
    if (action.type === "navigate" && (
      typeof action.url !== "string" || !action.url.startsWith("https://")
    )) {
      throw new CaptureError(`navigate action ${action.id} must use an https URL`);
    }
    if (action.required != null && typeof action.required !== "boolean") {
      throw new CaptureError(`action ${action.id} required must be boolean`);
    }
  }
  return {
    payload,
    bytes,
    sha256: sha256(bytes),
  };
}


function captureStatistics(frames) {
  const timestamps = frames.map((frame) => frame.timestamp_seconds);
  const intervals = [];
  for (let index = 1; index < timestamps.length; index += 1) {
    intervals.push(timestamps[index] - timestamps[index - 1]);
  }
  const elapsed = timestamps.length > 1 ? timestamps.at(-1) - timestamps[0] : 0;
  const sorted = [...intervals].sort((left, right) => left - right);
  const quantile = (probability) => {
    if (!sorted.length) return null;
    const position = (sorted.length - 1) * probability;
    const lower = Math.floor(position);
    const upper = Math.ceil(position);
    if (lower === upper) return sorted[lower];
    const weight = position - lower;
    return sorted[lower] * (1 - weight) + sorted[upper] * weight;
  };
  return {
    frame_count: frames.length,
    elapsed_seconds: elapsed,
    effective_average_fps: elapsed > 0 ? (frames.length - 1) / elapsed : null,
    interval_seconds: {
      minimum: sorted.length ? sorted[0] : null,
      median: quantile(0.5),
      p95: quantile(0.95),
      maximum: sorted.length ? sorted.at(-1) : null,
    },
    capture_duration_seconds: {
      median: median(frames.map((frame) => frame.capture_duration_seconds)),
      maximum: frames.length
        ? Math.max(...frames.map((frame) => frame.capture_duration_seconds))
        : null,
    },
    timestamp_range_seconds: {
      first: frames.length ? timestamps[0] : null,
      last: frames.length ? timestamps.at(-1) : null,
    },
  };
}


function assessCapture(stats, options, frameErrors, actionRows) {
  const reasons = [];
  const warnings = [];
  if (frameErrors.length) {
    warnings.push("one or more screenshot attempts failed but all temporal validity bounds are assessed independently");
  }
  if ((stats.effective_average_fps ?? 0) < options.minimumAverageFps) {
    reasons.push("effective average frame rate is below the frozen minimum");
  }
  if ((stats.interval_seconds.maximum ?? Infinity) > options.maximumGapSeconds) {
    reasons.push("maximum frame gap exceeds the frozen capture limit");
  }
  if (stats.frame_count < 2) reasons.push("capture contains fewer than two frames");
  const firstTimestamp = stats.timestamp_range_seconds?.first;
  const lastTimestamp = stats.timestamp_range_seconds?.last;
  if (Number.isFinite(options.durationSeconds) && Number.isFinite(firstTimestamp)) {
    if (firstTimestamp > options.maximumGapSeconds) {
      reasons.push("capture starts after the frozen coverage limit");
    }
    if (options.durationSeconds - lastTimestamp > options.maximumGapSeconds) {
      reasons.push("capture ends before the frozen coverage limit");
    }
  }
  const requiredFailures = actionRows.filter(
    (row) => row.required && row.status !== "completed",
  );
  if (requiredFailures.length) reasons.push("one or more required actions failed");
  return {
    valid: reasons.length === 0,
    reasons,
    warnings,
    required_action_failures: requiredFailures.map((row) => row.id),
  };
}


function sha256(data) {
  return crypto.createHash("sha256").update(data).digest("hex");
}


function sha256File(filename) {
  const digest = crypto.createHash("sha256");
  const descriptor = fs.openSync(filename, "r");
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  try {
    while (true) {
      const count = fs.readSync(descriptor, buffer, 0, buffer.length, null);
      if (!count) break;
      digest.update(buffer.subarray(0, count));
    }
  } finally {
    fs.closeSync(descriptor);
  }
  return digest.digest("hex");
}


function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const midpoint = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[midpoint]
    : (sorted[midpoint - 1] + sorted[midpoint]) / 2;
}


function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, Math.max(0, milliseconds)));
}


function loadPlaywright() {
  const candidates = [];
  if (process.env.SIGNUM_NODE_MODULES) {
    candidates.push(path.join(process.env.SIGNUM_NODE_MODULES, "playwright"));
  }
  candidates.push("playwright");
  const failures = [];
  for (const candidate of candidates) {
    try {
      return require(candidate);
    } catch (error) {
      failures.push(`${candidate}: ${error.message}`);
    }
  }
  throw new CaptureError(
    "Playwright is unavailable. Set SIGNUM_NODE_MODULES to a node_modules directory. " +
      failures.join(" | "),
  );
}


function prepareOutput(output) {
  const destination = path.resolve(output);
  if (fs.existsSync(destination) && fs.readdirSync(destination).length) {
    throw new CaptureError(`refusing to overwrite non-empty output: ${destination}`);
  }
  fs.mkdirSync(path.join(destination, "frames"), { recursive: true });
  return destination;
}


function locatorFor(page, descriptor) {
  if (!descriptor || typeof descriptor !== "object") {
    throw new CaptureError("action requires a locator object");
  }
  const scope = descriptor.frame ? page.frameLocator(descriptor.frame) : page;
  switch (descriptor.by) {
    case "css":
      return scope.locator(descriptor.value);
    case "label":
      return scope.getByLabel(descriptor.value, { exact: Boolean(descriptor.exact) });
    case "placeholder":
      return scope.getByPlaceholder(descriptor.value, { exact: Boolean(descriptor.exact) });
    case "role":
      return scope.getByRole(descriptor.role, {
        name: descriptor.name,
        exact: Boolean(descriptor.exact),
      });
    case "text":
      return scope.getByText(descriptor.value, { exact: Boolean(descriptor.exact) });
    default:
      throw new CaptureError(`unknown locator type: ${descriptor.by}`);
  }
}


async function executeAction(page, action) {
  const timeout = Number(action.timeout_ms ?? 3000);
  switch (action.type) {
    case "click":
      return locatorFor(page, action.locator).click({ timeout, force: Boolean(action.force) });
    case "double_click":
      return locatorFor(page, action.locator).dblclick({ timeout, force: Boolean(action.force) });
    case "fill":
      return locatorFor(page, action.locator).fill(String(action.value ?? ""), { timeout });
    case "press":
      return locatorFor(page, action.locator).press(String(action.key), { timeout });
    case "select":
      return locatorFor(page, action.locator).selectOption(action.value, { timeout });
    case "check":
      return locatorFor(page, action.locator).check({ timeout, force: Boolean(action.force) });
    case "uncheck":
      return locatorFor(page, action.locator).uncheck({ timeout, force: Boolean(action.force) });
    case "hover":
      return locatorFor(page, action.locator).hover({ timeout, force: Boolean(action.force) });
    case "scroll":
      return page.evaluate(
        ({ x, y }) => window.scrollBy(Number(x || 0), Number(y || 0)),
        { x: action.x, y: action.y },
      );
    case "reload":
      return page.reload({ waitUntil: "domcontentloaded", timeout });
    case "navigate":
      return page.goto(action.url, { waitUntil: "domcontentloaded", timeout });
    case "wait_for":
      return locatorFor(page, action.locator).waitFor({
        state: action.state || "visible",
        timeout,
      });
    default:
      throw new CaptureError(`unknown action type: ${action.type}`);
  }
}


async function captureFrames(page, destination, options, monotonicStart, wallStart) {
  const frames = [];
  const errors = [];
  const period = 1000 / options.fps;
  let sequence = 0;
  while ((performance.now() - monotonicStart) / 1000 < options.durationSeconds) {
    const scheduled = monotonicStart + sequence * period;
    await sleep(scheduled - performance.now());
    if ((performance.now() - monotonicStart) / 1000 >= options.durationSeconds) break;
    const requestStart = performance.now();
    try {
      const data = await page.screenshot({
        type: "png",
        animations: "allow",
        timeout: options.screenshotTimeoutMs,
      });
      const completed = performance.now();
      const midpoint = (requestStart + completed) / 2;
      const name = `frame_${String(sequence).padStart(6, "0")}.png`;
      fs.writeFileSync(path.join(destination, "frames", name), data);
      frames.push({
        sequence,
        file: `frames/${name}`,
        timestamp_seconds: (midpoint - monotonicStart) / 1000,
        wall_timestamp_utc: new Date(
          wallStart.getTime() + (midpoint - monotonicStart),
        ).toISOString(),
        capture_duration_seconds: (completed - requestStart) / 1000,
        encoded_bytes: data.length,
        sha256: sha256(data),
      });
    } catch (error) {
      errors.push({
        sequence,
        requested_at_seconds: (requestStart - monotonicStart) / 1000,
        error: String(error.message || error),
      });
    }
    sequence += 1;
  }
  return { frames, errors };
}


async function executeActions(page, actions, monotonicStart, wallStart) {
  const rows = [];
  for (const action of actions) {
    await sleep(monotonicStart + action.at_seconds * 1000 - performance.now());
    const started = performance.now();
    const row = {
      id: action.id,
      type: action.type,
      required: action.required !== false,
      scheduled_at_seconds: action.at_seconds,
      started_at_seconds: (started - monotonicStart) / 1000,
      started_at_utc: new Date(
        wallStart.getTime() + (started - monotonicStart),
      ).toISOString(),
      expected_result: action.expected_result ?? null,
      expected_outcome: action.expected_outcome ?? null,
    };
    try {
      await executeAction(page, action);
      row.status = "completed";
    } catch (error) {
      row.status = "failed";
      row.failure_type = error.constructor?.name || "Error";
      row.failure = String(error.message || error);
    }
    const completed = performance.now();
    row.completed_at_seconds = (completed - monotonicStart) / 1000;
    row.duration_seconds = (completed - started) / 1000;
    rows.push(row);
  }
  return rows;
}


async function main(argv) {
  const options = parseArgs(argv);
  const actionSpec = readActionSpec(
    path.resolve(options.actions),
    options,
  );
  const destination = prepareOutput(options.output);
  const inProgressPath = path.join(destination, ".capture-in-progress.json");
  fs.writeFileSync(
    inProgressPath,
    JSON.stringify(
      {
        schema_version: 1,
        started_at_utc: new Date().toISOString(),
        process_id: process.pid,
      },
      null,
      2,
    ) + "\n",
  );
  const preservedActionSpec = path.join(destination, "actions.json");
  fs.writeFileSync(preservedActionSpec, actionSpec.bytes);
  if (!fs.existsSync(options.browserExecutable)) {
    throw new CaptureError(`browser executable does not exist: ${options.browserExecutable}`);
  }
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch({
    executablePath: path.resolve(options.browserExecutable),
    headless: options.headless,
  });
  let report;
  try {
    const context = await browser.newContext({
      viewport: { width: options.width, height: options.height },
      deviceScaleFactor: 1,
      locale: "en-US",
      colorScheme: "light",
      reducedMotion: "no-preference",
    });
    const page = await context.newPage();
    const navigationStarted = performance.now();
    const navigationResponse = await page.goto(options.url, {
      waitUntil: "domcontentloaded",
      timeout: 30000,
    });
    const navigationSeconds = (performance.now() - navigationStarted) / 1000;
    const wallStart = new Date();
    const monotonicStart = performance.now() + 250;
    const capturePromise = captureFrames(
      page,
      destination,
      options,
      monotonicStart,
      wallStart,
    );
    const actionsPromise = executeActions(
      page,
      actionSpec.payload.actions,
      monotonicStart,
      wallStart,
    );
    const [{ frames, errors }, actionRows] = await Promise.all([
      capturePromise,
      actionsPromise,
    ]);
    const stats = captureStatistics(frames);
    const assessment = assessCapture(stats, options, errors, actionRows);
    report = {
      schema_version: 1,
      status: assessment.valid ? "completed" : "completed_invalid",
      valid: assessment.valid,
      invalid_reasons: assessment.reasons,
      warnings: assessment.warnings,
      case_id: options.caseId,
      goal: options.goal,
      source_url: options.url,
      captured_at_utc: wallStart.toISOString(),
      viewport: { width: options.width, height: options.height, device_scale_factor: 1 },
      capture_policy: {
        requested_fps: options.fps,
        minimum_average_fps: options.minimumAverageFps,
        maximum_gap_seconds: options.maximumGapSeconds,
        screenshot_timeout_ms: options.screenshotTimeoutMs,
        duration_seconds: options.durationSeconds,
      },
      navigation_seconds: navigationSeconds,
      navigation: {
        requested_url: options.url,
        final_url: page.url(),
        response_url: navigationResponse?.url() ?? null,
        response_status: navigationResponse?.status() ?? null,
      },
      action_spec: {
        path: "actions.json",
        source_path: path.resolve(options.actions),
        sha256: actionSpec.sha256,
        bytes: actionSpec.bytes.length,
      },
      browser: {
        executable: path.resolve(options.browserExecutable),
        executable_sha256: sha256File(path.resolve(options.browserExecutable)),
        executable_bytes: fs.statSync(path.resolve(options.browserExecutable)).size,
        version: await browser.version(),
        playwright_version: require(loadPlaywrightPackagePath()).version,
        node_version: process.version,
        platform: process.platform,
        architecture: process.arch,
        headless: options.headless,
      },
      frame_statistics: stats,
      frame_errors: errors,
      required_action_failures: assessment.required_action_failures,
      actions: actionRows,
      frames,
    };
    await context.close();
  } finally {
    await browser.close();
  }
  const reportPath = path.join(destination, "capture.json");
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n");
  fs.unlinkSync(inProgressPath);
  const summary = {
    status: report.status,
    valid: report.valid,
    case_id: report.case_id,
    frames: report.frame_statistics.frame_count,
    effective_average_fps: report.frame_statistics.effective_average_fps,
    maximum_gap_seconds: report.frame_statistics.interval_seconds.maximum,
    screenshot_errors: report.frame_errors.length,
    action_failures: report.actions.filter((row) => row.status !== "completed").length,
    output: reportPath,
  };
  process.stdout.write(JSON.stringify(summary) + "\n");
  if (!report.valid) process.exitCode = 1;
}


function loadPlaywrightPackagePath() {
  if (process.env.SIGNUM_NODE_MODULES) {
    return path.join(process.env.SIGNUM_NODE_MODULES, "playwright", "package.json");
  }
  return require.resolve("playwright/package.json");
}


module.exports = {
  CaptureError,
  assessCapture,
  captureStatistics,
  parseArgs,
  readActionSpec,
};


if (require.main === module) {
  main(process.argv.slice(2)).catch((error) => {
    const outputIndex = process.argv.indexOf("--output");
    if (outputIndex >= 0 && process.argv[outputIndex + 1]) {
      const failureRoot = path.resolve(process.argv[outputIndex + 1]);
      const capturePath = path.join(failureRoot, "capture.json");
      const failurePath = path.join(failureRoot, "failure.json");
      const inProgressPath = path.join(failureRoot, ".capture-in-progress.json");
      if (
        fs.existsSync(failureRoot) &&
        fs.existsSync(inProgressPath) &&
        !fs.existsSync(capturePath) &&
        !fs.existsSync(failurePath)
      ) {
        fs.writeFileSync(
          failurePath,
          JSON.stringify(
            {
              schema_version: 1,
              status: "failed",
              failed_at_utc: new Date().toISOString(),
              failure_type: error.constructor?.name || "Error",
              failure: String(error.message || error),
              argv: process.argv.slice(2),
            },
            null,
            2,
          ) + "\n",
        );
      }
    }
    process.stderr.write(`signum capture: ${error.message || error}\n`);
    process.exitCode = 2;
  });
}
