"""Thin CLI for local Director stages."""

from pathlib import Path
import json

from pydantic import TypeAdapter
import typer

from director import __version__
from director.catalog.fixture import FixtureCatalogProvider
from director.music_directions import rank_directions
from director.music_blueprint import build_blueprint, build_generation_prompt
from director.scanner_bridge import build_library_profile
from director.schema import (
    CatalogSearchResult,
    ClipPlacement,
    MaterialLibraryProfile,
    MusicDirection,
    MusicSearchBrief,
    MusicStructure,
    SfxPlan,
    UserCreativeBrief,
)
from director.search_planner import build_music_search_brief
from scanner.schema import ScannerResult, TestManifest


app = typer.Typer(no_args_is_help=True, help="Music-driven travel montage prototype.")


@app.callback()
def main() -> None:
    """Run a Director prototype command."""


@app.command()
def version() -> None:
    """Print the Director contract version."""

    typer.echo(__version__)


@app.command("build-scanner-observations")
def build_scanner_observations_command(
    scanner_result: Path = typer.Option(..., "--scanner-result", exists=True, dir_okay=False),
    scanner_manifest: Path = typer.Option(..., "--scanner-manifest", exists=True, dir_okay=False),
    output: Path = typer.Option(..., "--output", dir_okay=False),
) -> None:
    """Bind local Scanner output to hashed source files without decoding media."""
    from director.scanner_bridge import build_scanner_observations_from_files
    observations = build_scanner_observations_from_files(
        ScannerResult.model_validate_json(scanner_result.read_text(encoding="utf-8")),
        TestManifest.model_validate_json(scanner_manifest.read_text(encoding="utf-8")), scanner_result,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(observations.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(str(output))


@app.command("build-frame-map")
def build_frame_map_command(
    scanner_result: Path = typer.Option(..., "--scanner-result", exists=True, dir_okay=False),
    scanner_observations: Path = typer.Option(..., "--scanner-observations", exists=True, dir_okay=False),
    scanner_run_dir: Path = typer.Option(..., "--scanner-run-dir", exists=True, file_okay=False),
    output: Path = typer.Option(..., "--output", dir_okay=False),
) -> None:
    """Resolve bounded local representative-frame maps from a Scanner run."""
    from director.scanner_bridge import build_material_frame_map
    from director.visual_schema import ClipObservationBatch
    frame_map = build_material_frame_map(
        ScannerResult.model_validate_json(scanner_result.read_text(encoding="utf-8")),
        ClipObservationBatch.model_validate_json(scanner_observations.read_text(encoding="utf-8")), scanner_run_dir,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(frame_map.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(str(output))


@app.command("prepare-agent-batches")
def prepare_agent_batches_command(
    frame_map: Path = typer.Option(..., "--frame-map", exists=True, dir_okay=False),
    output_dir: Path = typer.Option(..., "--output-dir", file_okay=False),
) -> None:
    """Create local contact sheets and bounded packets; no model is invoked."""
    from director.agent_batches import MaterialFrameMap, build_agent_batch_manifest
    manifest = build_agent_batch_manifest(
        MaterialFrameMap.model_validate_json(frame_map.read_text(encoding="utf-8")), output_dir
    )
    output = output_dir / "manifest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(str(output))


@app.command("plan-review")
def plan_review_command(
    observations: Path = typer.Option(
        ..., "--observations", exists=True, dir_okay=False
    ),
    output: Path = typer.Option(..., "--output", dir_okay=False),
    force_local_page: bool = typer.Option(False, "--force-local-page"),
) -> None:
    """Plan deterministic offline review routing from clip observations."""

    from director.skill_workflow import choose_review_route
    from director.visual_schema import ClipObservationBatch

    parsed_observations = ClipObservationBatch.model_validate_json(
        observations.read_text(encoding="utf-8")
    )
    route = choose_review_route(
        parsed_observations, force_local_page=force_local_page
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(route.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(str(output))


@app.command("plan-search")
def plan_search(
    scanner_result: Path = typer.Option(
        ..., "--scanner-result", exists=True, dir_okay=False
    ),
    scanner_manifest: Path = typer.Option(
        ..., "--scanner-manifest", exists=True, dir_okay=False
    ),
    brief: Path = typer.Option(..., "--brief", exists=True, dir_okay=False),
    output: Path = typer.Option(..., "--output", dir_okay=False),
) -> None:
    """Create a local, evidence-backed music search brief."""

    parsed_result = ScannerResult.model_validate_json(
        scanner_result.read_text(encoding="utf-8")
    )
    parsed_manifest = TestManifest.model_validate_json(
        scanner_manifest.read_text(encoding="utf-8")
    )
    parsed_brief = UserCreativeBrief.model_validate_json(
        brief.read_text(encoding="utf-8")
    )
    profile = build_library_profile(
        parsed_result,
        parsed_manifest,
        scanner_result.parent,
    )
    search_brief = build_music_search_brief(profile, parsed_brief)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(search_brief.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(str(output))


@app.command("catalog-fixture")
def catalog_fixture(
    brief: Path = typer.Option(..., "--brief", exists=True, dir_okay=False),
    fixture: Path = typer.Option(..., "--fixture", exists=True, dir_okay=False),
    output: Path = typer.Option(..., "--output", dir_okay=False),
) -> None:
    """Rank three music directions from an offline metadata fixture."""

    parsed_brief = MusicSearchBrief.model_validate_json(
        brief.read_text(encoding="utf-8")
    )
    result = FixtureCatalogProvider(fixture).search(parsed_brief)
    directions = rank_directions(result, parsed_brief, limit=3)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            [direction.model_dump(mode="json") for direction in directions],
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    typer.echo(str(output))


@app.command("blueprint")
def blueprint_command(
    directions: Path = typer.Option(
        ..., "--directions", exists=True, dir_okay=False
    ),
    choice: int = typer.Option(..., "--choice", min=1),
    brief: Path = typer.Option(..., "--brief", exists=True, dir_okay=False),
    output: Path = typer.Option(..., "--output", dir_okay=False),
) -> None:
    """Build a reference-safe blueprint from one selected direction."""

    parsed_directions = TypeAdapter(list[MusicDirection]).validate_json(
        directions.read_text(encoding="utf-8")
    )
    if choice > len(parsed_directions):
        raise typer.BadParameter("choice exceeds available directions", param_hint="--choice")
    parsed_brief = UserCreativeBrief.model_validate_json(
        brief.read_text(encoding="utf-8")
    )
    blueprint = build_blueprint(parsed_directions[choice - 1], parsed_brief)
    payload = {
        "blueprint": blueprint.model_dump(mode="json"),
        "generation_prompt": build_generation_prompt(blueprint),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    typer.echo(str(output))


@app.command("analyze-music")
def analyze_music_command(
    audio: Path = typer.Option(..., "--audio", exists=True, dir_okay=False),
    output: Path = typer.Option(..., "--output", dir_okay=False),
) -> None:
    """Measure beats, energy, sections, and ending from a local audio file."""

    from director.music_analysis import AudioAnalysisConfig, analyze_music

    structure = analyze_music(audio, AudioAnalysisConfig())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(structure.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(str(output))


@app.command("run-local")
def run_local_command(
    project_id: str = typer.Option(..., "--project-id"),
    scanner_result: Path = typer.Option(
        ..., "--scanner-result", exists=True, dir_okay=False
    ),
    scanner_manifest: Path = typer.Option(
        ..., "--scanner-manifest", exists=True, dir_okay=False
    ),
    brief: Path = typer.Option(..., "--brief", exists=True, dir_okay=False),
    catalog_fixture_path: Path = typer.Option(
        ..., "--catalog-fixture", exists=True, dir_okay=False
    ),
    music: Path = typer.Option(..., "--music", exists=True, dir_okay=False),
    run_root: Path = typer.Option(Path("prototype/runs"), "--run-root"),
    stop_after: str = typer.Option("timeline", "--stop-after"),
) -> None:
    """Run resumable local stages without any external provider call."""

    from director.music_analysis import AudioAnalysisConfig, analyze_music
    from director.project import (
        LOCAL_STAGE_ORDER,
        advance_project,
        create_project,
        record_project_inputs,
    )
    from director.timeline import TimelineConfig, build_timeline_slots

    if stop_after not in LOCAL_STAGE_ORDER[:6]:
        raise typer.BadParameter(
            "run-local supports material_profile through timeline",
            param_hint="--stop-after",
        )
    parsed_brief = UserCreativeBrief.model_validate_json(
        brief.read_text(encoding="utf-8")
    )
    paths = create_project(run_root, project_id, parsed_brief)
    record_project_inputs(
        paths,
        {
            "scanner_result": scanner_result,
            "scanner_manifest": scanner_manifest,
            "catalog_fixture": catalog_fixture_path,
            "music": music,
        },
    )

    def material_profile_adapter(_paths):
        parsed_result = ScannerResult.model_validate_json(
            scanner_result.read_text(encoding="utf-8")
        )
        parsed_manifest = TestManifest.model_validate_json(
            scanner_manifest.read_text(encoding="utf-8")
        )
        return build_library_profile(
            parsed_result,
            parsed_manifest,
            scanner_result.parent,
        )

    def search_brief_adapter(_paths):
        profile = MaterialLibraryProfile.model_validate_json(
            paths.material_profile.read_text(encoding="utf-8")
        )
        return build_music_search_brief(profile, parsed_brief)

    def catalog_adapter(_paths):
        search_brief = MusicSearchBrief.model_validate_json(
            paths.search_brief.read_text(encoding="utf-8")
        )
        return FixtureCatalogProvider(catalog_fixture_path).search(search_brief)

    def blueprint_adapter(_paths):
        search_brief = MusicSearchBrief.model_validate_json(
            paths.search_brief.read_text(encoding="utf-8")
        )
        catalog = CatalogSearchResult.model_validate_json(
            paths.catalog_result.read_text(encoding="utf-8")
        )
        directions = rank_directions(catalog, search_brief, limit=3)
        if not directions:
            raise ValueError("offline catalog fixture produced no direction")
        return build_blueprint(directions[0], parsed_brief)

    def music_structure_adapter(_paths):
        return analyze_music(music, AudioAnalysisConfig())

    def timeline_adapter(_paths):
        structure = MusicStructure.model_validate_json(
            paths.music_structure.read_text(encoding="utf-8")
        )
        return build_timeline_slots(structure, parsed_brief, TimelineConfig())

    state = advance_project(
        paths,
        stop_after,
        {
            "material_profile": material_profile_adapter,
            "search_brief": search_brief_adapter,
            "catalog": catalog_adapter,
            "blueprint": blueprint_adapter,
            "music_structure": music_structure_adapter,
            "timeline": timeline_adapter,
        },
    )
    typer.echo(state.model_dump_json(indent=2))


@app.command("init-visual-project")
def init_visual_project_command(
    project_id: str = typer.Option(..., "--project-id"),
    raw_brief: Path = typer.Option(
        ..., "--raw-brief", exists=True, dir_okay=False
    ),
    run_root: Path = typer.Option(Path("prototype/runs"), "--run-root"),
) -> None:
    """Initialize or reopen a V0.2 visual project without running providers."""

    from director.project import create_visual_project
    from director.visual_schema import RawCreativeBrief

    parsed_brief = RawCreativeBrief.model_validate_json(
        raw_brief.read_text(encoding="utf-8")
    )
    paths = create_visual_project(run_root, project_id, parsed_brief)
    typer.echo(str(paths.root))


@app.command("visual-status")
def visual_status_command(
    project: Path = typer.Option(..., "--project", exists=True, file_okay=False),
) -> None:
    """Read V0.2 visual project state without mutating it."""

    from director.project import load_project_state, open_project

    paths = open_project(project.resolve())
    state = load_project_state(paths)
    if state.schema_version != "0.2.0":
        raise typer.BadParameter(
            "project is not a V0.2 visual project", param_hint="--project"
        )
    typer.echo(state.model_dump_json(indent=2))


@app.command("normalize-brief")
def normalize_brief_command(
    brief: Path = typer.Option(..., "--brief", exists=True, dir_okay=False),
    output: Path = typer.Option(..., "--output", dir_okay=False),
) -> None:
    """Normalize an explicit V0.2 description or migrate a V0.1 brief."""

    from director.brief_interpreter import DeterministicBriefInterpreter
    from director.visual_schema import RawCreativeBrief

    payload = json.loads(brief.read_text(encoding="utf-8"))
    version = payload.get("schema_version")
    interpreter = DeterministicBriefInterpreter()
    if version == "0.1.0":
        draft = interpreter.normalize_legacy(UserCreativeBrief.model_validate(payload))
    elif version == "0.2.0":
        draft = interpreter.normalize(RawCreativeBrief.model_validate(payload))
    else:
        raise typer.BadParameter(
            "brief must use schema_version 0.1.0 or 0.2.0",
            param_hint="--brief",
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(draft.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(str(output))


@app.command("render-brief-review")
def render_brief_review_command(
    draft: Path = typer.Option(..., "--draft", exists=True, dir_okay=False),
    output: Path = typer.Option(..., "--output", dir_okay=False),
) -> None:
    """Render an offline form for reviewing normalized user intent."""

    from director.brief_interpreter import render_brief_review, sha256_file
    from director.visual_schema import NormalizedIntentDraft

    parsed = NormalizedIntentDraft.model_validate_json(
        draft.read_text(encoding="utf-8")
    )
    render_brief_review(parsed, output, draft_sha256=sha256_file(draft))
    typer.echo(str(output))


@app.command("confirm-brief")
def confirm_brief_command(
    draft: Path = typer.Option(..., "--draft", exists=True, dir_okay=False),
    confirmation: Path = typer.Option(
        ..., "--confirmation", exists=True, dir_okay=False
    ),
    output: Path = typer.Option(..., "--output", dir_okay=False),
) -> None:
    """Validate and record a hash-bound brief confirmation."""

    from director.brief_interpreter import sha256_file, validate_brief_confirmation
    from director.visual_schema import BriefConfirmation, NormalizedIntentDraft

    if output.resolve() == draft.resolve():
        raise typer.BadParameter("output cannot overwrite the draft", param_hint="--output")
    parsed_draft = NormalizedIntentDraft.model_validate_json(
        draft.read_text(encoding="utf-8")
    )
    parsed_confirmation = BriefConfirmation.model_validate_json(
        confirmation.read_text(encoding="utf-8")
    )
    validate_brief_confirmation(
        parsed_confirmation,
        parsed_draft,
        sha256_file(draft),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        parsed_confirmation.model_dump_json(indent=2), encoding="utf-8"
    )
    typer.echo(str(output))


@app.command("freeze-visual-evaluation")
def freeze_visual_evaluation_command(
    source_manifest: Path = typer.Option(
        ..., "--source-manifest", exists=True, dir_okay=False
    ),
    cv_profile: Path = typer.Option(
        ..., "--cv-profile", exists=True, dir_okay=False
    ),
    probe_root: Path = typer.Option(
        ..., "--probe-root", exists=True, file_okay=False
    ),
    output_dir: Path = typer.Option(..., "--output-dir", file_okay=False),
) -> None:
    """Freeze 12/12/6 manifests and blank labels from existing local evidence."""

    from director.evaluation import freeze_evaluation_pack

    paths = freeze_evaluation_pack(
        source_manifest,
        cv_profile,
        probe_root,
        output_dir,
    )
    typer.echo(
        json.dumps(
            {name: str(path) for name, path in paths.items()},
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("render-visual-review")
def render_visual_review_command(
    observations: Path = typer.Option(
        ..., "--observations", exists=True, dir_okay=False
    ),
    ground_truth_template: Path = typer.Option(
        ..., "--ground-truth-template", exists=True, dir_okay=False
    ),
    output: Path = typer.Option(..., "--output", dir_okay=False),
) -> None:
    """Render an offline observation confirmation form from saved probe frames."""

    from director.evaluation import DirectorVisualGroundTruth, sha256_file
    from director.visual_review import render_visual_review
    from director.visual_schema import ClipObservationBatch

    parsed_observations = ClipObservationBatch.model_validate_json(
        observations.read_text(encoding="utf-8")
    )
    template = DirectorVisualGroundTruth.model_validate_json(
        ground_truth_template.read_text(encoding="utf-8")
    )
    frame_paths = {
        record.material_id: [
            (
                path
                if path.is_absolute()
                else ground_truth_template.parent / path
            )
            for raw_path in record.frame_paths
            for path in [Path(raw_path)]
        ]
        for record in template.records
    }
    render_visual_review(
        parsed_observations,
        frame_paths,
        output,
        source_observations_sha256=sha256_file(observations),
    )
    typer.echo(str(output))


@app.command("validate-visual-ground-truth")
def validate_visual_ground_truth_command(
    split: Path = typer.Option(..., "--split", exists=True, dir_okay=False),
    ground_truth: Path = typer.Option(
        ..., "--ground-truth", exists=True, dir_okay=False
    ),
    require_completed: bool = typer.Option(
        True, "--require-completed/--allow-incomplete"
    ),
) -> None:
    """Validate membership, hashes, enums, and completion of manual labels."""

    from director.evaluation import (
        DirectorVisualGroundTruth,
        DirectorVisualSplit,
        validate_ground_truth,
    )

    parsed_split = DirectorVisualSplit.model_validate_json(
        split.read_text(encoding="utf-8")
    )
    parsed_ground_truth = DirectorVisualGroundTruth.model_validate_json(
        ground_truth.read_text(encoding="utf-8")
    )
    validate_ground_truth(
        parsed_ground_truth,
        parsed_split,
        require_completed=require_completed,
    )
    typer.echo("valid")


@app.command("validate-visual-confirmation")
def validate_visual_confirmation_command(
    observations: Path = typer.Option(
        ..., "--observations", exists=True, dir_okay=False
    ),
    confirmation: Path = typer.Option(
        ..., "--confirmation", exists=True, dir_okay=False
    ),
) -> None:
    """Validate a visual confirmation against its immutable draft artifact."""

    from director.evaluation import VisualConfirmation, sha256_file
    from director.visual_review import (
        validate_visual_confirmation_against_observations,
    )
    from director.visual_schema import ClipObservationBatch

    parsed_observations = ClipObservationBatch.model_validate_json(
        observations.read_text(encoding="utf-8")
    )
    parsed_confirmation = VisualConfirmation.model_validate_json(
        confirmation.read_text(encoding="utf-8")
    )
    validate_visual_confirmation_against_observations(
        parsed_confirmation,
        parsed_observations,
        sha256_file(observations),
    )
    typer.echo("valid")


@app.command("import-visual-confirmation")
def import_visual_confirmation_command(
    observations: Path = typer.Option(
        ..., "--observations", exists=True, dir_okay=False
    ),
    confirmation: Path = typer.Option(
        ..., "--confirmation", exists=True, dir_okay=False
    ),
    output: Path = typer.Option(..., "--output", dir_okay=False),
) -> None:
    """Create a new assisted observation artifact without overwriting its draft."""

    from director.evaluation import VisualConfirmation, sha256_file
    from director.visual_review import (
        apply_visual_confirmation,
        validate_visual_confirmation_against_observations,
    )
    from director.visual_schema import ClipObservationBatch

    parsed_observations = ClipObservationBatch.model_validate_json(
        observations.read_text(encoding="utf-8")
    )
    parsed_confirmation = VisualConfirmation.model_validate_json(
        confirmation.read_text(encoding="utf-8")
    )
    validate_visual_confirmation_against_observations(
        parsed_confirmation,
        parsed_observations,
        sha256_file(observations),
    )
    updated = apply_visual_confirmation(
        parsed_observations,
        parsed_confirmation,
        confirmation,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(updated.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(str(output))


@app.command("render-director-review")
def render_director_review_command(
    treatment: Path = typer.Option(
        ..., "--treatment", exists=True, dir_okay=False
    ),
    output: Path = typer.Option(..., "--output", dir_okay=False),
) -> None:
    """Render the separate bucket/function override ledger."""

    from director.visual_review import render_director_review
    from director.visual_schema import DirectorTreatment

    parsed = DirectorTreatment.model_validate_json(
        treatment.read_text(encoding="utf-8")
    )
    render_director_review(parsed, output)
    typer.echo(str(output))


@app.command("build-director-treatment")
def build_director_treatment_command(
    observations: Path = typer.Option(
        ..., "--observations", exists=True, dir_okay=False
    ),
    brief_confirmation: Path = typer.Option(
        ..., "--brief-confirmation", exists=True, dir_okay=False
    ),
    decisions_output: Path = typer.Option(..., "--decisions-output", dir_okay=False),
    coverage_output: Path = typer.Option(..., "--coverage-output", dir_okay=False),
    output: Path = typer.Option(..., "--output", dir_okay=False),
) -> None:
    """Build deterministic decisions, project coverage, and director treatment."""

    from director.director_treatment import build_director_treatment
    from director.intent_matcher import build_intent_decisions, build_project_coverage
    from director.visual_schema import BriefConfirmation, ClipObservationBatch

    destinations = [decisions_output.resolve(), coverage_output.resolve(), output.resolve()]
    if len(destinations) != len(set(destinations)):
        raise typer.BadParameter("output paths must be distinct")
    inputs = {observations.resolve(), brief_confirmation.resolve()}
    if any(path in inputs for path in destinations):
        raise typer.BadParameter("outputs cannot overwrite input artifacts")
    parsed_observations = ClipObservationBatch.model_validate_json(
        observations.read_text(encoding="utf-8")
    )
    parsed_brief = BriefConfirmation.model_validate_json(
        brief_confirmation.read_text(encoding="utf-8")
    )
    decisions = build_intent_decisions(parsed_observations, parsed_brief)
    coverage = build_project_coverage(parsed_observations, decisions)
    treatment = build_director_treatment(decisions, coverage, parsed_brief)
    for path, artifact in (
        (decisions_output, decisions),
        (coverage_output, coverage),
        (output, treatment),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(str(output))


@app.command("recommend-music-prompts")
def recommend_music_prompts_command(
    treatment: Path = typer.Option(
        ..., "--treatment", exists=True, dir_okay=False
    ),
    brief_confirmation: Path = typer.Option(
        ..., "--brief-confirmation", exists=True, dir_okay=False
    ),
    coverage: Path = typer.Option(..., "--coverage", exists=True, dir_okay=False),
    output: Path = typer.Option(..., "--output", dir_okay=False),
) -> None:
    """Write three offline, ready-to-use music generation prompts."""

    from director.music_prompt_recommender import recommend_music_prompts
    from director.visual_schema import (
        BriefConfirmation,
        DirectorTreatment,
        ProjectCoverage,
    )

    inputs = {treatment.resolve(), brief_confirmation.resolve(), coverage.resolve()}
    if output.resolve() in inputs:
        raise typer.BadParameter("output cannot overwrite an input artifact")
    parsed_treatment = DirectorTreatment.model_validate_json(
        treatment.read_text(encoding="utf-8")
    )
    parsed_brief = BriefConfirmation.model_validate_json(
        brief_confirmation.read_text(encoding="utf-8")
    )
    parsed_coverage = ProjectCoverage.model_validate_json(
        coverage.read_text(encoding="utf-8")
    )
    recommendations = recommend_music_prompts(
        parsed_treatment,
        parsed_brief,
        parsed_coverage,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(recommendations.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(str(output))


@app.command("validate-director-review")
def validate_director_review_command(
    treatment: Path = typer.Option(
        ..., "--treatment", exists=True, dir_okay=False
    ),
    review: Path = typer.Option(..., "--review", exists=True, dir_okay=False),
) -> None:
    """Validate an exported director override ledger against its treatment."""

    from director.visual_review import validate_director_review
    from director.visual_schema import DirectorReview, DirectorTreatment

    parsed_treatment = DirectorTreatment.model_validate_json(
        treatment.read_text(encoding="utf-8")
    )
    parsed_review = DirectorReview.model_validate_json(
        review.read_text(encoding="utf-8")
    )
    validate_director_review(parsed_review, parsed_treatment)
    typer.echo("valid")


@app.command("render-project")
def render_project_command(
    project: Path = typer.Option(..., "--project", exists=True, file_okay=False),
    output: Path = typer.Option(..., "--output", dir_okay=False),
) -> None:
    """Render one bounded local project preview and record its verified result."""

    from director.project import open_project, record_stage_artifact
    from director.render import RenderResult, render_preview, verify_render_result

    root = project.resolve()
    paths = open_project(root)
    if paths.render_result.exists():
        existing = RenderResult.model_validate_json(
            paths.render_result.read_text(encoding="utf-8")
        )
        if existing.status == "completed" and not verify_render_result(existing):
            raise RuntimeError("recorded render output hash drifted")
        typer.echo(existing.model_dump_json(indent=2))
        if existing.status != "completed":
            raise typer.Exit(code=1)
        return
    parsed_placements = TypeAdapter(list[ClipPlacement]).validate_json(
        paths.clip_placements.read_text(encoding="utf-8")
    )
    parsed_sfx = SfxPlan.model_validate_json(
        paths.sfx_plan.read_text(encoding="utf-8")
    )
    parsed_brief = UserCreativeBrief.model_validate_json(
        paths.brief.read_text(encoding="utf-8")
    )
    manifest = json.loads(paths.input_manifest.read_text(encoding="utf-8"))
    music_path = Path(manifest["inputs"]["music"]["path"])
    expected_duration = sum(
        item.source_out - item.source_in for item in parsed_placements
    )
    result = render_preview(
        placements=parsed_placements,
        music=music_path,
        sfx_plan=parsed_sfx,
        output=output,
        orientation=parsed_brief.orientation,
        music_duration_seconds=expected_duration,
    )
    record_stage_artifact(paths, "render", result)
    typer.echo(result.model_dump_json(indent=2))
    if result.status != "completed":
        raise typer.Exit(code=1)
