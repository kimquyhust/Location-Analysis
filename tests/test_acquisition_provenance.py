"""Offline tests for Overture release-provenance checking and the generic
derived-asset reuse helper in run_acquisition.py -- no network access.
"""

from unittest.mock import patch

import duckdb
import pytest

from ingestion.acquire_overture import (
    OvertureAoiResult,
    ReleaseResolutionError,
    acquire_aoi_subset,
    resolve_release,
    sidecar_matches_request,
    verify_output_integrity,
    write_sidecar,
)
from ingestion.manifest import sha256_of
from ingestion.run_acquisition import derive_or_reuse

CONNECTOR_REQUIRED_COLUMNS = {"id", "sources", "bbox", "geometry"}


def _build_tiny_connector_fixture(path):
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute(f"""
        COPY (
            SELECT * FROM (VALUES
                (
                    'id-1',
                    [{{'property': NULL, 'dataset': 'osm', 'license': NULL, 'record_id': NULL,
                       'update_time': NULL, 'confidence': NULL, 'between': NULL,
                       'provider': NULL, 'resource': NULL, 'version': NULL}}],
                    {{'xmin': 108.2, 'xmax': 108.2, 'ymin': 16.0, 'ymax': 16.0}},
                    ST_Point(108.2, 16.0)
                )
            ) AS t(id, sources, bbox, geometry)
        ) TO '{path}' (FORMAT PARQUET)
    """)
    con.close()


def test_resolve_release_raises_loudly_on_network_failure_no_silent_fallback():
    with patch("urllib.request.urlopen", side_effect=RuntimeError("network unreachable")):
        with pytest.raises(ReleaseResolutionError):
            resolve_release()


def test_resolve_release_raises_when_bucket_listing_is_empty():
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"<ListBucketResult></ListBucketResult>"

    with patch("urllib.request.urlopen", return_value=_Resp()):
        with pytest.raises(ReleaseResolutionError):
            resolve_release()


def test_resolve_release_picks_lexically_latest_from_real_shaped_response():
    xml = (
        b"<ListBucketResult>"
        b"<CommonPrefixes><Prefix>release/2026-07-22.0/</Prefix></CommonPrefixes>"
        b"<CommonPrefixes><Prefix>release/2026-08-19.0/</Prefix></CommonPrefixes>"
        b"</ListBucketResult>"
    )

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return xml

    with patch("urllib.request.urlopen", return_value=_Resp()):
        assert resolve_release() == "2026-08-19.0"


def test_sidecar_matches_exact_release_bbox_schema():
    sidecar = {
        "theme": "places", "type": "place", "release": "2026-08-19.0",
        "bbox": [108.07, 15.72, 108.38, 16.18], "schema_columns": ["id", "basic_category"],
    }
    ok, reason = sidecar_matches_request(sidecar, "places", "place", "2026-08-19.0", (108.07, 15.72, 108.38, 16.18), {"id", "basic_category"})
    assert ok, reason


def test_sidecar_rejects_stale_release():
    sidecar = {
        "theme": "places", "type": "place", "release": "2026-07-22.0",
        "bbox": [108.07, 15.72, 108.38, 16.18], "schema_columns": ["id", "basic_category"],
    }
    ok, reason = sidecar_matches_request(sidecar, "places", "place", "2026-08-19.0", (108.07, 15.72, 108.38, 16.18), {"id"})
    assert not ok
    assert "release" in reason


def test_sidecar_rejects_bbox_mismatch():
    sidecar = {
        "theme": "places", "type": "place", "release": "2026-08-19.0",
        "bbox": [1.0, 1.0, 2.0, 2.0], "schema_columns": ["id"],
    }
    ok, reason = sidecar_matches_request(sidecar, "places", "place", "2026-08-19.0", (108.07, 15.72, 108.38, 16.18), {"id"})
    assert not ok
    assert "bbox" in reason


def test_sidecar_rejects_missing_required_columns():
    sidecar = {
        "theme": "places", "type": "place", "release": "2026-08-19.0",
        "bbox": [108.07, 15.72, 108.38, 16.18], "schema_columns": ["id"],  # missing basic_category
    }
    ok, reason = sidecar_matches_request(sidecar, "places", "place", "2026-08-19.0", (108.07, 15.72, 108.38, 16.18), {"id", "basic_category"})
    assert not ok
    assert "schema" in reason


def test_write_and_read_sidecar_roundtrip(tmp_path):
    out_path = tmp_path / "subset.parquet"
    out_path.write_bytes(b"not a real parquet, just for sidecar path testing")
    write_sidecar(out_path, {"release": "2026-08-19.0", "row_count": 42})
    from ingestion.acquire_overture import read_sidecar
    sidecar = read_sidecar(out_path)
    assert sidecar["release"] == "2026-08-19.0"
    assert sidecar["row_count"] == 42


# --- derive_or_reuse (generic derived-asset helper in run_acquisition.py) ---

def test_derive_or_reuse_produces_fresh_when_no_sidecar(tmp_path):
    out_path = tmp_path / "derived.bin"
    calls = []

    def produce():
        calls.append(1)
        out_path.write_bytes(b"derived content")

    path, meta, was_new = derive_or_reuse(out_path, "parent-sha-abc", {"tool": "test", "param": 1}, produce)

    assert was_new is True
    assert len(calls) == 1
    assert meta["parent_sha256"] == "parent-sha-abc"


def test_derive_or_reuse_skips_regeneration_when_parent_and_transform_match(tmp_path):
    out_path = tmp_path / "derived.bin"
    calls = []

    def produce():
        calls.append(1)
        out_path.write_bytes(b"derived content")

    derive_or_reuse(out_path, "parent-sha-abc", {"tool": "test", "param": 1}, produce)
    path2, meta2, was_new2 = derive_or_reuse(out_path, "parent-sha-abc", {"tool": "test", "param": 1}, produce)

    assert was_new2 is False
    assert len(calls) == 1  # produce() only called once, not twice


def test_derive_or_reuse_regenerates_when_parent_sha256_changes(tmp_path):
    out_path = tmp_path / "derived.bin"
    calls = []

    def produce():
        calls.append(1)
        out_path.write_bytes(f"derived content v{len(calls)}".encode())

    derive_or_reuse(out_path, "parent-sha-v1", {"tool": "test"}, produce)
    path2, meta2, was_new2 = derive_or_reuse(out_path, "parent-sha-v2", {"tool": "test"}, produce)

    assert was_new2 is True
    assert len(calls) == 2
    assert meta2["parent_sha256"] == "parent-sha-v2"


def test_derive_or_reuse_regenerates_when_transform_params_change(tmp_path):
    out_path = tmp_path / "derived.bin"
    calls = []

    def produce():
        calls.append(1)
        out_path.write_bytes(b"content")

    derive_or_reuse(out_path, "parent-sha", {"bbox": [1, 2, 3, 4]}, produce)
    path2, meta2, was_new2 = derive_or_reuse(out_path, "parent-sha", {"bbox": [9, 9, 9, 9]}, produce)

    assert was_new2 is True
    assert len(calls) == 2


def test_derive_or_reuse_refuses_reuse_of_file_with_no_sidecar(tmp_path):
    out_path = tmp_path / "derived.bin"
    out_path.write_bytes(b"pre-existing file with no provenance")
    calls = []

    def produce():
        calls.append(1)
        out_path.write_bytes(b"regenerated content")

    path, meta, was_new = derive_or_reuse(out_path, "parent-sha", {"tool": "test"}, produce)

    assert was_new is True
    assert len(calls) == 1
    assert out_path.read_bytes() == b"regenerated content"


def test_derive_or_reuse_regenerates_when_existing_output_is_corrupted_but_sidecar_matches(tmp_path):
    # Same parent_sha256/transform as the original derivation (so the
    # sidecar metadata check alone would say "reuse") -- but the file's
    # bytes were changed after being derived, without updating the sidecar.
    # This is exactly the case the sidecar-metadata-only check missed.
    out_path = tmp_path / "derived.bin"
    calls = []

    def produce():
        calls.append(1)
        out_path.write_bytes(b"derived content")

    derive_or_reuse(out_path, "parent-sha", {"tool": "test"}, produce)
    out_path.write_bytes(b"CORRUPTED -- tampered after derivation")  # sidecar untouched

    path2, meta2, was_new2 = derive_or_reuse(out_path, "parent-sha", {"tool": "test"}, produce)

    assert was_new2 is True
    assert len(calls) == 2
    assert out_path.read_bytes() == b"derived content"  # regenerated back to real content


def test_derive_or_reuse_reruns_validator_on_reuse_and_regenerates_on_failure(tmp_path):
    # File and sidecar are perfectly self-consistent (untouched since
    # derivation) -- but revalidation on the REUSE path (e.g. tightened
    # validation logic since the file was first derived) rejects the
    # existing content. Even with matching checksums, reuse must not bypass
    # revalidation; the file must be regenerated, and the newly-produced
    # content must be revalidated again (and pass).
    out_path = tmp_path / "derived.bin"
    calls = []
    validate_calls = []

    def produce():
        calls.append(1)
        out_path.write_bytes(f"derived content v{len(calls)}".encode())

    def fails_only_on_first_call(p):
        validate_calls.append(1)
        if len(validate_calls) == 1:
            raise ValueError("content no longer considered valid on reuse-check")
        return {"ok": True}

    derive_or_reuse(out_path, "parent-sha", {"tool": "test"}, produce)  # no validate_fn on first derivation
    path2, meta2, was_new2 = derive_or_reuse(
        out_path, "parent-sha", {"tool": "test"}, produce, validate_fn=fails_only_on_first_call,
    )

    assert was_new2 is True
    assert len(calls) == 2  # regenerated, not silently reused
    assert len(validate_calls) == 2  # reuse-check call (failed) + post-regeneration call (passed)


# --- Overture acquire_aoi_subset integrity verification (P1: do not trust
# sidecar metadata alone) ---

def test_verify_output_integrity_passes_for_untampered_file(tmp_path):
    path = tmp_path / "connectors.parquet"
    _build_tiny_connector_fixture(path)
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    sidecar = {"bytes": path.stat().st_size, "sha256": sha256_of(path), "row_count": 1}

    ok, reason = verify_output_integrity(path, sidecar, CONNECTOR_REQUIRED_COLUMNS, con)
    assert ok, reason


def test_verify_output_integrity_fails_on_byte_count_mismatch(tmp_path):
    path = tmp_path / "connectors.parquet"
    _build_tiny_connector_fixture(path)
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    sidecar = {"bytes": path.stat().st_size + 1, "sha256": sha256_of(path), "row_count": 1}

    ok, reason = verify_output_integrity(path, sidecar, CONNECTOR_REQUIRED_COLUMNS, con)
    assert not ok
    assert "bytes" in reason


def test_verify_output_integrity_fails_on_checksum_mismatch_with_same_byte_count(tmp_path):
    path = tmp_path / "connectors.parquet"
    _build_tiny_connector_fixture(path)
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    real_bytes = path.stat().st_size
    # A sidecar recording a DIFFERENT sha256 but the SAME byte count --
    # simulates the file's content being silently replaced (corrupted
    # parquet) without its size changing.
    sidecar = {"bytes": real_bytes, "sha256": "0" * 64, "row_count": 1}

    ok, reason = verify_output_integrity(path, sidecar, CONNECTOR_REQUIRED_COLUMNS, con)
    assert not ok
    assert "sha256" in reason


def test_verify_output_integrity_fails_on_row_count_mismatch(tmp_path):
    path = tmp_path / "connectors.parquet"
    _build_tiny_connector_fixture(path)
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    sidecar = {"bytes": path.stat().st_size, "sha256": sha256_of(path), "row_count": 999}

    ok, reason = verify_output_integrity(path, sidecar, CONNECTOR_REQUIRED_COLUMNS, con)
    assert not ok
    assert "row_count" in reason


def test_verify_output_integrity_fails_on_missing_local_columns(tmp_path):
    path = tmp_path / "connectors.parquet"
    _build_tiny_connector_fixture(path)
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    sidecar = {"bytes": path.stat().st_size, "sha256": sha256_of(path), "row_count": 1}

    ok, reason = verify_output_integrity(path, sidecar, CONNECTOR_REQUIRED_COLUMNS | {"confidence"}, con)
    assert not ok
    assert "missing required columns" in reason


def test_acquire_aoi_subset_refuses_reuse_and_refetches_when_file_is_corrupted(tmp_path):
    """End-to-end: a sidecar whose METADATA matches the request (theme/type/
    release/bbox/schema) is still not trusted if the file itself doesn't
    match that sidecar's own recorded sha256 -- acquire_aoi_subset must
    discard and re-fetch rather than silently returning corrupted data."""
    path = tmp_path / "connectors.parquet"
    _build_tiny_connector_fixture(path)
    write_sidecar(path, {
        "theme": "transportation", "type": "connector", "release": "2026-08-19.0",
        "s3_path": "s3://fake/connectors", "bbox": [0.0, 0.0, 1.0, 1.0], "row_count": 1,
        "schema_columns": sorted(CONNECTOR_REQUIRED_COLUMNS),
        "sha256": sha256_of(path), "bytes": path.stat().st_size,
        "fetched_at_utc": "2026-01-01T00:00:00+00:00",
    })
    path.write_bytes(b"corrupted parquet content, tampered after the sidecar was written")

    def _fake_refetch(theme, type_, release, bbox, output_path, con=None):
        output_path.write_bytes(b"freshly refetched content")
        write_sidecar(output_path, {
            "theme": theme, "type": type_, "release": release, "s3_path": "s3://fake/connectors",
            "bbox": list(bbox), "row_count": 1, "schema_columns": sorted(CONNECTOR_REQUIRED_COLUMNS),
            "sha256": sha256_of(output_path), "bytes": output_path.stat().st_size,
            "fetched_at_utc": "2026-01-02T00:00:00+00:00",
        })
        return OvertureAoiResult(
            theme=theme, type_=type_, release=release, s3_path="s3://fake/connectors",
            row_count=1, output_path=output_path, schema_columns=sorted(CONNECTOR_REQUIRED_COLUMNS),
        )

    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    with patch("ingestion.acquire_overture.fetch_aoi_subset", side_effect=_fake_refetch) as mock_fetch:
        result, provenance = acquire_aoi_subset(
            "transportation", "connector", (0.0, 0.0, 1.0, 1.0), path, release="2026-08-19.0", con=con,
        )

    assert mock_fetch.called
    assert provenance["reused"] is False
    assert path.read_bytes() == b"freshly refetched content"
