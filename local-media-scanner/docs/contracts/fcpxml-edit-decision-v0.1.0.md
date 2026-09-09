# FCPXML edit decision v0.1.0

The model supplies only editorial choices. `travel-director export-fcpxml` owns media probing, range checks, track mapping, gain conversion, hard-linked asset packaging, FCPXML serialization and the validation receipt.

```json
{
  "schema_version": "0.1.0",
  "project_name": "12-second trial",
  "canvas": {
    "width": 1920,
    "height": 1080,
    "fps": 30,
    "duration_seconds": 12
  },
  "clips": [
    {
      "kind": "video",
      "source_path": "/absolute/path/clip.mov",
      "track": "main",
      "timeline_in": 0,
      "source_in": 1,
      "duration": 4,
      "gain": 0
    },
    {
      "kind": "music",
      "source_path": "/absolute/path/music.wav",
      "track": "music",
      "timeline_in": 0,
      "source_in": 0,
      "duration": 12,
      "gain": 0.35
    }
  ]
}
```

`kind` is `video`, `music` or `sfx`. Times are seconds. `gain` is a linear amplitude ratio: `0` is muted, `1` is unity gain. Clips may overlap only when their `track` values differ. The current exporter supports exactly one video track and any number of non-overlapping audio tracks. Every source and timeline range must fit its media or project duration.

Run:

```bash
uv run travel-director export-fcpxml --decision /absolute/path/decision.json --output /new/output/package
```

The output directory must not already exist. A successful run writes `project.fcpxml`, an `asset/` directory of hard links, and `receipt.json`. `fcpxml_generated` means program validation passed; it does not mean Jianying import or edit/save persistence was tested.
