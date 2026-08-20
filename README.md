# Signum

Signum is an experiment in reducing how much video a multimodal model needs to inspect.

Most video is repetitive. Passing frames at a fixed interval is cheap, but it can miss short events. Passing every frame avoids that problem and creates a much larger one: unnecessary decoding, tokens, latency, and cost. Signum sits in front of that pipeline and uses ordinary image-processing signals to decide which moments are worth keeping.

The project is intentionally small at this stage. It runs on the CPU, does not call an AI model, and keeps enough source information to recover every selected frame later.

## What it does

```text
video
  -> low-resolution candidate frames
  -> frame difference, histogram change, and motion scores
  -> temporal spacing and duplicate suppression
  -> original-resolution frames + a timestamped timeline
```

The current release is a video-only sampler. Audio, streaming input, object detection, and model adapters are not implemented yet.

## Install

Signum requires Python 3.11 or newer.

```bash
git clone https://github.com/consol0302/Signum.git
cd Signum
python -m pip install -e .
```

OpenCV is the only substantial runtime dependency. No GPU or separate FFmpeg installation is required, although codec support still depends on the OpenCV build available on your system.

## Use

```bash
signum analyze input.mp4 --budget 32 --output output
```

The output directory looks like this:

```text
output/
  frames/
    frame_000000000_00000000.000s.jpg
    ...
  timeline.json
  report.json
```

`timeline.json` contains the selected frame index, timestamp, source interval, score, and signal values. `report.json` records the input metadata, sampler settings, candidate count, timing, and measured redundancy.

Useful options:

```text
--candidate-hz       candidate analysis rate (default: 4)
--analysis-width     maximum analysis width (default: 192)
--min-distance       preferred spacing between selections (default: 0.5s)
--coverage-fraction  budget reserved for timeline coverage (default: 0.25)
--strategy           hybrid, score_only, or uniform
```

## How selection works

Candidate frames are decoded sequentially and resized before analysis. Signum calculates three simple signals between consecutive candidates:

- mean pixel difference;
- grayscale histogram distance;
- the fraction of pixels that changed beyond a fixed threshold.

The signals are normalized within the video and combined into an importance score. The default `hybrid` selector reserves part of the frame budget for timeline coverage and uses the rest for high-scoring moments. Near-identical compact frame signatures are skipped when a distinct alternative exists.

There are no learned weights and no hidden model calls. Given the same video and settings, selection is deterministic.

## Benchmark

The repository includes a deterministic synthetic benchmark with seven cases: short motion in a static scene, hard cuts, slow change, a one-frame flash, continuous motion, repetitive motion, and camera-like panning.

Run it with:

```bash
python -m signum.benchmark --output benchmark-output
```

The first local run used six observations per six-second video:

| Method | Mean event recall | Temporal coverage | Redundancy |
| --- | ---: | ---: | ---: |
| Uniform | 0.429 | 1.000 | 0.500 |
| Score only | 0.857 | 0.571 | 0.429 |
| Hybrid | 0.857 | 0.643 | 0.429 |

These numbers are useful for checking the mechanics, not for claiming real-world performance. The one-frame flash fell between candidate samples and was missed by every strategy. Uniform sampling also requires no pixel analysis, so Signum has to earn its additional CPU cost by finding events that uniform sampling misses.

The benchmark setup and full notes are in [docs/BENCHMARK.md](docs/BENCHMARK.md) and [docs/RESULTS.md](docs/RESULTS.md).

## Development

Run the test suite:

```bash
python -m unittest discover -s tests -v
```

The project currently has five tests covering the CLI, budget handling, timestamps, duplicate handling, and deterministic selection.

The next useful step is not another scoring feature. It is a small collection of manually labeled real videos: screen recordings, fixed-camera footage, handheld video, and clips with subtle UI changes. That will show whether pixel-level novelty is actually a useful proxy for moments a downstream model needs to see.

## Project notes

- [Architecture](ARCHITECTURE.md)
- [MVP scope](docs/MVP.md)
- [Benchmark methodology](docs/BENCHMARK.md)
- [Initial results](docs/RESULTS.md)

Signum is currently at `0.0.1`. The API and output schema may still change while the core sampling approach is being validated.
