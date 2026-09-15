"""Gate 2 source acquisition: the smallest reproducible per-AOI subsets.

Reuses the Gate 1 acquisition utilities (`download_pinned`, `derive_or_reuse`,
`RunManifest`) rather than re-implementing them. Two national rasters are
already pinned by Gate 1 (`run_acquisition.PINNED_ASSETS`) and are reused
here by checksum; Gate 2 additionally needs land cover and built-up surface,
which Gate 1 never downloaded.

Source roles follow the Gate 1 decision in `docs/source_validation_report.md`
§7 unchanged:

- roads / POI : OSM (Geofabrik Vietnam PBF, canonical). Overture is NOT
  unioned in and is not used for Gate 2 roads.
- population  : WorldPop Global 2 R2025A v1, 2025, 100 m constrained count.
- land cover  : ESA WorldCover 2021 v200, 10 m.
- built-up    : GHS-BUILT-S R2023A E2020, 100 m (Mollweide native).

Every derived subset keeps its source's NATIVE CRS and grid -- no
resampling, no reprojection, no value interpolation happens at acquisition
time. Units are reprojected onto the raster at measurement time instead, so
raster values are never altered between the publisher and the metric.

A halo is added around each AOI because the 1 km and 3 km buffer metrics
read data outside the AOI footprint; without it those buffers would be
silently truncated at the AOI edge and read as real sparsity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# This repository is importable under two roots by existing convention:
# `python -m src.ingestion.X` (repo root on the path) and the test suite's
# `pythonpath = ["src"]` (src on the path). Relative imports inside a
# package work under both; a cross-package import does not, so it is tried
# both ways rather than forcing one invocation style on callers.
try:  # pragma: no cover - exercised by whichever root is active
    from ..spatial.aoi import Aoi, aoi_checksum, load_aois
except ImportError:  # pragma: no cover
    from spatial.aoi import Aoi, aoi_checksum, load_aois
from .download import PinnedAsset, download_pinned
from .manifest import ManifestEntry, RunManifest, sha256_of
from .run_acquisition import PINNED_ASSETS, RAW_ASSET_LICENSES, derive_or_reuse
from .validators import validate_osm_pbf, validate_raster

RAW_DIR = Path("data/raw")
GATE2_AOI_DIR = Path("data/gate2/aoi_sources")

# 3 km is the widest buffer any Gate 2 metric uses (config/spatial.yaml
# buffers_m.regional); 0.5 km of margin absorbs projection differences
# between the AOI's metric CRS and the WGS84 bbox used for extraction.
HALO_KM = 3.5

WORLDCOVER_VERSION = "v200"
WORLDCOVER_YEAR = "2021"
WORLDCOVER_URL = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/"
    "{version}/{year}/map/ESA_WorldCover_10m_{year}_{version}_{tile}_Map.tif"
)
GHS_BUILT_S_RELEASE = "R2023A"
GHS_BUILT_S_EPOCH = "E2020"
GHS_BUILT_S_URL = (
    "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_BUILT_S_GLOBE_R2023A/"
    "GHS_BUILT_S_E2020_GLOBE_R2023A_54009_100/V1-0/tiles/"
    "GHS_BUILT_S_E2020_GLOBE_R2023A_54009_100_V1_0_R{row}_C{col}.zip"
)
MOLLWEIDE = "ESRI:54009"
# ESA WorldCover tiles are 3 deg x 3 deg, named by their SW corner.
WORLDCOVER_TILE_DEG = 3
# GHSL's global tiling scheme: 1,000 km x 1,000 km tiles in Mollweide, with
# R1/C1 at the top-left of the world extent.
GHSL_TILE_SIZE_M = 1_000_000
GHSL_ORIGIN_X = -18_041_000
GHSL_ORIGIN_Y = 9_000_000


# ---------------------------------------------------------------------------
# Tile identification (pure functions -- no network, directly testable)
# ---------------------------------------------------------------------------

def worldcover_tile_id(lat: float, lon: float) -> str:
    """ESA WorldCover tiles are 3 deg x 3 deg, named by their SW corner."""
    lat_floor = int(math.floor(lat / 3.0) * 3)
    lon_floor = int(math.floor(lon / 3.0) * 3)
    ns = "N" if lat_floor >= 0 else "S"
    ew = "E" if lon_floor >= 0 else "W"
    return f"{ns}{abs(lat_floor):02d}{ew}{abs(lon_floor):03d}"


def worldcover_tile_bounds(tile: str) -> tuple[float, float, float, float]:
    """(west, south, east, north) in EPSG:4326 of a WorldCover tile id."""
    lat = int(tile[1:3]) * (1 if tile[0] == "N" else -1)
    lon = int(tile[4:7]) * (1 if tile[3] == "E" else -1)
    return (float(lon), float(lat), float(lon + WORLDCOVER_TILE_DEG), float(lat + WORLDCOVER_TILE_DEG))


def worldcover_tiles_for_bbox(bbox: tuple[float, float, float, float]) -> set[str]:
    """Every WorldCover tile whose extent intersects the WGS84 bbox.

    Tiles are half-open on their upper/right edges, so a window whose north
    edge lies exactly on a tile line does not pull in the tile above it.
    The set is derived from the bbox EXTENT, not from its centre or its
    corners: a window is never served by only the tile its centre lies in.
    """
    w, s, e, n = bbox
    step = WORLDCOVER_TILE_DEG
    lat0 = int(math.floor(s / step) * step)
    lat1 = int(math.ceil(n / step) * step)
    lon0 = int(math.floor(w / step) * step)
    lon1 = int(math.ceil(e / step) * step)
    return {worldcover_tile_id(lat, lon)
            for lat in range(lat0, max(lat1, lat0 + step), step)
            for lon in range(lon0, max(lon1, lon0 + step), step)}


def ghsl_tile_id(lon: float, lat: float) -> tuple[int, int]:
    """(row, col) of the GHSL Mollweide tile containing this coordinate."""
    from pyproj import Transformer

    x, y = Transformer.from_crs("EPSG:4326", MOLLWEIDE, always_xy=True).transform(lon, lat)
    return _ghsl_tile_for_xy(x, y)


def _ghsl_tile_for_xy(x: float, y: float) -> tuple[int, int]:
    col = int((x - GHSL_ORIGIN_X) // GHSL_TILE_SIZE_M) + 1
    row = int((GHSL_ORIGIN_Y - y) // GHSL_TILE_SIZE_M) + 1
    return row, col


def ghsl_tile_bounds(row: int, col: int) -> tuple[float, float, float, float]:
    """(xmin, ymin, xmax, ymax) in Mollweide of a GHSL (row, col) tile."""
    xmin = GHSL_ORIGIN_X + (col - 1) * GHSL_TILE_SIZE_M
    ymax = GHSL_ORIGIN_Y - (row - 1) * GHSL_TILE_SIZE_M
    return (float(xmin), float(ymax - GHSL_TILE_SIZE_M), float(xmin + GHSL_TILE_SIZE_M), float(ymax))


def ghsl_tiles_for_bbox(bbox_mollweide: tuple[float, float, float, float]) -> set[tuple[int, int]]:
    """Every GHSL tile whose extent intersects a Mollweide bbox (half-open on
    the upper/right edges, like `worldcover_tiles_for_bbox`)."""
    xmin, ymin, xmax, ymax = bbox_mollweide
    t = GHSL_TILE_SIZE_M
    c0 = int(math.floor((xmin - GHSL_ORIGIN_X) / t))
    c1 = int(math.ceil((xmax - GHSL_ORIGIN_X) / t))
    r0 = int(math.floor((GHSL_ORIGIN_Y - ymax) / t))
    r1 = int(math.ceil((GHSL_ORIGIN_Y - ymin) / t))
    return {(r + 1, c + 1)
            for r in range(r0, max(r1, r0 + 1))
            for c in range(c0, max(c1, c0 + 1))}


def window_inside_union(window: tuple[float, float, float, float],
                        extents: list[tuple[float, float, float, float]],
                        tolerance: float = 0.0) -> bool:
    """True when the requested window lies entirely inside the union of the
    given extents (all in one CRS). `tolerance` shrinks the window by that
    amount on every side before testing, to absorb float noise in bounds
    read back from a raster header -- never to excuse a missing tile."""
    from shapely.geometry import box
    from shapely.ops import unary_union

    if not extents:
        return False
    w, s, e, n = window
    win = box(w + tolerance, s + tolerance, e - tolerance, n - tolerance)
    return unary_union([box(*x) for x in extents]).covers(win)


def halo_bbox(aoi: Aoi, halo_km: float = HALO_KM) -> tuple[float, float, float, float]:
    """AOI bbox grown by `halo_km` on every side, in EPSG:4326.

    The growth is computed in the AOI's metric CRS so it is a true distance
    on the ground, then converted back -- not a naive degree offset, which
    would be a different distance in x than in y.
    """
    from pyproj import Transformer
    from shapely.geometry import box
    from shapely.ops import transform as shapely_transform

    fwd = Transformer.from_crs("EPSG:4326", aoi.metric_crs, always_xy=True).transform
    back = Transformer.from_crs(aoi.metric_crs, "EPSG:4326", always_xy=True).transform
    grown = shapely_transform(back, shapely_transform(fwd, aoi.polygon).buffer(halo_km * 1000.0, join_style=2))
    w, s, e, n = grown.bounds
    # Round outward to a stable 4-decimal grid so the bbox string in the
    # transform record is reproducible regardless of float formatting.
    r = 4
    return (math.floor(w * 10**r) / 10**r, math.floor(s * 10**r) / 10**r,
            math.ceil(e * 10**r) / 10**r, math.ceil(n * 10**r) / 10**r)


def halo_bbox_in(aoi: Aoi, crs: str, halo_km: float = HALO_KM) -> tuple[float, float, float, float]:
    """The halo bbox expressed in `crs` -- the bounds of the WGS84 halo box
    reprojected as a polygon, so a Mollweide-native raster is windowed in
    Mollweide rather than being warped to WGS84."""
    from pyproj import Transformer
    from shapely.geometry import box
    from shapely.ops import transform as shapely_transform

    wgs_bbox = halo_bbox(aoi, halo_km)
    if crs == "EPSG:4326":
        return wgs_bbox
    fwd = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
    return shapely_transform(fwd, box(*wgs_bbox)).bounds


def required_tiles(aois: list[Aoi], halo_km: float = HALO_KM) -> tuple[set[str], set[tuple[int, int]]]:
    """(worldcover tile ids, ghsl (row, col) tiles) intersecting every AOI
    halo -- by extent, so a halo straddling a tile line needs both tiles."""
    wc, gh = set(), set()
    for aoi in aois:
        wc |= worldcover_tiles_for_bbox(halo_bbox(aoi, halo_km))
        gh |= ghsl_tiles_for_bbox(halo_bbox_in(aoi, MOLLWEIDE, halo_km))
    return wc, gh


def aoi_tiles(aoi: Aoi, halo_km: float = HALO_KM) -> tuple[set[str], set[tuple[int, int]]]:
    """Tiles one AOI's halo needs, for both tiled products."""
    return required_tiles([aoi], halo_km)


# ---------------------------------------------------------------------------
# National assets (download once, shared by every AOI)
# ---------------------------------------------------------------------------

@dataclass
class NationalAsset:
    source_id: str
    path: Path
    provider: str
    product: str
    release: str
    license_id: str
    url: str
    retrieved_at_utc: str
    retrieved_at_utc_method: str
    sha256: str
    bytes: int
    validation: dict


def _record_national(manifest: RunManifest, asset: NationalAsset, notes: str) -> None:
    manifest.add(ManifestEntry(
        source_id=asset.source_id, provider=asset.provider, product=asset.product,
        release=asset.release, represented_at=asset.release,
        retrieved_at_utc=asset.retrieved_at_utc, source_uri=asset.url,
        local_path=str(asset.path), sha256=asset.sha256, bytes=asset.bytes,
        license_id=asset.license_id, crs=asset.validation.get("crs"),
        bounds=asset.validation.get("bounds"),
        expected_assets=[asset.source_id], present_assets=[asset.source_id],
        notes=notes, validation=asset.validation,
        retrieved_at_utc_method=asset.retrieved_at_utc_method,
    ))


def acquire_gate1_reused(manifest: RunManifest, source_id: str) -> NationalAsset:
    """Reuse a nationally-pinned Gate 1 asset by checksum. `download_pinned`
    refuses to reuse anything whose bytes/sha256 do not match the pin, so
    this cannot quietly pick up a changed file."""
    spec = PINNED_ASSETS[source_id]
    path, downloaded, retrieved_at, method = download_pinned(spec)
    provider, product, release, license_id = RAW_ASSET_LICENSES[source_id]
    validation = validate_raster(path) if path.suffix == ".tif" else validate_osm_pbf(path)
    asset = NationalAsset(
        source_id=source_id, path=path, provider=provider, product=product, release=release,
        license_id=license_id, url=spec.url, retrieved_at_utc=retrieved_at,
        retrieved_at_utc_method=method, sha256=sha256_of(path), bytes=path.stat().st_size,
        validation=validation,
    )
    _record_national(manifest, asset, "downloaded this run" if downloaded else
                     f"reused Gate 1 pinned asset (checksum-confirmed); retrieved_at_utc_method={method}")
    return asset


def acquire_worldcover_tile(manifest: RunManifest, tile: str) -> NationalAsset:
    url = WORLDCOVER_URL.format(version=WORLDCOVER_VERSION, year=WORLDCOVER_YEAR, tile=tile)
    source_id = f"esa_worldcover_{WORLDCOVER_YEAR}_{WORLDCOVER_VERSION}_{tile}"
    dest = RAW_DIR / "worldcover" / f"ESA_WorldCover_10m_{WORLDCOVER_YEAR}_{WORLDCOVER_VERSION}_{tile}_Map.tif"
    path, downloaded, retrieved_at, method = download_pinned(
        PinnedAsset(source_id=source_id, url=url, dest=dest, max_time_s=900, retries=4, retry_delay_s=10)
    )
    validation = validate_raster(path)
    asset = NationalAsset(
        source_id=source_id, path=path, provider="ESA WorldCover consortium",
        product=f"ESA WorldCover 10 m {WORLDCOVER_YEAR} {WORLDCOVER_VERSION}",
        release=f"{WORLDCOVER_YEAR}_{WORLDCOVER_VERSION}", license_id="CC-BY-4.0", url=url,
        retrieved_at_utc=retrieved_at, retrieved_at_utc_method=method,
        sha256=sha256_of(path), bytes=path.stat().st_size, validation=validation,
    )
    _record_national(manifest, asset, "downloaded this run" if downloaded else "reused existing verified file")
    return asset


def acquire_ghs_built_s_tile(manifest: RunManifest, row: int, col: int) -> NationalAsset:
    url = GHS_BUILT_S_URL.format(row=row, col=col)
    source_id = f"ghs_built_s_{GHS_BUILT_S_EPOCH.lower()}_{GHS_BUILT_S_RELEASE.lower()}_r{row}_c{col}"
    zip_dest = RAW_DIR / "ghsl" / f"GHS_BUILT_S_{GHS_BUILT_S_EPOCH}_GLOBE_{GHS_BUILT_S_RELEASE}_54009_100_V1_0_R{row}_C{col}.zip"
    zip_path, downloaded, retrieved_at, method = download_pinned(
        # This JRC endpoint is slow to first byte; Gate 1 measured 45-60 s.
        PinnedAsset(source_id=source_id, url=url, dest=zip_dest, max_time_s=600, retries=5, retry_delay_s=15)
    )
    zip_sha = sha256_of(zip_path)
    asset_zip = NationalAsset(
        source_id=source_id, path=zip_path, provider="European Commission JRC GHSL",
        product=f"GHS-BUILT-S {GHS_BUILT_S_RELEASE} 100 m", release=GHS_BUILT_S_EPOCH,
        license_id="CC-BY-4.0", url=url, retrieved_at_utc=retrieved_at,
        retrieved_at_utc_method=method, sha256=zip_sha, bytes=zip_path.stat().st_size,
        validation={"container": "zip"},
    )
    _record_national(manifest, asset_zip, "downloaded this run" if downloaded else "reused existing verified file")

    out_dir = RAW_DIR / "ghsl" / f"built-s-{GHS_BUILT_S_EPOCH.lower()}-r{row}-c{col}"
    out_dir.mkdir(parents=True, exist_ok=True)
    tif_path = out_dir / f"GHS_BUILT_S_{GHS_BUILT_S_EPOCH}_GLOBE_{GHS_BUILT_S_RELEASE}_54009_100_V1_0_R{row}_C{col}.tif"
    transform = {"tool": "unzip", "member": tif_path.name}

    def produce():
        subprocess.run(["unzip", "-o", "-q", str(zip_path), "-d", str(out_dir)], check=True)
        if not tif_path.exists():
            candidates = list(out_dir.glob("*.tif"))
            if not candidates:
                raise RuntimeError(f"unzip of {zip_path} produced no .tif in {out_dir}")
            candidates[0].rename(tif_path)

    path, meta, created = derive_or_reuse(tif_path, zip_sha, transform, produce, validate_fn=validate_raster)
    extracted_id = f"{source_id}_extracted"
    manifest.add(ManifestEntry(
        source_id=extracted_id, provider="derived/unzip", product="extracted native-grid GeoTIFF",
        release=GHS_BUILT_S_EPOCH, represented_at=GHS_BUILT_S_EPOCH,
        retrieved_at_utc=meta["derived_at_utc"], source_uri=f"derived:{source_id}",
        local_path=str(path), sha256=meta["sha256"], bytes=meta["bytes"], license_id="CC-BY-4.0",
        crs=meta.get("validation", {}).get("crs"), bounds=meta.get("validation", {}).get("bounds"),
        expected_assets=[extracted_id], present_assets=[extracted_id],
        notes="derived this run" if created else "reused existing derived asset (parent checksum + transform + revalidation matched)",
        is_derived=True, parent_source_id=source_id, parent_sha256=zip_sha,
        transform=transform, validation=meta.get("validation"),
        retrieved_at_utc_method="derived_at_utc",
    ))
    return NationalAsset(
        source_id=extracted_id, path=path, provider="European Commission JRC GHSL",
        product=f"GHS-BUILT-S {GHS_BUILT_S_RELEASE} 100 m", release=GHS_BUILT_S_EPOCH,
        license_id="CC-BY-4.0", url=f"derived:{source_id}", retrieved_at_utc=meta["derived_at_utc"],
        retrieved_at_utc_method="derived_at_utc", sha256=meta["sha256"], bytes=meta["bytes"],
        validation=meta.get("validation", {}),
    )


# ---------------------------------------------------------------------------
# Per-AOI subsets
# ---------------------------------------------------------------------------

class TileCoverageError(RuntimeError):
    """The requested window is not fully served by the supplied source tiles."""


def _record_derived(manifest: RunManifest, source_id: str, parents: list[NationalAsset], path: Path,
                    meta: dict, created: bool, aoi: Aoi, product: str) -> dict:
    primary = parents[0]
    manifest.add(ManifestEntry(
        source_id=source_id, provider=f"derived/{meta['transform']['tool']}", product=product,
        release=primary.release, represented_at=primary.release,
        retrieved_at_utc=meta["derived_at_utc"], source_uri=f"derived:{primary.source_id}",
        local_path=str(path), sha256=meta["sha256"], bytes=meta["bytes"],
        license_id=primary.license_id,
        crs=meta.get("validation", {}).get("crs"),
        bounds=meta.get("validation", {}).get("bounds") or list(halo_bbox(aoi)),
        expected_assets=[source_id], present_assets=[source_id],
        notes=(f"aoi={aoi.id}; aoi_checksum={aoi_checksum(aoi)}; "
               + ("derived this run" if created else "reused (parent checksum + transform + revalidation matched)")),
        is_derived=True, parent_source_id=primary.source_id, parent_sha256=meta["parent_sha256"],
        parent_source_ids=[a.source_id for a in parents],
        transform=meta["transform"], validation=meta.get("validation"),
        retrieved_at_utc_method="derived_at_utc",
    ))
    return {"source_id": source_id, "path": str(path), "sha256": meta["sha256"],
            "bytes": meta["bytes"], "parent_source_id": primary.source_id,
            "parent_source_ids": [a.source_id for a in parents],
            "transform": meta["transform"], "coverage": meta.get("validation", {}).get("coverage"),
            "ingest_status": "ok"}


def _projwin(src: Path, out: Path, bbox: tuple[float, float, float, float],
             extra: Optional[list[str]] = None) -> None:
    w, s, e, n = bbox
    subprocess.run(
        ["gdal_translate", "-projwin", str(w), str(n), str(e), str(s),
         "-of", "COG", "-co", "COMPRESS=DEFLATE", *(extra or []), str(src), str(out)],
        check=True, capture_output=True,
    )


def _mosaic_projwin(srcs: list[Path], out: Path, bbox: tuple[float, float, float, float]) -> None:
    """Windowed clip from a VRT mosaic of `srcs`. The tiles of a global
    product share one grid, so the VRT is a pure index over them: no pixel
    is resampled, and a window straddling a tile line reads both tiles
    instead of being padded with NoData where the second tile should be."""
    vrt = out.with_suffix(".mosaic.vrt")
    try:
        subprocess.run(["gdalbuildvrt", "-q", "-overwrite", str(vrt), *map(str, srcs)],
                       check=True, capture_output=True)
        _projwin(vrt, out, bbox)
    finally:
        vrt.unlink(missing_ok=True)


def _parents_digest(parents: list[NationalAsset]) -> str:
    """One checksum standing for the ordered set of parent tiles, so
    `derive_or_reuse` regenerates the clip if the tile set changes."""
    if len(parents) == 1:
        return parents[0].sha256
    return hashlib.sha256("+".join(a.sha256 for a in parents).encode()).hexdigest()


def _edge_nodata_bands(arr, nodata) -> dict:
    """Leading/trailing rows and columns that are entirely NoData. Recorded
    as a diagnostic on every clip; a truncated window shows up here as a
    solid band on one side."""
    import numpy as np

    if nodata is None:
        return {"top": 0, "bottom": 0, "left": 0, "right": 0}
    nd = (arr == nodata)
    rows_full = nd.all(axis=1)
    cols_full = nd.all(axis=0)

    def _lead(v):
        n = 0
        for flag in v:
            if not flag:
                break
            n += 1
        return int(n)

    return {"top": _lead(rows_full), "bottom": _lead(rows_full[::-1]),
            "left": _lead(cols_full), "right": _lead(cols_full[::-1])}


def validate_clip_coverage(path: Path, window: tuple[float, float, float, float],
                           expected_crs: Optional[str], expected_nodata: Optional[float],
                           tile_extents: list[tuple[float, float, float, float]]) -> dict:
    """Proves the clip is a complete, unresampled window of its sources:

    - it opens with the expected CRS and NoData;
    - the requested window lies inside the union of the source tile
      extents (a geometric test, independent of what gdal wrote);
    - the clip's own bounds cover the requested window to within one
      pixel of grid snapping on each side, so no part of the window fell
      outside the produced file.

    Returns the observed metadata plus the edge-NoData diagnostic. Raises
    `TileCoverageError` on any failure.
    """
    import rasterio

    with rasterio.open(path) as src:
        crs = src.crs.to_string() if src.crs else None
        nodata = src.nodata
        bounds = tuple(src.bounds)
        res = (abs(src.transform.a), abs(src.transform.e))
        edge = _edge_nodata_bands(src.read(1), nodata)
        width, height = src.width, src.height

    if expected_crs is not None and crs != expected_crs:
        raise TileCoverageError(f"{path}: CRS {crs!r} != source CRS {expected_crs!r}")
    if expected_nodata is not None:
        if nodata is None or abs(float(nodata) - float(expected_nodata)) > 1e-6:
            raise TileCoverageError(f"{path}: NoData {nodata!r} != source NoData {expected_nodata!r}")
    if not window_inside_union(window, tile_extents):
        raise TileCoverageError(
            f"{path}: requested window {window} is not inside the union of the source tile "
            f"extents {tile_extents}; a tile is missing and the clip would be silently padded")
    w, s, e, n = window
    bw, bs, be, bn = bounds
    tol_x, tol_y = res[0] * 1.001, res[1] * 1.001
    covered = (bw <= w + tol_x) and (bs <= s + tol_y) and (be >= e - tol_x) and (bn >= n - tol_y)
    if not covered:
        raise TileCoverageError(
            f"{path}: clip bounds {bounds} do not cover the requested window {window} "
            f"(tolerance one pixel {res}); the window was truncated")
    return {"crs": crs, "nodata": nodata, "bounds": list(bounds), "width": width, "height": height,
            "resolution": list(res), "requested_window": list(window),
            "window_inside_tile_union": True, "window_covered_by_clip": True,
            "edge_full_nodata": edge, "source_tile_extents": [list(x) for x in tile_extents]}


def _tile_extent(asset: NationalAsset) -> tuple[float, float, float, float]:
    b = asset.validation.get("bounds")
    if not b:
        raise TileCoverageError(f"{asset.source_id}: no bounds recorded for the source raster")
    return tuple(float(v) for v in b)


def clip_osm(aoi: Aoi, parent: NationalAsset, manifest: RunManifest) -> dict:
    out = GATE2_AOI_DIR / aoi.id / "osm.osm.pbf"
    out.parent.mkdir(parents=True, exist_ok=True)
    bbox = halo_bbox(aoi)
    w, s, e, n = bbox
    transform = {"tool": "osmium extract", "strategy": "complete_ways",
                 "bbox": list(bbox), "halo_km": HALO_KM}

    def produce():
        subprocess.run(
            ["osmium", "extract", "--bbox", f"{w},{s},{e},{n}", "--strategy", "complete_ways",
             "--set-bounds", "--overwrite", "--output", str(out), str(parent.path)],
            check=True, capture_output=True,
        )

    path, meta, created = derive_or_reuse(out, parent.sha256, transform, produce, validate_fn=validate_osm_pbf)
    return _record_derived(manifest, f"gate2_{aoi.id}_osm", [parent], path, meta, created, aoi,
                           "AOI extract (complete_ways, halo)")


def clip_raster(aoi: Aoi, parents: list[NationalAsset], manifest: RunManifest, name: str,
                product: str, bbox_crs: str = "EPSG:4326",
                expected_nodata: Optional[float] = None,
                required_tile_ids: Optional[set] = None) -> dict:
    """Windowed read only -- NO resampling and NO reprojection.

    `parents` is EVERY source raster whose extent intersects the halo (one
    for a national product, one or more tiles for a tiled one). A single
    parent is windowed directly; several are mosaicked through a VRT first.
    `bbox_crs` says which CRS the window coordinates are given in, so a
    Mollweide-native raster is windowed in Mollweide rather than being
    warped to WGS84. `required_tile_ids`, when given, is the set of tile
    source ids the halo extent needs; a missing one is an error before any
    clip is attempted, never a NoData band in the output.
    """
    if not parents:
        raise TileCoverageError(f"{aoi.id}/{name}: no source raster supplied")
    if required_tile_ids is not None:
        missing = set(required_tile_ids) - {a.source_id for a in parents}
        if missing:
            raise TileCoverageError(
                f"{aoi.id}/{name}: halo needs tiles {sorted(required_tile_ids)} but "
                f"{sorted(missing)} were not supplied")

    out = GATE2_AOI_DIR / aoi.id / f"{name}.tif"
    out.parent.mkdir(parents=True, exist_ok=True)
    wgs_bbox = halo_bbox(aoi)
    bbox = halo_bbox_in(aoi, bbox_crs)
    tile_extents = [_tile_extent(a) for a in parents]
    if not window_inside_union(bbox, tile_extents):
        raise TileCoverageError(
            f"{aoi.id}/{name}: requested window {bbox} ({bbox_crs}) is not inside the union of "
            f"the supplied source extents {[a.source_id for a in parents]}")

    source_crs = parents[0].validation.get("crs")
    source_nodata = parents[0].validation.get("nodata")
    transform = {"tool": "gdal_translate",
                 "op": "projwin_no_resample" if len(parents) == 1 else "vrt_mosaic_projwin_no_resample",
                 "bbox": [round(v, 4) for v in bbox], "bbox_crs": bbox_crs,
                 "source_bbox_wgs84": list(wgs_bbox), "halo_km": HALO_KM,
                 "source_tiles": [a.source_id for a in parents]}

    def produce():
        if len(parents) == 1:
            _projwin(parents[0].path, out, bbox)
        else:
            _mosaic_projwin([a.path for a in parents], out, bbox)

    def validate(p):
        meta = validate_raster(p, expected_nodata=expected_nodata)
        meta["coverage"] = validate_clip_coverage(
            p, bbox, source_crs, expected_nodata if expected_nodata is not None else source_nodata,
            tile_extents)
        return meta

    path, meta, created = derive_or_reuse(out, _parents_digest(parents), transform, produce, validate_fn=validate)
    return _record_derived(manifest, f"gate2_{aoi.id}_{name}", parents, path, meta, created, aoi, product)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def acquire_all(aoi_ids: Optional[list[str]] = None, manifest: Optional[RunManifest] = None) -> dict:
    aois = [a for a in load_aois() if aoi_ids is None or a.id in aoi_ids]
    if not aois:
        raise ValueError(f"no AOIs matched {aoi_ids}")
    manifest = manifest or RunManifest()

    osm_national = acquire_gate1_reused(manifest, "osm_geofabrik_vnm_20260913")
    worldpop = acquire_gate1_reused(manifest, "worldpop_vnm_2025_cn_100m_r2025a_v1")

    wc_tiles, gh_tiles = required_tiles(aois)
    worldcover = {t: acquire_worldcover_tile(manifest, t) for t in sorted(wc_tiles)}
    built_s = {rc: acquire_ghs_built_s_tile(manifest, *rc) for rc in sorted(gh_tiles)}

    per_aoi: dict[str, dict] = {}
    for aoi in aois:
        # Every tile the halo EXTENT intersects, not the one under its
        # centre: a halo straddling a tile line is served by both tiles.
        wc_needed, gh_needed = aoi_tiles(aoi)
        wc_assets = [worldcover[t] for t in sorted(wc_needed)]
        gh_assets = [built_s[rc] for rc in sorted(gh_needed)]
        per_aoi[aoi.id] = {
            "aoi_id": aoi.id, "context": aoi.context, "metric_crs": aoi.metric_crs,
            "aoi_checksum": aoi_checksum(aoi), "halo_bbox_wgs84": list(halo_bbox(aoi)),
            "halo_km": HALO_KM,
            "acquisition_run_id": manifest.run_id, "manifest_path": str(manifest.path),
            "roads_poi": clip_osm(aoi, osm_national, manifest),
            "population": clip_raster(aoi, [worldpop], manifest, "worldpop2025",
                                      "AOI clip (no resample)", expected_nodata=-99999.0),
            "land_cover": clip_raster(aoi, wc_assets, manifest, "worldcover",
                                      "AOI clip (no resample; VRT mosaic when the halo spans tiles)",
                                      required_tile_ids={worldcover[t].source_id for t in wc_needed}),
            "built_up": clip_raster(aoi, gh_assets, manifest, "ghs_built_s",
                                    "AOI clip (no resample, Mollweide native; VRT mosaic when the halo spans tiles)",
                                    bbox_crs=MOLLWEIDE,
                                    required_tile_ids={built_s[rc].source_id for rc in gh_needed}),
        }
        print(f"  {aoi.id}: sources ready "
              f"(worldcover tiles {sorted(wc_needed)}, ghsl tiles {sorted(gh_needed)})")

    return {"manifest_path": str(manifest.path), "run_id": manifest.run_id, "aois": per_aoi}


def merge_source_index(existing: Optional[dict], result: dict) -> dict:
    """Update only the AOIs acquired this run and keep every other AOI's
    entry as it was. Each AOI entry names the acquisition run and manifest
    it came from, so a partial re-acquisition never orphans the rest."""
    merged = {"manifest_path": result["manifest_path"], "run_id": result["run_id"],
              "aois": dict((existing or {}).get("aois", {}))}
    for aoi_id, entry in (existing or {}).get("aois", {}).items():
        entry = dict(entry)
        entry.setdefault("acquisition_run_id", (existing or {}).get("run_id"))
        entry.setdefault("manifest_path", (existing or {}).get("manifest_path"))
        merged["aois"][aoi_id] = entry
    merged["aois"].update(result["aois"])
    return merged


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Acquire the per-AOI Gate 2 source subsets.")
    parser.add_argument("--aoi", action="append", default=None,
                        help="AOI id (repeatable). Default: every AOI in config/spatial.yaml.")
    parser.add_argument("--out", type=Path, default=GATE2_AOI_DIR / "gate2_source_index.json")
    args = parser.parse_args(argv)

    manifest = RunManifest()
    print(f"run_id: {manifest.run_id}")
    try:
        result = acquire_all(args.aoi, manifest)
    except Exception as e:
        manifest.mark_failed(f"{type(e).__name__}: {e}")
        print(f"acquisition FAILED, manifest marked failed: {manifest.path}")
        raise
    manifest.finalize()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(args.out.read_text()) if args.out.exists() else None
    args.out.write_text(json.dumps(merge_source_index(existing, result), indent=2, sort_keys=True))
    print(f"manifest: {manifest.path}\nindex: {args.out}")


if __name__ == "__main__":
    main()
