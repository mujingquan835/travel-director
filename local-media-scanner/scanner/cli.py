"""Developer-only command line interface."""

from __future__ import annotations

from pathlib import Path

import typer

from scanner import __version__
from scanner.metadata import build_manifest, discover_videos


app = typer.Typer(no_args_is_help=True, help="Local-first travel media scanner experiments.")


@app.callback()
def main() -> None:
    """Run a local media scanner experiment command."""


@app.command()
def version() -> None:
    """Print the scanner package version."""

    typer.echo(__version__)


@app.command()
def inspect(input: Path = typer.Option(..., "--input", exists=True, file_okay=False)) -> None:
    """Print read-only ffprobe metadata for a video directory."""

    manifest = build_manifest(input, discover_videos(input))
    typer.echo(manifest.model_dump_json(indent=2))
