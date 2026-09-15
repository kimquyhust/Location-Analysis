import pytest

from ingestion.manifest import ManifestEntry, RunManifest, load_manifest, utc_now_iso


def _entry(source_id="test_source"):
    return ManifestEntry(
        source_id=source_id, provider="test", product="test product", release="v1",
        represented_at="v1", retrieved_at_utc=utc_now_iso(), source_uri="https://example.invalid/x",
        local_path="data/raw/x.bin", sha256="0" * 64, bytes=123,
        license_id="CC-BY-4.0", crs=None, bounds=None,
        expected_assets=[source_id], present_assets=[source_id],
    )


def test_manifest_writes_and_is_readable(tmp_path):
    manifest = RunManifest(run_id="test_run_1", manifest_dir=tmp_path)
    manifest.add(_entry("source_a"))
    manifest.add(_entry("source_b"))
    path = manifest.finalize()

    assert path.exists()
    data = load_manifest(path)
    assert data["run_id"] == "test_run_1"
    assert data["status"] == "complete"
    assert [s["source_id"] for s in data["sources"]] == ["source_a", "source_b"]


def test_manifest_status_starts_in_progress_before_finalize(tmp_path):
    manifest = RunManifest(run_id="test_run_status", manifest_dir=tmp_path)
    manifest.add(_entry("source_a"))

    data = load_manifest(manifest.path)
    assert data["status"] == "in_progress"


def test_manifest_mark_failed_records_status_and_reason(tmp_path):
    manifest = RunManifest(run_id="test_run_failed", manifest_dir=tmp_path)
    manifest.add(_entry("source_a"))
    path = manifest.mark_failed("ReleaseResolutionError: bucket listing empty")

    data = load_manifest(path)
    assert data["status"] == "failed"
    assert "ReleaseResolutionError" in data["failure_reason"]
    # A failed run's entries acquired before the failure are still preserved,
    # not discarded -- the manifest stays honest about partial progress.
    assert [s["source_id"] for s in data["sources"]] == ["source_a"]


def test_manifest_refuses_to_reuse_an_existing_run_id(tmp_path):
    RunManifest(run_id="dup_run", manifest_dir=tmp_path).add(_entry())
    with pytest.raises(FileExistsError):
        RunManifest(run_id="dup_run", manifest_dir=tmp_path)


def test_new_run_id_is_fresh_each_time():
    from ingestion.manifest import new_run_id
    assert new_run_id() != "" and isinstance(new_run_id(), str)
