"""Verified, idempotent, atomic download of a pinned remote asset.

Never silently re-downloads a file that already matches the pinned expected
byte count AND checksum, and never silently accepts a file that does not
match -- both are load-bearing for the "fail loudly on ... changed source
content" rule. Downloads go to a `.partial` sibling and are only moved into
place after byte-count/checksum verification succeeds, so a crashed or
interrupted download can never leave a file at the canonical path that
looks reusable.

A sidecar `<path>.meta.json` records the asset's retrieval time AND the
URL it was retrieved from. Reusing an already-downloaded file reports that
recorded time only if the sidecar's `url` matches the asset's CURRENT url
-- a sidecar is otherwise not proof of anything about this specific asset
(e.g. a sidecar carrying a placeholder/backfilled url, or one written for a
different source). When no trustworthy sidecar exists, the file's own
filesystem mtime is used as an explicitly-labeled PROXY
(`retrieved_at_utc_method="filesystem_mtime_proxy"`) -- never presented as
if it were the real retrieval time, since mtime is not proof of when a
file was actually downloaded (it can be changed by copies, checkouts, or
filesystem operations unrelated to the original fetch).
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class DownloadVerificationError(RuntimeError):
    """HTTP failure, byte-count mismatch, or checksum mismatch."""


@dataclass
class PinnedAsset:
    source_id: str
    url: str
    dest: Path
    expected_bytes: Optional[int] = None
    expected_sha256: Optional[str] = None
    retries: int = 3
    retry_delay_s: int = 5
    max_time_s: int = 300


def _sidecar_path(dest: Path) -> Path:
    return dest.with_suffix(dest.suffix + ".meta.json")


def read_sidecar(dest: Path) -> Optional[dict]:
    sidecar = _sidecar_path(dest)
    if not sidecar.exists():
        return None
    with open(sidecar) as f:
        return json.load(f)


def write_sidecar(dest: Path, retrieved_at_utc: str, sha256: str, bytes_: int, url: str, method: str = "download") -> Path:
    sidecar = _sidecar_path(dest)
    with open(sidecar, "w") as f:
        json.dump({
            "retrieved_at_utc": retrieved_at_utc, "sha256": sha256,
            "bytes": bytes_, "url": url, "retrieved_at_utc_method": method,
        }, f, indent=2)
    return sidecar


def download_pinned(asset: PinnedAsset) -> tuple[Path, bool, str, str]:
    """Return (path, was_downloaded, retrieved_at_utc, retrieved_at_utc_method).
    Reuses an existing file at `asset.dest` only if BOTH its size matches
    `asset.expected_bytes` (when pinned) AND, when `asset.expected_sha256` is
    pinned, its checksum matches too -- otherwise downloads via curl to a
    `.partial` file, verifies, and atomically renames into place.
    """
    from .manifest import sha256_of, utc_now_iso  # local import: keeps this module import-light

    dest = asset.dest
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        actual_bytes = dest.stat().st_size
        if asset.expected_bytes is not None and actual_bytes != asset.expected_bytes:
            raise DownloadVerificationError(
                f"{asset.source_id}: existing file {dest} is {actual_bytes} bytes, "
                f"expected {asset.expected_bytes}. Refusing to silently reuse or "
                f"overwrite -- remove it manually if it should be re-fetched."
            )
        if asset.expected_sha256 is not None:
            actual_sha256 = sha256_of(dest)
            if actual_sha256 != asset.expected_sha256:
                raise DownloadVerificationError(
                    f"{asset.source_id}: existing file {dest} has sha256 {actual_sha256}, "
                    f"expected {asset.expected_sha256}. Refusing to silently reuse a file "
                    f"whose content does not match the pinned checksum."
                )
        sidecar = read_sidecar(dest)
        # A sidecar's recorded retrieval time is trusted ONLY if it also
        # identifies the SAME url as this asset's current pinned url -- a
        # sidecar with a mismatched or placeholder url (e.g. a manual
        # backfill) is not proof of anything about *this* asset's real
        # retrieval time, even if its byte count happens to match.
        if sidecar is not None and sidecar.get("bytes") == actual_bytes and sidecar.get("url") == asset.url:
            retrieved_at_utc = sidecar["retrieved_at_utc"]
            retrieved_at_utc_method = sidecar.get("retrieved_at_utc_method", "download")
        else:
            # No trustworthy sidecar identifying this exact asset -- we can
            # still verify bytes/checksum above, but we cannot know the true
            # original retrieval time. The file's own mtime is used as an
            # explicitly-labeled PROXY, never claimed as the real time.
            mtime = dest.stat().st_mtime
            retrieved_at_utc = dt.datetime.fromtimestamp(mtime, dt.timezone.utc).isoformat(timespec="seconds")
            retrieved_at_utc_method = "filesystem_mtime_proxy"
            write_sidecar(dest, retrieved_at_utc, sha256_of(dest), actual_bytes, asset.url, method=retrieved_at_utc_method)
        return dest, False, retrieved_at_utc, retrieved_at_utc_method

    tmp_path = dest.with_suffix(dest.suffix + ".partial")
    if tmp_path.exists():
        tmp_path.unlink()

    cmd = [
        "curl", "--fail", "--location",
        "--retry", str(asset.retries),
        "--retry-delay", str(asset.retry_delay_s),
        "--max-time", str(asset.max_time_s),
        "--output", str(tmp_path),
        asset.url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        if tmp_path.exists():
            tmp_path.unlink()
        raise DownloadVerificationError(
            f"{asset.source_id}: download failed (curl exit {result.returncode}): "
            f"{result.stderr.strip()[-2000:]}"
        )

    actual_bytes = tmp_path.stat().st_size
    if asset.expected_bytes is not None and actual_bytes != asset.expected_bytes:
        mismatch = (
            f"{asset.source_id}: downloaded {actual_bytes} bytes, expected "
            f"{asset.expected_bytes}. Source content may have changed -- do not "
            f"proceed without re-pinning and documenting the new size."
        )
        tmp_path.unlink()
        raise DownloadVerificationError(mismatch)

    actual_sha256 = sha256_of(tmp_path)
    if asset.expected_sha256 is not None and actual_sha256 != asset.expected_sha256:
        tmp_path.unlink()
        raise DownloadVerificationError(
            f"{asset.source_id}: sha256 mismatch. "
            f"expected={asset.expected_sha256} actual={actual_sha256}"
        )

    retrieved_at_utc = utc_now_iso()
    tmp_path.replace(dest)  # atomic: dest never observably holds a partial file
    write_sidecar(dest, retrieved_at_utc, actual_sha256, actual_bytes, asset.url, method="download")
    return dest, True, retrieved_at_utc, "download"
