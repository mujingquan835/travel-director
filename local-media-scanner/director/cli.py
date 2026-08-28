"""Thin CLI for local Director stages."""

from pathlib import Path

import typer

from director import __version__
from director.scanner_bridge import build_library_profile
from director.schema import UserCreativeBrief
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
