# Validation samples (historical / non-portable)

These directories hold **historical local-run artifacts** used while developing shot-review, shot-group, music-adaptation, sound-design, and audiovisual-review tooling.

## Honesty rules

- Paths inside JSON/FCPXML/logs were scrubbed of developer machine absolute paths for the public repo. They are **not** portable evidence that media still exists on disk.
- Receipt hashes and absolute `file://` media references may no longer match a real checkout. Treat packages as **shape/examples**, not reproducible acceptance proofs.
- **`audiovisual-review-20260910/audiovisual_review.json` is DEMO_INVALID.** It must not be cited as completed subjective audiovisual acceptance. Program tests and Jianying import success never equal aesthetic approval. See that file’s `overall_verdict: needs_revision` and recommendations.

## Regenerating

Re-run the relevant CLI flows on a machine with local footage and `TRAVEL_DIRECTOR_AUDIO_ROOT` set; do not revive scrubbed paths.
