import pytest

from scanner.cache import cache_key, create_run_dir
from scanner.config import ScanConfig, SamplingConfig
from scanner.schema import ManifestEntry, SourceRecord, TechnicalMetadata


def _entry(mtime_ns: int) -> ManifestEntry:
    return ManifestEntry(
        file="clip.mov",
        source=SourceRecord(relative_path="clip.mov", size_bytes=10, mtime_ns=mtime_ns),
        technical=TechnicalMetadata(
            duration=1.0,
            width=320,
            height=240,
            fps=25,
            orientation="landscape",
            codec="h264",
        ),
    )


def test_cache_key_changes_with_source_config_and_model_revision() -> None:
    base = _entry(1)
    adaptive = ScanConfig(sampling=SamplingConfig(profile="adaptive5"))
    temporal = ScanConfig(sampling=SamplingConfig(profile="temporal3"))

    first = cache_key(base, adaptive, {"siglip": "a"})

    assert first != cache_key(_entry(2), adaptive, {"siglip": "a"})
    assert first != cache_key(base, temporal, {"siglip": "a"})
    assert first != cache_key(base, adaptive, {"siglip": "b"})


def test_run_directory_is_immutable_and_resume_requires_identical_config(tmp_path) -> None:
    config = ScanConfig(sampling=SamplingConfig(profile="adaptive5"))
    paths = create_run_dir(tmp_path, "run-1", config)

    assert paths.evidence.is_dir()
    assert paths.cache_links.is_dir()
    assert (paths.root / "environment.json").exists()
    with pytest.raises(FileExistsError):
        create_run_dir(tmp_path, "run-1", config)

    resumed = create_run_dir(tmp_path, "run-1", config, resume=True)
    assert resumed.root == paths.root
    changed = ScanConfig(sampling=SamplingConfig(profile="temporal3"))
    with pytest.raises(ValueError, match="different config"):
        create_run_dir(tmp_path, "run-1", changed, resume=True)
    with pytest.raises(ValueError, match="safe path component"):
        create_run_dir(tmp_path, "../escape", config)
