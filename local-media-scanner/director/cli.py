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
