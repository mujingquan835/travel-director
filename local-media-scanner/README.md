# Travel Edit Engine V0.1 — Local Media Scanner

This directory contains a local-first technical validation project. It scans sparse frames from travel videos and never uploads source media.

Current status: the Scanner V0.1 feasibility phase is concluded. The local pipeline is viable with strict field-level constraints; most semantic fields are not reliable enough to become deterministic facts. See `BENCHMARK.md` for the measured evidence, extrapolated 100-video range, acceptance matrix, and minimum next step.

## Development setup

```bash
uv sync --extra dev
uv run pytest -v
uv run travel-scanner version
```

Python is pinned to 3.12 by `pyproject.toml`. FFmpeg and ffprobe must be available on `PATH`.

## Scope boundary

This V0.1 is a Scanner, not an AI Director. It does not generate music or SFX, call Dreamina, create timelines, or export editing projects.
