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
from director.schema import MusicDirection, MusicSearchBrief, UserCreativeBrief
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
