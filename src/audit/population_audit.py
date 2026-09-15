"""Population audit: WorldPop 2025 (primary candidate), WorldPop 2020 vs.
GHS-POP 2020 (same-epoch validation pair), per COWORK_START_PROMPT.md.

Both count rasters are regridded onto a common 1 km EPSG:32649 grid using
area-conserving (`Resampling.sum`) resampling so that totals are not
silently distorted -- summing a *count* raster with nearest-neighbor or
bilinear resampling would double-count or drop population. Native grids are
read directly from `data/raw/` / the AOI-clipped GeoTIFFs, never averaged
against each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject
from scipy import stats as sstats

METRIC_CRS = "EPSG:32649"
GRID_RESOLUTION_M = 1000.0


def _target_grid(bounds_wgs84: tuple, resolution_m: float = GRID_RESOLUTION_M):
    """Return (transform, width, height) for a regular `resolution_m` grid
    in METRIC_CRS covering `bounds_wgs84` (west, south, east, north)."""
    west, south, east, north = bounds_wgs84
    transform, width, height = calculate_default_transform(
        "EPSG:4326", METRIC_CRS, 10, 10, west, south, east, north,
        resolution=(resolution_m, resolution_m),
    )
    return transform, width, height


def _reproject_sum(src_path: Path, dst_transform, dst_width: int, dst_height: int, src_nodata: float | None = None) -> np.ndarray:
    with rasterio.open(src_path) as src:
        nodata = src_nodata if src_nodata is not None else src.nodata
        dst = np.zeros((dst_height, dst_width), dtype="float64")
        reproject(
            source=rasterio.band(src, 1),
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=nodata,
            dst_transform=dst_transform,
            dst_crs=METRIC_CRS,
            dst_nodata=np.nan,
            resampling=Resampling.sum,
        )
    return dst


@dataclass
class RasterGridResult:
    label: str
    grid: np.ndarray  # NaN = no valid source coverage
    total_population: float
    non_zero_fraction: float
    quantiles: dict


def summarize_grid(grid: np.ndarray, label: str) -> RasterGridResult:
    valid = grid[~np.isnan(grid)]
    total = float(np.nansum(grid))
    non_zero_fraction = float((valid > 0).mean()) if valid.size else float("nan")
    q = {str(p): float(np.nanpercentile(valid, p)) for p in [10, 25, 50, 75, 90, 99]} if valid.size else {}
    return RasterGridResult(label=label, grid=grid, total_population=total, non_zero_fraction=non_zero_fraction, quantiles=q)


@dataclass
class PopulationComparison:
    worldpop2020: RasterGridResult
    ghspop2020: RasterGridResult
    common_valid_cell_count: int
    spearman_rho: float
    spearman_p: float
    abs_diff_mean: float
    abs_diff_median: float
    rel_diff_median: float
    rel_diff_undefined_fraction: float
    strata: dict = field(default_factory=dict)


NEAR_ZERO_EPS = 1.0  # people; below this in BOTH rasters, relative difference is undefined, not a huge outlier


def safe_relative_difference(a: np.ndarray, b: np.ndarray, eps: float = NEAR_ZERO_EPS) -> tuple[np.ndarray, np.ndarray]:
    """Relative difference |a-b| / max(a,b), except where max(a,b) < eps --
    there it is undefined (NaN), not a spuriously huge or divide-by-zero
    value, because a 1-person absolute difference on a near-empty cell
    would otherwise register as a 1000% "error." Returns (rel_diff,
    near_zero_mask)."""
    denom = np.maximum(a, b)
    near_zero_mask = denom < eps
    with np.errstate(invalid="ignore", divide="ignore"):
        rel_diff = np.where(near_zero_mask, np.nan, np.abs(a - b) / np.where(denom == 0, np.nan, denom))
    return rel_diff, near_zero_mask


def compare_worldpop_ghspop_2020(
    worldpop2020_path: Path,
    ghspop2020_path: Path,
    bounds_wgs84: tuple,
    resolution_m: float = GRID_RESOLUTION_M,
) -> PopulationComparison:
    transform, width, height = _target_grid(bounds_wgs84, resolution_m)

    wp_grid = _reproject_sum(worldpop2020_path, transform, width, height, src_nodata=-99999.0)
    ghs_grid = _reproject_sum(ghspop2020_path, transform, width, height, src_nodata=-200.0)

    wp_result = summarize_grid(wp_grid, "worldpop_2020")
    ghs_result = summarize_grid(ghs_grid, "ghspop_2020_e2020")

    both_valid = (~np.isnan(wp_grid)) & (~np.isnan(ghs_grid))
    wp_v = wp_grid[both_valid]
    ghs_v = ghs_grid[both_valid]

    if wp_v.size >= 2:
        rho, p = sstats.spearmanr(wp_v, ghs_v)
    else:
        rho, p = float("nan"), float("nan")

    abs_diff = np.abs(wp_v - ghs_v)
    rel_diff, near_zero_mask = safe_relative_difference(wp_v, ghs_v)

    strata = _stratify(wp_v, ghs_v, near_zero_mask)

    return PopulationComparison(
        worldpop2020=wp_result,
        ghspop2020=ghs_result,
        common_valid_cell_count=int(both_valid.sum()),
        spearman_rho=float(rho),
        spearman_p=float(p),
        abs_diff_mean=float(np.mean(abs_diff)) if abs_diff.size else float("nan"),
        abs_diff_median=float(np.median(abs_diff)) if abs_diff.size else float("nan"),
        rel_diff_median=float(np.nanmedian(rel_diff)) if rel_diff.size else float("nan"),
        rel_diff_undefined_fraction=float(near_zero_mask.mean()) if near_zero_mask.size else float("nan"),
        strata=strata,
    )


def _stratify(wp_v: np.ndarray, ghs_v: np.ndarray, near_zero_mask: np.ndarray) -> dict:
    """Strata are defined from WorldPop's own density distribution (no
    external land-cover source is in scope for this task): top decile of
    non-zero cells = dense_urban proxy, next ~30 percentile = peri_urban
    proxy, remainder (incl. zero) = sparse proxy. Documented as a
    self-referential proxy, not an independent land-use classification.
    """
    strata = {}
    non_zero = wp_v[wp_v > 0]
    if non_zero.size < 10:
        return strata
    p90 = np.percentile(non_zero, 90)
    p60 = np.percentile(non_zero, 60)

    masks = {
        "dense_urban_proxy": wp_v >= p90,
        "peri_urban_proxy": (wp_v >= p60) & (wp_v < p90),
        "sparse_proxy": wp_v < p60,
    }
    for name, mask in masks.items():
        if mask.sum() == 0:
            continue
        abs_diff = np.abs(wp_v[mask] - ghs_v[mask])
        denom = np.maximum(wp_v[mask], ghs_v[mask])
        nz = denom < NEAR_ZERO_EPS
        rel = np.where(nz, np.nan, abs_diff / np.where(denom == 0, np.nan, denom))
        strata[name] = {
            "cell_count": int(mask.sum()),
            "worldpop_total": float(wp_v[mask].sum()),
            "ghspop_total": float(ghs_v[mask].sum()),
            "abs_diff_median": float(np.median(abs_diff)),
            "rel_diff_median": float(np.nanmedian(rel)) if not np.all(np.isnan(rel)) else None,
        }
    return strata


def summarize_worldpop2025(worldpop2025_path: Path, bounds_wgs84: tuple, resolution_m: float = GRID_RESOLUTION_M) -> RasterGridResult:
    transform, width, height = _target_grid(bounds_wgs84, resolution_m)
    grid = _reproject_sum(worldpop2025_path, transform, width, height, src_nodata=-99999.0)
    return summarize_grid(grid, "worldpop_2025")


def native_grid_total(path: Path, nodata: float, bounds_wgs84: tuple | None = None) -> dict:
    """Sum of valid pixels on the source's OWN native grid, with no
    reprojection -- the "before" figure for a conservation check.

    If `bounds_wgs84` is given, the read is windowed to that extent
    (transformed into the raster's own CRS first) rather than reading the
    whole file. This matters for a source like GHS-POP, whose "native"
    file for this project is a full 1000km x 1000km global tile, NOT
    pre-clipped to the AOI the way the WorldPop AOI clips are -- comparing
    a whole-tile total against an AOI-only regridded total would silently
    compare two different spatial extents and produce a meaningless
    "conservation error" dominated by that extent mismatch, not by
    resampling. Windowing here first makes every source's native total
    cover the SAME extent as its regridded total.
    """
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    with rasterio.open(path) as src:
        if bounds_wgs84 is not None:
            west, south, east, north = transform_bounds("EPSG:4326", src.crs, *bounds_wgs84)
            window = from_bounds(west, south, east, north, transform=src.transform).round_offsets().round_lengths()
            window = window.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
            arr = src.read(1, window=window).astype("float64")
        else:
            arr = src.read(1).astype("float64")
        mask = arr != nodata
        if src.nodata is not None:
            mask &= ~np.isclose(arr, src.nodata)
        total = float(arr[mask].sum())
        valid_px = int(mask.sum())
    return {"native_total": total, "native_valid_pixel_count": valid_px, "native_crs": str(src.crs)}


def conservation_report(path: Path, bounds_wgs84: tuple, nodata: float, resolution_m: float = GRID_RESOLUTION_M) -> dict:
    """Compares the AOI-windowed native-grid total (no resampling) against
    the total after regridding onto the common 1km EPSG:32649 grid with
    Resampling.sum, for ONE source's actual AOI raster (not a synthetic
    test fixture) -- the conservation-error evidence the review asked for,
    per source. Both totals cover the SAME extent (see native_grid_total),
    so any remaining difference is attributable to the resampling step
    itself, not to a differing spatial extent between the two totals.
    """
    native = native_grid_total(path, nodata, bounds_wgs84=bounds_wgs84)
    transform, width, height = _target_grid(bounds_wgs84, resolution_m)
    regridded_arr = _reproject_sum(path, transform, width, height, src_nodata=nodata)
    regridded_total = float(np.nansum(regridded_arr))

    native_total = native["native_total"]
    abs_error = regridded_total - native_total
    rel_error = (abs_error / native_total) if native_total else None
    return {
        **native,
        "regridded_total_1km": regridded_total,
        "conservation_abs_error": abs_error,
        "conservation_rel_error": rel_error,
    }


def mapped_water_polygon_stratum(
    water_gdf,
    bounds_wgs84: tuple,
    wp_grid: np.ndarray,
    ghs_grid: np.ndarray,
    resolution_m: float = GRID_RESOLUTION_M,
    water_fraction_threshold: float = 0.1,
) -> dict:
    """A stratum built from the CLOSED OSM water polygons this parser
    actually captures (`natural=water/bay/strait`, `waterway=riverbank/dock`
    -- config/poi_taxonomy.yaml area_categories.water_body) -- distinct from
    the WorldPop-density-based proxy strata in `_stratify`, which the review
    correctly flagged as self-referential.

    This is explicitly NOT a complete coastal/water-cell classification:
    it does not read `natural=coastline` (a line, not a closed polygon),
    does not construct an ocean/land mask, and does not include the 22
    water-related multipolygon RELATIONS this parser skips (see
    `skipped_relevant_relation_counts` in osm_extract.py / §4.4 of the
    report) -- so it undercounts true water coverage and must not be read
    as, or described as, a complete coastal stratum. A grid cell is
    classified "mapped water" only if more than `water_fraction_threshold`
    of its area intersects one of the AVAILABLE closed water polygons.
    """
    import geopandas as gpd

    transform, width, height = _target_grid(bounds_wgs84, resolution_m)
    if water_gdf is None or len(water_gdf) == 0:
        return {"note": "no water_body polygons available in this AOI extract", "cell_count": 0}

    water_m = water_gdf.to_crs(METRIC_CRS)
    water_union = water_m.geometry.union_all() if hasattr(water_m.geometry, "union_all") else water_m.unary_union

    import shapely.geometry as sgeom
    cell_polys = []
    cell_rc = []
    for row in range(height):
        for col in range(width):
            x0 = transform.c + col * transform.a
            y0 = transform.f + row * transform.e
            x1 = transform.c + (col + 1) * transform.a
            y1 = transform.f + (row + 1) * transform.e
            cell_polys.append(sgeom.box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))
            cell_rc.append((row, col))

    cells = gpd.GeoDataFrame({"row": [rc[0] for rc in cell_rc], "col": [rc[1] for rc in cell_rc]}, geometry=cell_polys, crs=METRIC_CRS)
    cell_area = resolution_m * resolution_m
    cells["water_fraction"] = cells.geometry.apply(lambda g: g.intersection(water_union).area / cell_area)
    cells["is_coastal_water"] = cells["water_fraction"] > water_fraction_threshold

    wp_flat = np.full(height * width, np.nan)
    ghs_flat = np.full(height * width, np.nan)
    for i, (row, col) in enumerate(cell_rc):
        if row < wp_grid.shape[0] and col < wp_grid.shape[1]:
            wp_flat[i] = wp_grid[row, col]
            ghs_flat[i] = ghs_grid[row, col]

    is_water = cells["is_coastal_water"].values
    both_valid = (~np.isnan(wp_flat)) & (~np.isnan(ghs_flat))

    def _substrata(mask_label, mask):
        sel = mask & both_valid
        if sel.sum() == 0:
            return None
        wp_v, ghs_v = wp_flat[sel], ghs_flat[sel]
        abs_diff = np.abs(wp_v - ghs_v)
        rel_diff, _ = safe_relative_difference(wp_v, ghs_v)
        return {
            "cell_count": int(sel.sum()),
            "worldpop_total": float(wp_v.sum()),
            "ghspop_total": float(ghs_v.sum()),
            "abs_diff_median": float(np.median(abs_diff)),
            "rel_diff_median": float(np.nanmedian(rel_diff)) if not np.all(np.isnan(rel_diff)) else None,
        }

    return {
        "water_fraction_threshold": water_fraction_threshold,
        "mapped_water_cell_count": int(is_water.sum()),
        "non_water_cell_count": int((~is_water).sum()),
        "mapped_water": _substrata("mapped_water", is_water),
        "non_water": _substrata("non_water", ~is_water),
        "coverage_caveat": (
            "Covers only closed OSM water polygons this parser captures (natural=water/bay/strait, "
            "waterway=riverbank/dock). Does NOT read natural=coastline, does NOT construct an ocean/land "
            "mask, and excludes 22 water-related multipolygon relations this parser skips (see osm_extract.py "
            "skipped_relevant_relation_counts) -- an undercount of true water/coastal coverage, not a complete "
            "coastal stratum."
        ),
    }
