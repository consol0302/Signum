from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from measure_codex_stratified import (
    build_prompt,
    choose_samples,
    load_observation,
    output_schema,
)


ENDPOINTS = {
    "openai": "https://api.openai.com/v1/responses",
    "anthropic": "https://api.anthropic.com/v1/messages",
}
KEY_ENVIRONMENTS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the same stratified saved-evidence batch through an external API."
    )
    parser.add_argument("--provider", choices=tuple(ENDPOINTS), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--method", choices=("signum", "uniform"), default="signum")
    parser.add_argument("--per-category", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--endpoint")
    return parser.parse_args()


def collect(args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[tuple[str, str]], list[Path]]:
    evaluation_path = args.evaluation.resolve()
    root = evaluation_path.parent
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    samples = choose_samples(evaluation, args.method, args.per_category)
    attachments: list[tuple[str, str]] = []
    images: list[Path] = []
    for sample in samples:
        observation = load_observation(root, sample, args.method)
        sample["observation"] = observation
        event = observation["event"]
        observation_path = root / sample["case"]["methods"][args.method]["observation_file"]
        for image, relative in zip(event["images"], event["image_files"], strict=True):
            image_path = observation_path.parent / relative
            if not image_path.is_file():
                raise RuntimeError(f"missing saved evidence: {image_path}")
            attachments.append((sample["sample_id"], image["role"]))
            images.append(image_path)
    return samples, attachments, images


def data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def openai_request(model: str, prompt: str, schema: dict[str, Any], images: list[Path]) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    content.extend(
        {"type": "input_image", "image_url": data_url(path), "detail": "auto"}
        for path in images
    )
    return {
        "model": model,
        "store": False,
        "input": [{"role": "user", "content": content}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "signum_perception_batch",
                "strict": True,
                "schema": schema,
            }
        },
    }


def anthropic_request(model: str, prompt: str, schema: dict[str, Any], images: list[Path]) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    for path in images:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                },
            }
        )
    content.append({"type": "text", "text": prompt})
    return {
        "model": model,
        "max_tokens": 8192,
        "messages": [{"role": "user", "content": content}],
        "output_config": {
            "format": {"type": "json_schema", "schema": schema}
        },
    }


def request_json(
    provider: str,
    endpoint: str,
    api_key: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    headers = {"content-type": "application/json"}
    if provider == "openai":
        headers["authorization"] = f"Bearer {api_key}"
    else:
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{provider} returned HTTP {error.code}: {detail[:800]}") from error


def parse_output(provider: str, response: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if provider == "openai":
        text = response.get("output_text")
        if not isinstance(text, str):
            for item in response.get("output", []):
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        text = content.get("text")
                        break
        usage = response.get("usage", {})
        normalized_usage = {
            "input_tokens": usage.get("input_tokens"),
            "cached_input_tokens": usage.get("input_tokens_details", {}).get("cached_tokens"),
            "output_tokens": usage.get("output_tokens"),
        }
    else:
        blocks = response.get("content", [])
        text = next(
            (block.get("text") for block in blocks if block.get("type") == "text"),
            None,
        )
        usage = response.get("usage", {})
        normalized_usage = {
            "input_tokens": usage.get("input_tokens"),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
            "output_tokens": usage.get("output_tokens"),
        }
    if not isinstance(text, str):
        raise RuntimeError(f"{provider} response did not contain structured text")
    return json.loads(text), normalized_usage


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    key_environment = KEY_ENVIRONMENTS[args.provider]
    api_key = os.environ.get(key_environment)
    status_path = args.output / "status.json"
    if not api_key:
        status = {
            "schema_version": 1,
            "status": "not_run",
            "reason": f"{key_environment} is not set",
            "provider": args.provider,
            "model": args.model,
            "evaluation": str(args.evaluation.resolve()),
            "method": args.method,
            "per_category": args.per_category,
        }
        status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(status, sort_keys=True))
        return

    samples, attachments, images = collect(args)
    prompt = build_prompt(samples, attachments)
    schema = output_schema(len(samples))
    payload = (
        openai_request(args.model, prompt, schema, images)
        if args.provider == "openai"
        else anthropic_request(args.model, prompt, schema, images)
    )
    started = time.perf_counter()
    response = request_json(
        args.provider,
        args.endpoint or ENDPOINTS[args.provider],
        api_key,
        payload,
        args.timeout,
    )
    output, usage = parse_output(args.provider, response)
    observations = output.get("observations")
    expected = [sample["sample_id"] for sample in samples]
    actual = [row.get("sample_id") for row in observations or []]
    if actual != expected:
        raise RuntimeError("provider did not preserve the selected sample order")
    report = {
        "schema_version": 1,
        "status": "completed",
        "provider": args.provider,
        "model": args.model,
        "evaluation": str(args.evaluation.resolve()),
        "method": args.method,
        "events": len(samples),
        "latency_seconds": time.perf_counter() - started,
        "usage": usage,
        "observations": observations,
    }
    status_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "provider", "model", "events", "latency_seconds", "usage")}, sort_keys=True))


if __name__ == "__main__":
    main()
