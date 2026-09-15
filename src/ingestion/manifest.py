"""Immutable per-run source manifest for acquired geospatial assets.

Fields follow `required_manifest_fields` in `config/data_sources.yaml`. A
manifest is keyed by `run_id` and, once written, is never edited in place --
re-running acquisition produces a new run_id and therefore a new manifest
file rather than mutating a previous one.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

MANIFEST_DIR = Path("data/manifests")
_CHUNK_SIZE = 1 << 20


def new_run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclasses.dataclass
class ManifestEntry:
    source_id: str
    provider: str
    product: str
    release: str
    represented_at: str
    retrieved_at_utc: str
    source_uri: str
    local_path: str
    sha256: str
    bytes: int
    license_id: str
    crs: Optional[str]
    bounds: Optional[list]
    expected_assets: list
    present_assets: list
    notes: str = ""
    # Derived-asset provenance (empty/None for a raw pinned source entry).
    # `parent_source_id` links to another entry's `source_id` in the SAME
    # manifest; `parent_sha256` pins exactly which content of that parent
    # this entry was derived from, so a manifest entry for e.g. the OSM AOI
    # extract is traceable to the exact raw PBF checksum it came from.
    is_derived: bool = False
    parent_source_id: Optional[str] = None
    parent_sha256: Optional[str] = None
    # Every parent when a derived asset is a mosaic of several tiles;
    # `parent_source_id` then names the first of them and `parent_sha256`
    # is the digest over all of their checksums.
    parent_source_ids: Optional[list] = None
    transform: Optional[dict] = None
    validation: Optional[dict] = None
    # How `retrieved_at_utc` was established: "download" (this run's own
    # verified download), "filesystem_mtime_proxy" (backfilled from the
    # local file's mtime because no trustworthy sidecar identifying this
    # exact asset's URL existed), or "unknown". Filesystem mtime is NOT
    # proof of the original retrieval time -- it is only ever reported as
    # an explicitly-labeled proxy, never presented as a real timestamp.
    retrieved_at_utc_method: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class RunManifest:
    """Accumulates entries for one acquisition run and writes them to a
    run-id-keyed JSON file under `data/manifests/`. Raises if a manifest for
    this run_id already exists -- manifests are append-within-a-run, then
    frozen; they are not mutated across runs.

    Carries an explicit `status`: "in_progress" while entries are still
    being added, "complete" once `finalize()` is called, or "failed" if
    `mark_failed()` is called (the caller's job -- typically from an
    `except` block around the whole acquisition run) so an aborted run is
    distinguishable from a merely-smaller successful one by more than entry
    count alone.
    """

    def __init__(self, run_id: Optional[str] = None, manifest_dir: Path = MANIFEST_DIR):
        self.run_id = run_id or new_run_id()
        self.manifest_dir = Path(manifest_dir)
        self.entries: list[ManifestEntry] = []
        self.path = self.manifest_dir / f"source_manifest_{self.run_id}.json"
        self.status = "in_progress"
        self.failure_reason: Optional[str] = None
        if self.path.exists():
            raise FileExistsError(
                f"Manifest {self.path} already exists; manifests are immutable "
                f"per run_id. Start a new run to get a new run_id."
            )

    def add(self, entry: ManifestEntry) -> None:
        self.entries.append(entry)
        self._write()

    def _write(self) -> None:
        self.manifest_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "manifest_version": "1.1.0",
            "run_id": self.run_id,
            "status": self.status,
            "failure_reason": self.failure_reason,
            "written_at_utc": utc_now_iso(),
            "sources": [e.as_dict() for e in self.entries],
        }
        tmp_path = self.path.with_suffix(".json.tmp")
        with open(tmp_path, "w") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_path, self.path)

    def finalize(self) -> Path:
        self.status = "complete"
        self._write()
        return self.path

    def mark_failed(self, reason: str = "") -> Path:
        self.status = "failed"
        self.failure_reason = reason or None
        self._write()
        return self.path


def load_manifest(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return json.load(f)


def latest_manifest(manifest_dir: Path = MANIFEST_DIR) -> Optional[Path]:
    if not manifest_dir.exists():
        return None
    candidates = sorted(manifest_dir.glob("source_manifest_*.json"))
    return candidates[-1] if candidates else None
