from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .gateway import (
    GatewayConfig,
    GatewayObservation,
    PerceptionGateway,
    SemanticInterpreter,
)
from .video import iter_frames, probe_video


def observe_video(
    source: Path | str,
    output_dir: Path | str,
    *,
    goal: str,
    config: GatewayConfig | None = None,
    interpreter: SemanticInterpreter | None = None,
) -> dict[str, Any]:
    if not goal.strip():
        raise ValueError("goal cannot be empty")
    gateway_config = config or GatewayConfig()
    gateway_config.validate()
    metadata = probe_video(Path(source))
    output = Path(output_dir)
    images_dir = output / "events"
    images_dir.mkdir(parents=True, exist_ok=True)
    observations: list[dict[str, Any]] = []
    started = time.perf_counter()

    gateway = PerceptionGateway(gateway_config, interpreter=interpreter)
    last_frame = None
    last_frame_index: int | None = None
    for frame_index, frame in iter_frames(metadata):
        last_frame = frame
        last_frame_index = frame_index
        observation = gateway.observe_frame(
            frame,
            frame_index / metadata.fps,
            goal=goal,
            frame_index=frame_index,
        )
        if observation is None:
            continue
        observations.append(_serialize_observation(observation, images_dir, output))

    if last_frame is not None and last_frame_index is not None:
        final_observation = gateway.flush(
            last_frame,
            last_frame_index / metadata.fps,
            goal=goal,
            frame_index=last_frame_index,
        )
        if final_observation is not None:
            observations.append(
                _serialize_observation(final_observation, images_dir, output)
            )

    payload = {
        "schema_version": 1,
        "source": metadata.to_dict(),
        "goal": goal,
        "config": gateway_config.to_dict(),
        "stats": {
            **gateway.stats.to_dict(),
            "processing_seconds": time.perf_counter() - started,
        },
        "observations": observations,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "observations.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return payload


def _serialize_observation(
    observation: GatewayObservation, images_dir: Path, output: Path
) -> dict[str, Any]:
    serialized = observation.to_dict()
    image_paths: list[str] = []
    for image in observation.event.images:
        name = (
            f"event_{observation.event.sequence:05d}_"
            f"{observation.event.timestamp:012.3f}s_{image.role}.jpg"
        )
        path = images_dir / name
        path.write_bytes(image.jpeg)
        image_paths.append(path.relative_to(output).as_posix())
    serialized["event"]["image_files"] = image_paths  # type: ignore[index]
    return serialized
