"""Thin CLI for local Director stages."""

import typer

from director import __version__


app = typer.Typer(no_args_is_help=True, help="Music-driven travel montage prototype.")


@app.callback()
def main() -> None:
    """Run a Director prototype command."""


@app.command()
def version() -> None:
    """Print the Director contract version."""

    typer.echo(__version__)
