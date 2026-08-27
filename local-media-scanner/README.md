# Travel Edit Engine V0.1 — Local Media Scanner

This directory contains a local-first technical validation project. It scans sparse frames from travel videos and never uploads source media.

Current status: the versioned Schema and CLI bootstrap are implemented. Metadata, sampling, CV, local model inference, evaluation, and benchmark evidence are added sequentially in `EXPERIMENTS.md`.

## Development setup

```bash
uv sync --extra dev
uv run pytest -v
uv run travel-scanner version
```

Python is pinned to 3.12 by `pyproject.toml`. FFmpeg and ffprobe must be available on `PATH`.

## Scope boundary

This V0.1 is a Scanner, not an AI Director. It does not generate music or SFX, call Dreamina, create timelines, or export editing projects.

