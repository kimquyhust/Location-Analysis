"""Source resolution and checksum verification for a Gate 3 run.

Every input is resolved through `data/gate2/aoi_sources/gate2_source_index.json`
and the AOI's OWN acquisition manifest (never a lexical or first-match
choice across manifests), and its bytes are hashed BEFORE any feature is
computed. A mismatch between the file on disk, the source index and the
manifest is an error, not a warning: a feature computed from an unverified
input has no lineage.
"""

from __future__ import annotations

import json
from pathlib import Path

try:  # pragma: no cover - import root differs between CLI and tests
    from ..spatial.benchmark import sha256_of
    from ..spatial.run_gate2 import _load_acquisition_manifest
except ImportError:  # pragma: no cover
    from spatial.benchmark import sha256_of
    from spatial.run_gate2 import _load_acquisition_manifest

ROLE_KEYS = {"poi_roads": "roads_poi", "population": "population",
             "land_cover": "land_cover", "built_up": "built_up"}


class ProvenanceError(RuntimeError):
    pass


def load_source_index(path: Path) -> tuple[dict, dict[str, dict]]:
    index = json.loads(Path(path).read_text())
    return index, _load_acquisition_manifest(index)


def verify_aoi_sources(aoi_id: str, index: dict, manifest_entries: dict[str, dict]) -> list[dict]:
    """Hash every source file of one AOI and check it against the source
    index AND the AOI's manifest entry. Returns one provenance row per
    source role with the verified checksum and the manifest facts."""
    if aoi_id not in index["aois"]:
        raise ProvenanceError(f"{aoi_id}: not present in the source index")
    aoi = index["aois"][aoi_id]
    rows = []
    for role, key in ROLE_KEYS.items():
        src = aoi[key]
        path = Path(src["path"])
        if path.is_absolute():
            raise ProvenanceError(f"{aoi_id}/{role}: absolute path in source index {path}")
        if not path.exists():
            raise ProvenanceError(f"{aoi_id}/{role}: source file missing: {path}")
        actual = sha256_of(path)
        if actual != src["sha256"]:
            raise ProvenanceError(
                f"{aoi_id}/{role}: {path} sha256 {actual} != source index {src['sha256']}")
        entry = manifest_entries.get(src["source_id"])
        if entry is None:
            raise ProvenanceError(f"{aoi_id}/{role}: {src['source_id']} absent from acquisition manifest")
        if entry.get("sha256") != actual:
            raise ProvenanceError(
                f"{aoi_id}/{role}: manifest sha256 {entry.get('sha256')} != file {actual}")
        parent = manifest_entries.get(entry.get("parent_source_id", ""), {})
        coverage = src.get("coverage") or {}
        rows.append({
            "aoi_id": aoi_id, "source_role": role, "source_id": src["source_id"],
            "path": str(path), "sha256": actual, "bytes": int(path.stat().st_size),
            "release": entry.get("release") or parent.get("release"),
            "license_id": entry.get("license_id") or parent.get("license_id"),
            "source_uri": parent.get("source_uri") or entry.get("source_uri"),
            "retrieved_at_utc": entry.get("retrieved_at_utc"),
            "crs": entry.get("crs"),
            "parent_source_ids": json.dumps(entry.get("parent_source_ids") or [entry.get("parent_source_id")]),
            "source_tiles": json.dumps((src.get("transform") or {}).get("source_tiles")),
            "acquisition_run_id": aoi.get("acquisition_run_id"),
            "acquisition_manifest": aoi.get("manifest_path"),
            "window_inside_tile_union": coverage.get("window_inside_tile_union"),
            "window_covered_by_clip": coverage.get("window_covered_by_clip"),
            "checksum_verified": True,
        })
    return rows
