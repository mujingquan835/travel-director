# Ground Truth Annotation Guide

This Ground Truth is frozen before detector or vision-model inference. Labels are based on the source clip and model-free sparse review frames only.

## Label rules

- `people_present`: visible human pixels count, including background crowds. Use `null` when darkness or occlusion prevents a defensible decision.
- `people_count_estimate`: an approximate maximum visible count, not identity tracking. Crowds are capped at a rough visible estimate.
- `people_type`: use only `adult` or `child`; leave empty when age cannot be judged.
- `scene_type`: choose one primary compact V0.1 scene class. Put specific entities in `main_objects`.
- `shot_scale`: label the dominant subject framing, not the focal length. Use `null` for unreadable/accidental footage.
- `motion_level`: combines subject and camera movement as perceived across the clip. Use `unknown` when the clip is too short or unreadable.
- `quality_label`: `usable` means normally usable, `marginal` needs review/correction, and `unusable` should be rejected for ordinary editing.
- `material_role_candidates`: intrinsic material properties only. Do not add editorial roles such as opening, climax, or ending.
- `annotation_confidence`: overall confidence in the human labels, not a model score.

## Known annotation limits

- Sparse review cannot establish exact people counts in dense crowds.
- `child` versus `adult` is omitted for distant performers when age is not visually defensible.
- One clip has a `-90` Display Matrix even though its encoded landscape pixels are visually upright without autorotation. It is treated as a source metadata/content conflict, not evidence that global autorotation should be disabled.
- Two severely dark or obstructed clips intentionally abstain on uncertain content fields.
