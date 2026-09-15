"""Offline tests for src/ingestion/download.py using file:// URLs -- no
real network access, but exercises the real curl subprocess + atomic-
rename + checksum-verification path exactly as production does.
"""

from pathlib import Path

import pytest

from ingestion.download import DownloadVerificationError, PinnedAsset, download_pinned, read_sidecar
from ingestion.manifest import sha256_of


def _make_source(tmp_path, content=b"hello world") -> Path:
    src = tmp_path / "source.bin"
    src.write_bytes(content)
    return src


def test_fresh_download_writes_file_and_sidecar_with_real_timestamp(tmp_path):
    src = _make_source(tmp_path)
    dest = tmp_path / "dest" / "asset.bin"
    asset = PinnedAsset(source_id="t1", url=f"file://{src}", dest=dest, expected_bytes=len(b"hello world"))

    path, downloaded, retrieved_at, method = download_pinned(asset)

    assert downloaded is True
    assert method == "download"
    assert path.read_bytes() == b"hello world"
    sidecar = read_sidecar(dest)
    assert sidecar["sha256"] == sha256_of(dest)
    assert sidecar["retrieved_at_utc"] == retrieved_at
    assert sidecar["url"] == f"file://{src}"
    assert not (dest.parent / (dest.name + ".partial")).exists()


def test_reuse_when_bytes_and_sha256_match(tmp_path):
    src = _make_source(tmp_path)
    dest = tmp_path / "dest" / "asset.bin"
    expected_sha = sha256_of(src)
    asset = PinnedAsset(source_id="t1", url=f"file://{src}", dest=dest,
                         expected_bytes=len(b"hello world"), expected_sha256=expected_sha)

    path1, downloaded1, retrieved_at1, method1 = download_pinned(asset)
    assert downloaded1 is True
    assert method1 == "download"

    # Second call: file already present and matches -- must NOT redownload,
    # and must report the ORIGINAL retrieval time, not a new one.
    path2, downloaded2, retrieved_at2, method2 = download_pinned(asset)
    assert downloaded2 is False
    assert retrieved_at2 == retrieved_at1
    assert method2 == "download"


def test_reuse_with_sidecar_url_mismatch_falls_back_to_mtime_proxy(tmp_path):
    src = _make_source(tmp_path)
    dest = tmp_path / "dest" / "asset.bin"
    asset = PinnedAsset(source_id="t1", url=f"file://{src}", dest=dest, expected_bytes=len(b"hello world"))

    download_pinned(asset)
    # Simulate a sidecar that does not identify THIS asset (e.g. a manual
    # backfill, or a sidecar copied from a different source) -- its
    # retrieved_at_utc must NOT be trusted even though bytes match.
    from ingestion.download import write_sidecar
    write_sidecar(dest, "2020-01-01T00:00:00+00:00", sha256_of(dest), dest.stat().st_size, url="placeholder-not-the-real-url")

    path, downloaded, retrieved_at, method = download_pinned(asset)

    assert downloaded is False
    assert method == "filesystem_mtime_proxy"
    assert retrieved_at != "2020-01-01T00:00:00+00:00"


def test_refuses_reuse_on_byte_count_mismatch(tmp_path):
    src = _make_source(tmp_path)
    dest = tmp_path / "dest" / "asset.bin"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"wrong content, wrong length!!")
    asset = PinnedAsset(source_id="t1", url=f"file://{src}", dest=dest, expected_bytes=len(b"hello world"))

    with pytest.raises(DownloadVerificationError, match="bytes"):
        download_pinned(asset)


def test_refuses_reuse_on_sha256_mismatch_even_with_matching_bytes(tmp_path):
    src = _make_source(tmp_path)
    dest = tmp_path / "dest" / "asset.bin"
    dest.parent.mkdir(parents=True)
    same_length_wrong_content = b"HELLO WORLD"  # same length as "hello world"
    assert len(same_length_wrong_content) == len(b"hello world")
    dest.write_bytes(same_length_wrong_content)
    asset = PinnedAsset(source_id="t1", url=f"file://{src}", dest=dest,
                         expected_bytes=len(b"hello world"), expected_sha256=sha256_of(src))

    with pytest.raises(DownloadVerificationError, match="sha256"):
        download_pinned(asset)


def test_failed_download_leaves_no_partial_file_at_dest(tmp_path):
    dest = tmp_path / "dest" / "asset.bin"
    asset = PinnedAsset(source_id="t1", url="file:///does/not/exist/at/all.bin", dest=dest, retries=0, max_time_s=5)

    with pytest.raises(DownloadVerificationError):
        download_pinned(asset)

    assert not dest.exists()
    assert not (dest.parent / (dest.name + ".partial")).exists()


def test_content_change_at_source_is_caught_by_expected_bytes(tmp_path):
    src = _make_source(tmp_path, content=b"a completely different, longer payload here")
    dest = tmp_path / "dest" / "asset.bin"
    asset = PinnedAsset(source_id="t1", url=f"file://{src}", dest=dest, expected_bytes=len(b"hello world"))

    with pytest.raises(DownloadVerificationError, match="expected"):
        download_pinned(asset)
    assert not dest.exists()
