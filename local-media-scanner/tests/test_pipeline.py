from pathlib import Path

from typer.testing import CliRunner

from scanner.cli import app
from scanner.config import ScanConfig, SamplingConfig
from scanner.detector import Detection
from scanner.metadata import probe_video
from scanner.pipeline import ScanContext, scan_manifest
from scanner.schema import ManifestEntry, SourceRecord, TestManifest as ScannerManifest
from scanner.vision import FramePrediction, LabelScore


def test_one_decode_failure_does_not_abort_manifest(sample_video: Path, tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.mov"
    corrupt.write_bytes(b"not a video")
    technical = probe_video(sample_video)
    entries = []
    for path in (sample_video, corrupt):
        stat = path.stat()
        entries.append(
            ManifestEntry(
                file=path.name,
                source=SourceRecord(
                    relative_path=path.name,
                    size_bytes=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                ),
                technical=technical,
            )
        )
    manifest = ScannerManifest(input_root=str(tmp_path), entries=entries)
    context = ScanContext(
        input_root=tmp_path,
        run_dir=tmp_path / "run",
        config=ScanConfig(sampling=SamplingConfig(hardware_acceleration="none")),
    )

    result = scan_manifest(manifest, context)

    assert len(result.items) == 2
    assert result.items[0].analysis_status == "complete"
    assert result.items[1].analysis_status == "failed"
    assert result.items[1].errors[0].stage == "sampling"
    assert result.items[1].errors[0].code == "decode_failed"


def test_shared_representatives_feed_models_and_fusion(sample_video: Path, tmp_path: Path) -> None:
    technical = probe_video(sample_video)
    stat = sample_video.stat()
    entry = ManifestEntry(
        file=sample_video.name,
        source=SourceRecord(
            relative_path=sample_video.name,
            size_bytes=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
        ),
        technical=technical,
    )

    class FakeDetector:
        def detect(self, images):
            return [[Detection("person", 0.9, (0, 0, 100, 220))] for _ in images]

    class FakeVision:
        def classify_many(self, images, field_groups):
            winners = {
                "scene": "building",
                "shot_scale": "close",
                "people_type": "adult",
                "action": "walking",
                "objects": "building",
            }
            output = {}
            for field, groups in field_groups.items():
                winner = winners[field]
                other = next(label for label in groups if label != winner)
                scores = [LabelScore(winner, 0.9), LabelScore(other, 0.1)]
                output[field] = [
                    FramePrediction(field, scores, 0.8, "fake-vision") for _ in images
                ]
            return output

    manifest = ScannerManifest(input_root=str(sample_video.parent), entries=[entry])
    context = ScanContext(
        input_root=sample_video.parent,
        run_dir=tmp_path / "run-models",
        config=ScanConfig(sampling=SamplingConfig(hardware_acceleration="none")),
        detector=FakeDetector(),
        vision_encoder=FakeVision(),
        model_revisions={"detector": "fake-detector", "siglip": "fake-vision"},
        actual_device="cpu",
    )

    scan_result = scan_manifest(manifest, context)
    card = scan_result.items[0]

    assert card.content.people_present is True
    assert card.content.people_count_estimate == 1
    assert card.content.people_type == ["adult"]
    assert card.content.scene_type == "building"
    assert card.content.simple_action == "walking"
    assert card.shot_scale == "close"
    assert set(card.material_role_candidates) == {"human_story", "experience", "detail"}
    assert card.field_status["content.scene_type"] == "predicted"
    assert scan_result.actual_device == "cpu"
    assert scan_result.model_revisions["siglip"] == "fake-vision"
    evidence = tmp_path / "run-models" / "evidence" / f"{sample_video.name}.json"
    cache_link = tmp_path / "run-models" / "cache-links" / f"{sample_video.name}.json"
    assert evidence.exists()
    assert cache_link.exists()
    evidence_payload = evidence.read_text(encoding="utf-8")
    assert '"source": "fake-vision"' in evidence_payload
    assert "ground_truth" not in evidence_payload.lower()


def test_scan_cli_writes_immutable_run_result_without_models(sample_video: Path, tmp_path: Path) -> None:
    technical = probe_video(sample_video)
    stat = sample_video.stat()
    manifest = ScannerManifest(
        input_root=str(sample_video.parent),
        entries=[
            ManifestEntry(
                file=sample_video.name,
                source=SourceRecord(
                    relative_path=sample_video.name,
                    size_bytes=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                ),
                technical=technical,
            )
        ],
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    runs_dir = tmp_path / "runs"

    result = CliRunner().invoke(
        app,
        [
            "scan",
            "--manifest",
            str(manifest_path),
            "--run-id",
            "test-run",
            "--runs-dir",
            str(runs_dir),
            "--hwaccel",
            "none",
            "--no-models",
        ],
    )

    assert result.exit_code == 0, result.stdout
    output = runs_dir / "test-run" / "scanner_result.json"
    assert output.exists()
    payload = output.read_text(encoding="utf-8")
    assert '"run_id": "test-run"' in payload
    assert '"actual_device": "none"' in payload
    assert (runs_dir / "test-run" / "environment.json").exists()
