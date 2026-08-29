from __future__ import annotations

from typing import NoReturn

from director.generation.base import GenerationAuthorization
from director.generation.dreamina import DreaminaCapabilities, DreaminaMusicProvider
from director.schema import MusicBlueprint, MusicBlueprintSection


def blueprint() -> MusicBlueprint:
    return MusicBlueprint(
        duration_seconds=60,
        bpm=116,
        meter="4/4",
        genre="light electronic",
        instrumentation=["acoustic guitar", "electronic drums"],
        vocals="none",
        sections=[
            MusicBlueprintSection(start=0, end=60, role="climax", energy=0.8)
        ],
        ending="clean resolved ending",
    )


def forbidden_runner(*args: object, **kwargs: object) -> NoReturn:
    raise AssertionError("generation runner must not be invoked")


def test_generation_is_blocked_without_explicit_authorization() -> None:
    provider = DreaminaMusicProvider(
        capabilities=DreaminaCapabilities(
            music_generation=True,
            music_command="music generate",
        ),
        runner=forbidden_runner,
    )

    asset = provider.generate(
        blueprint(), GenerationAuthorization.denied("dreamina")
    )

    assert asset.status == "blocked"
    assert asset.errors[0].code == "not_authorized"


def test_missing_music_command_is_detected_from_help() -> None:
    capabilities = DreaminaCapabilities.from_help("image\nvideo\n")

    assert capabilities.music_generation is False
    assert capabilities.music_command is None


def test_missing_music_command_blocks_even_an_authorized_request() -> None:
    provider = DreaminaMusicProvider(
        capabilities=DreaminaCapabilities.from_help("image\nvideo\n"),
        runner=forbidden_runner,
    )

    asset = provider.generate(
        blueprint(),
        GenerationAuthorization(
            provider="dreamina",
            max_calls=1,
            approved_by_user=True,
        ),
    )

    assert asset.status == "blocked"
    assert asset.errors[0].code == "unsupported_capability"


def test_help_parser_requires_an_explicit_generation_command() -> None:
    capabilities = DreaminaCapabilities.from_help(
        "Commands:\n  image generate\n  video generate\n  music generate\n"
    )

    assert capabilities.music_generation is True
    assert capabilities.music_command == "music generate"
