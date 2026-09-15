"""Reproducible acquisition entry point for the Da Nang-Hoi An prototype.

Downloads the pinned OSM/WorldPop/GHS-POP assets (idempotent -- reuses a
file already on disk only if BOTH its byte count and, where pinned, its
sha256 match), derives the AOI subsets (osmium extract / gdal_translate /
unzip), validates every raw and derived asset (CRS, NoData, OSM PBF
structure), fetches Overture AOI subsets with release-specific provenance
checking, and writes ONE immutable source manifest covering every raw AND
derived asset -- each derived entry records its parent's checksum, the
exact transform parameters used, and its own validation result. Re-running
this script reuses any asset whose content and derivation parameters are
unchanged; anything that would silently reuse stale or unverifiable content
is refused and regenerated instead.

The Overture release is an explicit, required CLI choice -- either
`--overture-release RELEASE` (reproducible) or `--resolve-latest` (opt in
to acquiring a new release). There is no implicit "latest" mode: a run that
names no release fails rather than silently binding itself to whatever the
bucket holds at that moment.

Usage:
    # reproduce the audited run
    python -m src.ingestion.run_acquisition --overture-release 2026-08-19.0
    # deliberately acquire a newer release
    python -m src.ingestion.run_acquisition --resolve-latest
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Optional

from .acquire_overture import (
    REQUIRED_COLUMNS,
    acquire_aoi_subset,
    add_release_args,
    release_from_args,
    _connect,
)
from .download import PinnedAsset, download_pinned
from .manifest import ManifestEntry, RunManifest, sha256_of, utc_now_iso
from .validators import validate_osm_pbf, validate_raster

ACQUISITION_AOI = (108.07, 15.72, 108.38, 16.18)  # west, south, east, north
EVALUATION_AOI = (108.10, 15.75, 108.35, 16.15)

RAW_DIR = Path("data/raw")
AOI_DIR = Path("data/prototype/danang_hoian_halo")

# expected_sha256 values below were observed and verified across multiple
# independent downloads in this project's acquisition history (recorded in
# data/manifests/source_manifest_20260914T050158Z.json) -- pinning them now
# means any future content change at the source is caught, not silently
# accepted.
PINNED_ASSETS = {
    "osm_geofabrik_vnm_20260913": PinnedAsset(
        source_id="osm_geofabrik_vnm_20260913",
        url="https://download.geofabrik.de/asia/vietnam-260913.osm.pbf",
        dest=RAW_DIR / "osm" / "vietnam-260913.osm.pbf",
        expected_bytes=328_456_722,
        expected_sha256="3c4b19fea3e58ce0e3f6a1a52d75b141de1351e699cb8136bd7b1585bc24f52c",
        max_time_s=600,
    ),
    "worldpop_vnm_2025_cn_100m_r2025a_v1": PinnedAsset(
        source_id="worldpop_vnm_2025_cn_100m_r2025a_v1",
        url="https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2025/VNM/v1/100m/constrained/vnm_pop_2025_CN_100m_R2025A_v1.tif",
        dest=RAW_DIR / "worldpop" / "vnm_pop_2025_CN_100m_R2025A_v1.tif",
        expected_bytes=75_215_955,
        expected_sha256="21f403884d5a2d3a0961f75ef66dea51c43fcc9e2e99d4e43cbcceafd6774540",
        max_time_s=600,
    ),
    "worldpop_vnm_2020_cn_100m_r2025a_v1": PinnedAsset(
        source_id="worldpop_vnm_2020_cn_100m_r2025a_v1",
        url="https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2020/VNM/v1/100m/constrained/vnm_pop_2020_CN_100m_R2025A_v1.tif",
        dest=RAW_DIR / "worldpop" / "vnm_pop_2020_CN_100m_R2025A_v1.tif",
        expected_bytes=74_064_549,
        expected_sha256="d615df574ef2d42a1ca0f29c66f27f8d044a2b5b7be9ee368be8afb747127606",
        max_time_s=600,
    ),
    "ghspop_e2020_r2023a_r8_c29": PinnedAsset(
        source_id="ghspop_e2020_r2023a_r8_c29",
        url="https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/GHS_POP_E2020_GLOBE_R2023A_54009_100/V1-0/tiles/GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0_R8_C29.zip",
        dest=RAW_DIR / "ghsl" / "GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0_R8_C29.zip",
        expected_bytes=39_426_582,
        expected_sha256="d83c34aa9e108388dda3841db08996b3b3a598986270986b65daf77617568219",
        # This JRC endpoint has been observed to take 45-60s to first byte
        # before streaming -- a short timeout here will falsely look like a
        # dead source, so this is generous on purpose.
        retries=5, retry_delay_s=15, max_time_s=300,
    ),
}

RAW_ASSET_LICENSES = {
    "osm_geofabrik_vnm_20260913": ("OpenStreetMap contributors / Geofabrik", "Geofabrik Vietnam OSM extract", "vietnam-260913", "ODbL-1.0"),
    "worldpop_vnm_2025_cn_100m_r2025a_v1": ("WorldPop / University of Southampton", "Global 2 R2025A v1 constrained count", "2025", "CC-BY-4.0"),
    "worldpop_vnm_2020_cn_100m_r2025a_v1": ("WorldPop / University of Southampton", "Global 2 R2025A v1 constrained count", "2020", "CC-BY-4.0"),
    "ghspop_e2020_r2023a_r8_c29": ("European Commission JRC GHSL", "GHS-POP R2023A", "E2020", "CC-BY-4.0"),
}


# ---------------------------------------------------------------------------
# Generic derived-asset helper: a derived file is only reused if a sidecar
# exists AND its recorded parent_sha256 + transform parameters match the
# CURRENT request exactly. Otherwise it is regenerated.
# ---------------------------------------------------------------------------

def _derived_sidecar_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".derived.json")


def _read_derived_sidecar(path: Path) -> Optional[dict]:
    sidecar = _derived_sidecar_path(path)
    if not sidecar.exists():
        return None
    with open(sidecar) as f:
        return json.load(f)


def derive_or_reuse(out_path: Path, parent_sha256: str, transform: dict, produce_fn, validate_fn=None) -> tuple[Path, dict, bool]:
    """Reuses `out_path` only if ALL of the following hold:
    1. a `.derived.json` sidecar exists and its `parent_sha256`/`transform`
       match the current request;
    2. the file's CURRENT byte count and sha256 still match what the
       sidecar itself recorded (catches the file being modified/corrupted
       after derivation, independent of whether the parent/transform are
       still correct);
    3. `validate_fn`, if given, is re-run against the CURRENT file and does
       not raise (catches structural corruption a byte-for-byte match alone
       wouldn't -- e.g. re-validation logic being stricter than when this
       file was first derived).
    Any failure of 2 or 3 is treated exactly like a stale sidecar: the file
    is discarded and regenerated, never silently trusted.
    """
    existing = _read_derived_sidecar(out_path)
    if out_path.exists() and existing is not None:
        if existing.get("parent_sha256") == parent_sha256 and existing.get("transform") == transform:
            actual_bytes = out_path.stat().st_size
            actual_sha256 = sha256_of(out_path)
            integrity_ok = actual_bytes == existing.get("bytes") and actual_sha256 == existing.get("sha256")
            revalidation_ok = True
            if integrity_ok and validate_fn is not None:
                try:
                    validate_fn(out_path)
                except Exception:
                    revalidation_ok = False
            if integrity_ok and revalidation_ok:
                return out_path, existing, False
        out_path.unlink()
        _derived_sidecar_path(out_path).unlink(missing_ok=True)
    elif out_path.exists() and existing is None:
        out_path.unlink()

    produce_fn()
    validation = validate_fn(out_path) if validate_fn else {}
    meta = {
        "parent_sha256": parent_sha256,
        "transform": transform,
        "derived_at_utc": utc_now_iso(),
        "sha256": sha256_of(out_path),
        "bytes": out_path.stat().st_size,
        "validation": validation,
    }
    with open(_derived_sidecar_path(out_path), "w") as f:
        json.dump(meta, f, indent=2)
    return out_path, meta, True


# ---------------------------------------------------------------------------
# Raw pinned assets
# ---------------------------------------------------------------------------

def acquire_pinned_assets(manifest: RunManifest) -> dict[str, Path]:
    paths = {}
    for source_id, asset in PINNED_ASSETS.items():
        path, downloaded, retrieved_at_utc, retrieved_at_utc_method = download_pinned(asset)
        provider, product, release, license_id = RAW_ASSET_LICENSES[source_id]

        validation = {}
        if path.suffix == ".tif":
            validation = validate_raster(path)
        elif path.suffix == ".pbf":
            validation = validate_osm_pbf(path)

        if downloaded:
            notes = "downloaded this run"
        else:
            notes = (
                "reused existing verified file (checksum-confirmed); "
                f"retrieved_at_utc_method={retrieved_at_utc_method}"
            )
        manifest.add(ManifestEntry(
            source_id=source_id, provider=provider, product=product, release=release,
            represented_at=release, retrieved_at_utc=retrieved_at_utc, source_uri=asset.url,
            local_path=str(path), sha256=sha256_of(path), bytes=path.stat().st_size,
            license_id=license_id, crs=validation.get("crs"), bounds=validation.get("bounds"),
            expected_assets=[source_id], present_assets=[source_id],
            notes=notes, validation=validation,
            retrieved_at_utc_method=retrieved_at_utc_method,
        ))
        paths[source_id] = path
    return paths


# ---------------------------------------------------------------------------
# Derived AOI subsets
# ---------------------------------------------------------------------------

def extract_osm_aoi(osm_pbf_path: Path, out_path: Path, parent_sha256: str) -> tuple[Path, dict, bool]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    west, south, east, north = ACQUISITION_AOI
    transform = {"tool": "osmium extract", "strategy": "complete_ways", "bbox": list(ACQUISITION_AOI)}

    def produce():
        subprocess.run([
            "osmium", "extract",
            "--bbox", f"{west},{south},{east},{north}",
            "--strategy", "complete_ways",
            "--set-bounds", "--overwrite",
            "--output", str(out_path),
            str(osm_pbf_path),
        ], check=True)

    return derive_or_reuse(out_path, parent_sha256, transform, produce, validate_fn=validate_osm_pbf)


def window_worldpop(src_path: Path, out_path: Path, parent_sha256: str) -> tuple[Path, dict, bool]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    west, south, east, north = ACQUISITION_AOI
    transform = {"tool": "gdal_translate", "op": "projwin_no_resample", "bbox": list(ACQUISITION_AOI)}

    def produce():
        subprocess.run([
            "gdal_translate", "-projwin", str(west), str(north), str(east), str(south),
            "-of", "COG", "-co", "COMPRESS=DEFLATE",
            str(src_path), str(out_path),
        ], check=True)

    def validate(p):
        return validate_raster(p, expected_crs="EPSG:4326", expected_nodata=-99999.0)

    return derive_or_reuse(out_path, parent_sha256, transform, produce, validate_fn=validate)


def unzip_ghspop(zip_path: Path, out_dir: Path, parent_sha256: str) -> tuple[Path, dict, bool]:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0_R8_C29.tif"
    transform = {"tool": "unzip", "member": out_path.name}

    def produce():
        subprocess.run(["unzip", "-o", "-q", str(zip_path), "-d", str(out_dir)], check=True)
        if not out_path.exists():
            candidates = list(out_dir.glob("*.tif"))
            if not candidates:
                raise RuntimeError(f"unzip of {zip_path} produced no .tif in {out_dir}")
            candidates[0].rename(out_path)

    def validate(p):
        return validate_raster(p, expected_nodata=-200.0)

    return derive_or_reuse(out_path, parent_sha256, transform, produce, validate_fn=validate)


def _add_derived_manifest_entry(manifest: RunManifest, source_id: str, provider: str, product: str,
                                 release: str, license_id: str, path: Path, parent_source_id: str,
                                 meta: dict, reused: bool):
    manifest.add(ManifestEntry(
        source_id=source_id, provider=provider, product=product, release=release,
        represented_at=release, retrieved_at_utc=meta["derived_at_utc"], source_uri=f"derived:{parent_source_id}",
        local_path=str(path), sha256=meta["sha256"], bytes=meta["bytes"], license_id=license_id,
        crs=meta.get("validation", {}).get("crs"), bounds=meta.get("validation", {}).get("bounds") or ACQUISITION_AOI,
        expected_assets=[source_id], present_assets=[source_id],
        notes="reused existing derived asset (parent checksum + transform + revalidation matched)" if reused else "derived this run",
        is_derived=True, parent_source_id=parent_source_id, parent_sha256=meta["parent_sha256"],
        transform=meta["transform"], validation=meta.get("validation"),
        retrieved_at_utc_method="derived_at_utc",
    ))


def acquire_overture(manifest: RunManifest, release: Optional[str]) -> dict:
    con = _connect()
    results = {}
    specs = [
        ("places", "place", AOI_DIR / "overture-places.parquet", "CDLA-Permissive-2.0_or_Apache-2.0_by_source"),
        ("transportation", "segment", AOI_DIR / "overture-transportation-segments.parquet", "ODbL-1.0"),
        ("transportation", "connector", AOI_DIR / "overture-transportation-connectors.parquet", "ODbL-1.0"),
    ]
    for theme, type_, out_path, license_id in specs:
        res, provenance = acquire_aoi_subset(theme, type_, ACQUISITION_AOI, out_path, release=release, con=con)
        results[f"{theme}_{type_}"] = out_path
        manifest.add(ManifestEntry(
            source_id=f"overture_{theme}_{type_}_{res.release}",
            provider="Overture Maps Foundation", product=f"{theme}/{type_}", release=res.release,
            represented_at=res.release, retrieved_at_utc=provenance.get("fetched_at_utc", "unknown"),
            source_uri=res.s3_path, local_path=str(out_path), sha256=provenance["sha256"],
            bytes=provenance["bytes"], license_id=license_id,
            crs="OGC:CRS84", bounds=list(ACQUISITION_AOI),
            expected_assets=[f"overture_{theme}_{type_}"], present_assets=[f"overture_{theme}_{type_}"],
            notes=(
                f"{res.row_count} rows, acquisition_mode={provenance['acquisition_mode']}, "
                f"reused={provenance['reused']}"
            ),
            validation={"schema_columns_checked": sorted(REQUIRED_COLUMNS.get(theme, {}).get(type_, set()))},
            retrieved_at_utc_method="overture_sidecar",
        ))
    con.close()
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reproducible acquisition for the Da Nang-Hoi An prototype.",
        epilog="Exactly one of --overture-release / --resolve-latest is required; "
               "there is no implicit latest-release mode.",
    )
    add_release_args(parser)
    return parser


def main(argv: Optional[list[str]] = None):
    args = build_parser().parse_args(argv)
    release = release_from_args(args)

    manifest = RunManifest()
    print(f"run_id: {manifest.run_id}")
    try:
        _run(manifest, release)
    except Exception as e:
        manifest.mark_failed(f"{type(e).__name__}: {e}")
        print(f"acquisition FAILED, manifest marked failed: {manifest.path}")
        raise


def _run(manifest: RunManifest, overture_release: Optional[str]) -> None:
    pinned_paths = acquire_pinned_assets(manifest)
    print("pinned assets acquired:", {k: str(v) for k, v in pinned_paths.items()})

    osm_sha = sha256_of(pinned_paths["osm_geofabrik_vnm_20260913"])
    osm_aoi, osm_aoi_meta, osm_aoi_new = extract_osm_aoi(pinned_paths["osm_geofabrik_vnm_20260913"], AOI_DIR / "osm-260913.osm.pbf", osm_sha)
    _add_derived_manifest_entry(manifest, "osm_aoi_extract_complete_ways", "derived/osmium", "AOI extract (complete_ways)",
                                 "vietnam-260913", "ODbL-1.0", osm_aoi, "osm_geofabrik_vnm_20260913", osm_aoi_meta, not osm_aoi_new)

    wp2025_sha = sha256_of(pinned_paths["worldpop_vnm_2025_cn_100m_r2025a_v1"])
    wp2025_aoi, wp2025_meta, wp2025_new = window_worldpop(pinned_paths["worldpop_vnm_2025_cn_100m_r2025a_v1"], AOI_DIR / "worldpop-2025-count.tif", wp2025_sha)
    _add_derived_manifest_entry(manifest, "worldpop_2025_aoi_clip", "derived/gdal_translate", "AOI clip (no resample)",
                                 "2025", "CC-BY-4.0", wp2025_aoi, "worldpop_vnm_2025_cn_100m_r2025a_v1", wp2025_meta, not wp2025_new)

    wp2020_sha = sha256_of(pinned_paths["worldpop_vnm_2020_cn_100m_r2025a_v1"])
    wp2020_aoi, wp2020_meta, wp2020_new = window_worldpop(pinned_paths["worldpop_vnm_2020_cn_100m_r2025a_v1"], AOI_DIR / "worldpop-2020-count.tif", wp2020_sha)
    _add_derived_manifest_entry(manifest, "worldpop_2020_aoi_clip", "derived/gdal_translate", "AOI clip (no resample)",
                                 "2020", "CC-BY-4.0", wp2020_aoi, "worldpop_vnm_2020_cn_100m_r2025a_v1", wp2020_meta, not wp2020_new)

    ghspop_sha = sha256_of(pinned_paths["ghspop_e2020_r2023a_r8_c29"])
    ghspop_native, ghspop_meta, ghspop_new = unzip_ghspop(pinned_paths["ghspop_e2020_r2023a_r8_c29"], Path("data/raw/ghsl/pop-e2020-r8-c29"), ghspop_sha)
    _add_derived_manifest_entry(manifest, "ghspop_e2020_native_extracted", "derived/unzip", "extracted native-grid GeoTIFF",
                                 "E2020", "CC-BY-4.0", ghspop_native, "ghspop_e2020_r2023a_r8_c29", ghspop_meta, not ghspop_new)

    print("AOI subsets ready:", osm_aoi, wp2025_aoi, wp2020_aoi, ghspop_native)

    overture_paths = acquire_overture(manifest, release=overture_release)
    print("overture AOI subsets:", {k: str(v) for k, v in overture_paths.items()})

    manifest_path = manifest.finalize()
    print(f"manifest written: {manifest_path}")


if __name__ == "__main__":
    main()
