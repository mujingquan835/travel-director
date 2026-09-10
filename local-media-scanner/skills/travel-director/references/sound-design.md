# Evidence-based sound event design

Read this reference when designing sound effects, ambient layers, or foley events for an edit decision.

Do not treat sound design as mechanical keyword matching or arbitrary whoosh stacking. Every sound cue must have a concrete visual anchor, a defined auditory plane, an alignment between sound event and picture event, and attributable listening provenance.

## Core concepts

### 1. Layers and auditory planes

Sound is organized across three functional roles and three auditory depth planes:

- **Roles**:
  - `location_ambient`: Establishes place, environment, and spatial continuity. Ambient sound must not restart abruptly at every cut.
  - `action_foley`: Grounded in visible physical actions (footsteps, vehicle movement, door closing, water splash). Requires an explicit visual trigger.
  - `transition_accent`: Cinematic risers, hits, subdrops, or whooshes. Must have an explicit narrative reason; do not place a whoosh by default on every camera cut.
- **Auditory planes**:
  - `foreground`: Primary focus, synchronized with key subject action or focal moment.
  - `midground`: Secondary narrative elements, character actions, or spatial environment.
  - `background`: Bed of atmosphere, continuous ambient texture, or distant soundscape.

### 2. Time alignment: Event anchor, not file start

Audio files often contain quiet lead-ins or build-up before the impact or peak. Aligning the file's start (`timeline_in`) with the visual event causes the sound accent to arrive late.

Instead, define:
- `event_time`: The timeline moment where the visual event occurs (e.g. from fine review `action_moment`).
- `source_anchor_time`: The timestamp in the audio file where the sound transient or peak occurs.
- `source_in`: The start point inside the audio file.
- `pre_roll = source_anchor_time - source_in`: The acoustic build-up duration.

The program calculates:
$$\text{timeline\_in} = \text{event\_time} - (\text{source\_anchor\_time} - \text{source\_in})$$

The sound accent lands exactly at `event_time`. If `pre_roll` causes `timeline_in < 0`, the cue is rejected rather than silently truncated.

### 3. Location sound vs. library SFX vs. explicit gaps

- `location_recorded`: Real location sound recorded from camera footage or field microphones. External SFX library files must not be falsely claimed as location recordings.
- `library_sfx`: Recorded or synthesized library effects. Must have concrete selection rationale.
- `missing_gap`: When location sound is noisy/unusable or library effects are missing, declare an explicit gap (`sound_type: "missing_gap"`). Do not substitute inappropriate library sounds to pretend complete coverage.

### 4. Relation with music

- `parallel`: Independent mix alongside music.
- `music_ducked`: Voice or action sound requiring lowered music gain.
- `music_silent`: Sound event playing during an explicit music silence segment (as planned in `music_adaptation`).
- `accent_sync`: Sound accent synchronized with an adapted music accent or turn.

### 5. Listening provenance

- `not_listened`: Structural proposal without human or session listening.
- `source_listened`: Audio source file has been auditioned for transient and texture.
- `context_reviewed`: Auditioned in mix with picture and music.

Claims of `source_listened` or `context_reviewed` require a matching `SoundListeningRecord` covering the source interval. Program validation checks coverage and integrity, but does not prove aesthetic quality.

## CLI Usage

From the package root:

```bash
# Build initial sound design
uv run travel-director build-sound-design --plan <plan.json> --output <new_output_dir>

# Build an immutable revision against an earlier version
uv run travel-director build-sound-design --plan <revised_plan.json> --parent <previous_sound_design.json> --output <new_revision_dir>

# Revalidate a saved sound design
uv run travel-director inspect-sound-design --sound-design <sound_design.json>

# Export validated FCPXML package
uv run travel-director export-fcpxml --decision <returned_edit_decision.json> --output <package_dir>
```

The returned edit decision preserves upstream `shot_group` and `music_adaptation` bindings, adds a `sound_design` binding, and materializes non-conflicting audio tracks into the timeline.
