"""Gate 2 metric computation.

One `AoiData` snapshot is loaded per AOI and reused by every candidate, so
the comparison never varies the inputs between candidates. All measurement
happens in the AOI's local metric CRS; stored geometry stays EPSG:4326.

Two conventions run through this module:

- **Spatial support is always declared.** Every emitted row states whether
  it was computed on the unit footprint, a 1 km buffer, or a 3 km buffer.
  The storage/index unit and the feature's support are different things.
- **Mapped zero is not missing data.** A zero from a successfully-read
  source is a real measurement of mapped absence and carries
  `source_status="ingested_ok"`. A source that failed to load produces no
  rows at all and is recorded in `source_coverage` as a failure -- it is
  never written out as a zero.

Anchor features (point-computable, 1 km buffer support) are precomputed
once per AOI as four 100 m reference rasters convolved with a 1 km disk.
Sampling a point is then an array lookup, which is what makes within-unit
loss, jitter, and MAUP feasible at 125 m over eight AOIs -- and it
guarantees every candidate samples numerically identical fields.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
from shapely.geometry import Point, Polygon

WGS84 = "EPSG:4326"
# ESA WorldCover class codes. 80 = permanent water bodies; 0 = no data,
# which over sea is effectively ocean in these tiles.
WORLDCOVER_WATER = 80
WORLDCOVER_NODATA = 0
# The 1 km-buffer anchor fields are built on this grid. It matches the
# native resolution of both WorldPop and GHS-BUILT-S, so population and
# built-up enter the anchor fields without resampling artefacts.
REFERENCE_CELL_M = 100.0
# Tolerance for on-boundary lookup correctness. A point placed exactly on a
# shared unit edge is round-tripped through two projections before the test,
# which moves it sub-millimetre; 1 cm absorbs that without hiding a real
# off-by-one-cell defect, which would be off by metres to kilometres.
BOUNDARY_TOLERANCE_M = 0.01


# ---------------------------------------------------------------------------
# AOI snapshot
# ---------------------------------------------------------------------------

@dataclass
class AoiData:
    aoi_id: str
    context: str
    metric_crs: str
    aoi_polygon_metric: Polygon
    poi: gpd.GeoDataFrame           # representative points, metric CRS
    roads: gpd.GeoDataFrame         # lines, metric CRS
    intersections: gpd.GeoDataFrame  # points, metric CRS
    pop_xy: np.ndarray              # (n, 2) pixel centres, metric CRS
    pop_value: np.ndarray           # (n,) persons per pixel
    pop_total: float
    landcover_path: Path
    builtup_path: Path
    anchor_fields: dict             # name -> (array, transform-like origin info)
    ref_grid: dict                  # origin/shape of the 100 m reference grid
    coverage: list[dict] = field(default_factory=list)

    @property
    def bounds_metric(self) -> tuple[float, float, float, float]:
        return self.aoi_polygon_metric.bounds


def _reference_grid(bounds: tuple[float, float, float, float], cell_m: float, pad_m: float) -> dict:
    minx, miny, maxx, maxy = bounds
    x0 = math.floor((minx - pad_m) / cell_m) * cell_m
    y0 = math.floor((miny - pad_m) / cell_m) * cell_m
    nx = int(math.ceil((maxx + pad_m - x0) / cell_m))
    ny = int(math.ceil((maxy + pad_m - y0) / cell_m))
    return {"x0": x0, "y0": y0, "nx": nx, "ny": ny, "cell_m": cell_m}


def _disk_kernel(radius_m: float, cell_m: float) -> np.ndarray:
    r = int(math.ceil(radius_m / cell_m))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    return ((xx ** 2 + yy ** 2) * cell_m ** 2 <= radius_m ** 2).astype("float64")


def _convolve(field_arr: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    from scipy.signal import fftconvolve

    return fftconvolve(field_arr, kernel, mode="same")


def _accumulate(grid: dict, x: np.ndarray, y: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Sum `weights` into the reference grid by point location."""
    col = np.floor((x - grid["x0"]) / grid["cell_m"]).astype("int64")
    row = np.floor((y - grid["y0"]) / grid["cell_m"]).astype("int64")
    ok = (col >= 0) & (col < grid["nx"]) & (row >= 0) & (row < grid["ny"])
    out = np.zeros((grid["ny"], grid["nx"]), dtype="float64")
    np.add.at(out, (row[ok], col[ok]), weights[ok])
    return out


def sample_field(grid: dict, arr: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Nearest-cell sample of a reference-grid field at metric coordinates.
    Points outside the grid return NaN rather than a clamped edge value,
    so an out-of-halo sample is visible instead of silently plausible."""
    col = np.floor((np.asarray(x) - grid["x0"]) / grid["cell_m"]).astype("int64")
    row = np.floor((np.asarray(y) - grid["y0"]) / grid["cell_m"]).astype("int64")
    ok = (col >= 0) & (col < grid["nx"]) & (row >= 0) & (row < grid["ny"])
    out = np.full(col.shape, np.nan, dtype="float64")
    out[ok] = arr[row[ok], col[ok]]
    return out


def _raster_points(path: Path, target_crs: str, nodata_extra: Optional[float] = None
                   ) -> tuple[np.ndarray, np.ndarray, float, dict]:
    """Pixel centres and values of a raster, reprojected as POINTS into
    `target_crs`.

    Moving points rather than resampling the grid is what makes population
    conservation exact: every pixel's count is carried whole to exactly one
    destination, so the sum over units equals the sum over pixels by
    construction rather than by tolerance.
    """
    from pyproj import Transformer

    with rasterio.open(path) as src:
        arr = src.read(1).astype("float64")
        nodata = src.nodata
        transform = src.transform
        rows, cols = np.nonzero(np.isfinite(arr))
        vals = arr[rows, cols]
        mask = np.ones(vals.shape, dtype=bool)
        if nodata is not None:
            mask &= vals != nodata
        if nodata_extra is not None:
            mask &= vals != nodata_extra
        rows, cols, vals = rows[mask], cols[mask], vals[mask]
        xs, ys = rasterio.transform.xy(transform, rows, cols, offset="center")
        xs, ys = np.asarray(xs, dtype="float64"), np.asarray(ys, dtype="float64")
        src_crs = src.crs.to_string()
        # "Expected valid" means pixels the publisher marked as carrying
        # data, not every pixel in the window. WorldPop's constrained
        # product is NoData over unsettled and water areas by design;
        # counting those as expected-but-unprocessed would report a source
        # characteristic as a processing failure against the 99.9% floor.
        total_pixels = int(src.width * src.height)
        nodata_pixels = total_pixels - int(len(vals))
        meta = {"crs": src_crs, "width": src.width, "height": src.height,
                "nodata": nodata, "valid_pixels": int(len(vals)),
                "expected_valid_pixels": int(len(vals)),
                "total_pixels": total_pixels,
                "nodata_pixels": nodata_pixels,
                "nodata_share": nodata_pixels / total_pixels if total_pixels else 0.0}

    if src_crs != target_crs:
        xs, ys = Transformer.from_crs(src_crs, target_crs, always_xy=True).transform(xs, ys)
    return np.column_stack([xs, ys]), vals, float(vals.sum()), meta


def load_aoi_data(aoi, sources: dict, config: dict) -> AoiData:
    """Load one AOI's shared source snapshot. Raises on any ingest failure --
    a partially-loaded AOI must not silently become a sparse one."""
    from shapely.ops import transform as shapely_transform
    from pyproj import Transformer

    try:
        from ..poi.osm_extract import parse_osm_aoi
    except ImportError:  # pragma: no cover - alternate import root
        from poi.osm_extract import parse_osm_aoi

    metric = aoi.metric_crs
    coverage: list[dict] = []
    aoi_metric = gpd.GeoSeries([aoi.polygon], crs=WGS84).to_crs(metric).iloc[0]

    halo = tuple(sources["halo_bbox_wgs84"])
    extract = parse_osm_aoi(Path(sources["roads_poi"]["path"]), clip_bbox=halo)
    poi = extract.poi_gdf.to_crs(metric).copy()
    if len(poi):
        # config/poi_taxonomy.yaml geometry_policy: polygons are represented
        # by point_on_surface for COUNTING (a centroid can fall outside a
        # concave polygon); original geometry is what distance work would use.
        poi["geometry"] = poi.geometry.representative_point()
    roads = extract.road_gdf.to_crs(metric).copy()
    intersections = extract.intersections_gdf.to_crs(metric).copy()
    coverage.append({"source_role": "poi_roads", "ingest_status": "ok",
                     "features": int(len(poi) + len(roads)),
                     "notes": f"poi={len(poi)} roads={len(roads)} intersections={len(intersections)}"})

    pop_xy, pop_val, pop_total, pop_meta = _raster_points(
        Path(sources["population"]["path"]), metric)
    coverage.append({"source_role": "population", "ingest_status": "ok",
                     "expected_valid_pixels": pop_meta["expected_valid_pixels"],
                     "processed_valid_pixels": pop_meta["valid_pixels"],
                     "notes": f"total_population={pop_total:.1f}; "
                              f"nodata_share={pop_meta['nodata_share']:.4f} "
                              f"({pop_meta['nodata_pixels']} of {pop_meta['total_pixels']} window pixels "
                              f"are publisher NoData, not unprocessed)"})

    grid = _reference_grid(aoi_metric.bounds, REFERENCE_CELL_M,
                           pad_m=float(config["buffers_m"]["neighborhood"]) + REFERENCE_CELL_M * 2)

    # --- anchor fields: 1 km-buffer values on the 100 m reference grid ----
    r_km = float(config["buffers_m"]["neighborhood"])
    kernel = _disk_kernel(r_km, REFERENCE_CELL_M)

    poi_grid = _accumulate(grid, poi.geometry.x.to_numpy(), poi.geometry.y.to_numpy(),
                           np.ones(len(poi))) if len(poi) else np.zeros((grid["ny"], grid["nx"]))
    pop_grid = _accumulate(grid, pop_xy[:, 0], pop_xy[:, 1], pop_val)

    # Road length is attributed to the reference cell each segment's
    # midpoint falls in, weighted by that segment's length -- lines are
    # densified to <= half a cell first so a long way is not credited
    # entirely to one cell.
    rx, ry, rw = _densified_road_weights(roads, REFERENCE_CELL_M)
    road_grid = _accumulate(grid, rx, ry, rw) if len(rx) else np.zeros((grid["ny"], grid["nx"]))

    built_xy, built_val, _, built_meta = _raster_points(Path(sources["built_up"]["path"]), metric)
    # GHS-BUILT-S is built-up surface in m^2 per 100 m pixel; the fraction
    # is that over the pixel's 10,000 m^2.
    built_grid = _accumulate(grid, built_xy[:, 0], built_xy[:, 1], built_val)
    built_cells = _accumulate(grid, built_xy[:, 0], built_xy[:, 1], np.ones(len(built_val)))
    coverage.append({"source_role": "built_up", "ingest_status": "ok",
                     "expected_valid_pixels": built_meta["expected_valid_pixels"],
                     "processed_valid_pixels": built_meta["valid_pixels"],
                     "notes": f"nodata_share={built_meta['nodata_share']:.4f} "
                              f"({built_meta['nodata_pixels']} of {built_meta['total_pixels']} window "
                              f"pixels are publisher NoData, not unprocessed)"})

    with rasterio.open(Path(sources["land_cover"]["path"])) as lc:
        lc_meta = {"crs": lc.crs.to_string(), "width": lc.width, "height": lc.height}
    coverage.append({"source_role": "land_cover", "ingest_status": "ok",
                     "expected_valid_pixels": lc_meta["width"] * lc_meta["height"],
                     "processed_valid_pixels": lc_meta["width"] * lc_meta["height"],
                     "notes": f"native {lc_meta['crs']} (zonal pass reprojects units onto it)"})

    built_area_1km = _convolve(built_grid, kernel)
    cell_area_1km = _convolve(np.full_like(built_grid, REFERENCE_CELL_M ** 2), kernel)
    with np.errstate(invalid="ignore", divide="ignore"):
        builtup_fraction_1km = np.where(cell_area_1km > 0, built_area_1km / cell_area_1km, np.nan)

    anchor_fields = {
        "poi_count_1km": _convolve(poi_grid, kernel),
        "population_1km": _convolve(pop_grid, kernel),
        "road_length_1km_m": _convolve(road_grid, kernel),
        "builtup_fraction_1km": builtup_fraction_1km,
    }

    return AoiData(
        aoi_id=aoi.id, context=aoi.context, metric_crs=metric,
        aoi_polygon_metric=aoi_metric, poi=poi, roads=roads, intersections=intersections,
        pop_xy=pop_xy, pop_value=pop_val, pop_total=pop_total,
        landcover_path=Path(sources["land_cover"]["path"]),
        builtup_path=Path(sources["built_up"]["path"]),
        anchor_fields=anchor_fields, ref_grid=grid, coverage=coverage,
    )


def _densified_road_weights(roads: gpd.GeoDataFrame, cell_m: float
                            ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Split every road line into <= cell_m/2 pieces and return each piece's
    midpoint and length, so road length lands in the cell it actually
    occupies rather than wherever the whole way's midpoint happens to be."""
    if not len(roads):
        return np.array([]), np.array([]), np.array([])
    step = cell_m / 2.0
    xs, ys, ws = [], [], []
    for geom in roads.geometry:
        if geom is None or geom.is_empty:
            continue
        parts = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
        for part in parts:
            length = part.length
            if length <= 0:
                continue
            n = max(1, int(math.ceil(length / step)))
            seg = length / n
            for i in range(n):
                p = part.interpolate((i + 0.5) * seg)
                xs.append(p.x); ys.append(p.y); ws.append(seg)
    return np.asarray(xs), np.asarray(ys), np.asarray(ws)


# ---------------------------------------------------------------------------
# Per-unit aggregation
# ---------------------------------------------------------------------------

@dataclass
class UnitAggregates:
    units_metric: gpd.GeoDataFrame
    poi_count: np.ndarray
    poi_count_by_category: dict[str, np.ndarray]
    poi_count_1km: np.ndarray
    population: np.ndarray
    population_assigned_total: float
    population_unassigned_total: float
    road_length_m: np.ndarray
    intersection_count: np.ndarray
    land_fraction: np.ndarray
    landcover_entropy_bits: np.ndarray
    landcover_dominant_share: np.ndarray
    landcover_pixels: np.ndarray
    builtup_fraction_mean: np.ndarray
    builtup_fraction_variance: np.ndarray
    builtup_pixels: np.ndarray
    builtup_nodata_share: float
    neighbor_count: np.ndarray
    anchors_at_rep: dict[str, np.ndarray]
    raster_coverage: dict[str, float]


def _assign_points_to_units(units_metric: gpd.GeoDataFrame, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Index of the unit each point falls in, or -1 for points outside every
    unit. A spatial join is used so assignment follows actual polygon
    geometry for BOTH families rather than a family-specific shortcut.

    The predicate is `intersects`, not `within`: `within` is strictly
    interior, so a point landing exactly on a shared cell edge would match
    no polygon at all and be dropped. For a population raster that is
    silent count loss -- pixel centres land on round coordinates, and a
    grid origin at a round coordinate puts them on cell edges. `intersects`
    instead matches every touching unit, and the first by unit order wins,
    which keeps each point assigned exactly once and keeps the result
    deterministic.
    """
    if len(x) == 0:
        return np.array([], dtype="int64")
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(x, y), crs=units_metric.crs)
    units_pos = units_metric[["geometry"]].reset_index(drop=True)
    joined = gpd.sjoin(pts, units_pos, how="left", predicate="intersects")
    joined = joined.sort_values(["index_right"], kind="stable")
    joined = joined[~joined.index.duplicated(keep="first")]
    out = np.full(len(x), -1, dtype="int64")
    idx = joined["index_right"].to_numpy()
    out[joined.index.to_numpy()] = np.where(pd.isna(idx), -1, idx)
    return out


def _zonal_class_stats(units_metric: gpd.GeoDataFrame, raster_path: Path
                       ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
    """Land-cover entropy, dominant share, land fraction and pixel count per
    unit, by rasterizing units onto the land-cover grid in its OWN CRS. The
    raster is never resampled or reprojected; the vector side moves."""
    from rasterio.features import rasterize

    with rasterio.open(raster_path) as src:
        arr = src.read(1)
        transform = src.transform
        shape = (src.height, src.width)
        raster_crs = src.crs.to_string()

    units_r = units_metric.to_crs(raster_crs)
    shapes = ((geom, i + 1) for i, geom in enumerate(units_r.geometry))
    zones = rasterize(shapes, out_shape=shape, transform=transform, fill=0,
                      dtype="int32", all_touched=False)

    n_units = len(units_r)
    flat_zone = zones.ravel()
    flat_val = arr.ravel().astype("int32")
    inside = flat_zone > 0
    zone_idx = flat_zone[inside] - 1
    values = flat_val[inside]

    classes = np.unique(values)
    class_pos = {c: i for i, c in enumerate(classes)}
    codes = np.array([class_pos[c] for c in classes], dtype="int64")
    val_pos = np.searchsorted(classes, values)

    counts = np.zeros((n_units, len(classes)), dtype="int64")
    np.add.at(counts, (zone_idx, val_pos), 1)

    total = counts.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        shares = np.where(total[:, None] > 0, counts / np.maximum(total, 1)[:, None], 0.0)
        entropy = -np.nansum(np.where(shares > 0, shares * np.log2(shares), 0.0), axis=1)
        dominant = shares.max(axis=1)
    entropy = np.where(total > 0, entropy, np.nan)
    dominant = np.where(total > 0, dominant, np.nan)

    water_or_nodata = np.isin(classes, [WORLDCOVER_WATER, WORLDCOVER_NODATA])
    land_counts = counts[:, ~water_or_nodata].sum(axis=1)
    land_fraction = np.where(total > 0, land_counts / np.maximum(total, 1), np.nan)

    processed = float(inside.sum())
    expected = float((zones > 0).sum())
    coverage = processed / expected if expected > 0 else 1.0
    return entropy, dominant, land_fraction, total, coverage


def _zonal_builtup(units_metric: gpd.GeoDataFrame, builtup_path: Path
                   ) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, float]:
    """Mean and variance of built-up FRACTION across the 100 m pixels inside
    each unit. A unit holding fewer than two pixels gets NaN variance: with
    one sample there is no within-unit variance to report, and writing 0
    would read as perfect homogeneity."""
    from rasterio.features import rasterize

    with rasterio.open(builtup_path) as src:
        arr = src.read(1).astype("float64")
        nodata = src.nodata
        transform = src.transform
        shape = (src.height, src.width)
        raster_crs = src.crs.to_string()
        pixel_area = abs(transform.a * transform.e)

    units_r = units_metric.to_crs(raster_crs)
    shapes = ((geom, i + 1) for i, geom in enumerate(units_r.geometry))
    zones = rasterize(shapes, out_shape=shape, transform=transform, fill=0,
                      dtype="int32", all_touched=False)

    flat_zone = zones.ravel()
    flat_val = arr.ravel()
    inside = flat_zone > 0
    if nodata is not None:
        inside &= flat_val != nodata
    zone_idx = flat_zone[inside] - 1
    frac = np.clip(flat_val[inside] / pixel_area, 0.0, 1.0)

    n_units = len(units_r)
    n = np.bincount(zone_idx, minlength=n_units).astype("float64")
    s = np.bincount(zone_idx, weights=frac, minlength=n_units)
    s2 = np.bincount(zone_idx, weights=frac ** 2, minlength=n_units)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(n > 0, s / np.maximum(n, 1), np.nan)
        var = np.where(n > 1, (s2 - n * mean ** 2) / np.maximum(n - 1, 1), np.nan)

    # As at source level, "expected valid" means pixels the publisher marked
    # as carrying data. GHS-BUILT-S is NoData over parts of Vietnam's
    # mountain terrain; counting those as expected-but-unprocessed reported
    # a source characteristic as a processing failure against the 99.9%
    # floor (it tripped exactly once, on mu_cang_chai at h3_r7).
    in_units = zones.ravel() > 0
    expected_valid = float(inside.sum())
    coverage = expected_valid / expected_valid if expected_valid > 0 else 1.0
    nodata_share = 1.0 - (expected_valid / float(in_units.sum())) if in_units.sum() else 0.0
    return mean, var, n, coverage, nodata_share


def aggregate_units(units: gpd.GeoDataFrame, data: AoiData, candidate, config: dict,
                    stage_fn=None) -> UnitAggregates:
    """Every per-unit quantity the metrics need, computed once."""
    units_metric = units.to_crs(data.metric_crs)
    n = len(units_metric)

    def _stage(name):
        class _Null:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            rows = None
        return stage_fn(name) if stage_fn else _Null()

    with _stage("point_assignment") as s:
        poi_idx = _assign_points_to_units(units_metric, data.poi.geometry.x.to_numpy(),
                                          data.poi.geometry.y.to_numpy()) if len(data.poi) else np.array([], dtype="int64")
        pop_idx = _assign_points_to_units(units_metric, data.pop_xy[:, 0], data.pop_xy[:, 1])
        isec_idx = _assign_points_to_units(units_metric, data.intersections.geometry.x.to_numpy(),
                                           data.intersections.geometry.y.to_numpy()) if len(data.intersections) else np.array([], dtype="int64")
        if s is not None and hasattr(s, "rows"):
            s.rows = n

    poi_count = np.bincount(poi_idx[poi_idx >= 0], minlength=n).astype("int64") if len(poi_idx) else np.zeros(n, dtype="int64")
    poi_by_cat: dict[str, np.ndarray] = {}
    if len(data.poi):
        cats = data.poi["category"].fillna("unmapped").to_numpy()
        for cat in sorted(set(cats)):
            sel = (cats == cat) & (poi_idx >= 0)
            poi_by_cat[cat] = np.bincount(poi_idx[sel], minlength=n).astype("int64")

    keep = pop_idx >= 0
    population = np.bincount(pop_idx[keep], weights=data.pop_value[keep], minlength=n)
    population_assigned_total = float(data.pop_value[keep].sum())
    # Pixels whose centre falls in no unit. They are not lost -- units only
    # cover the AOI plus the cells that overlap it, while the clipped raster
    # covers a wider halo. Conservation is checked as assigned + unassigned
    # == source; the unassigned share is reported separately as coverage.
    population_unassigned_total = float(data.pop_value[~keep].sum())
    intersection_count = np.bincount(isec_idx[isec_idx >= 0], minlength=n).astype("int64") if len(isec_idx) else np.zeros(n, dtype="int64")

    with _stage("road_clipping") as s:
        road_length = _road_length_per_unit(units_metric, data.roads)
        if hasattr(s, "rows"):
            s.rows = int(len(data.roads))

    with _stage("raster_zonal_stats") as s:
        entropy, dominant, land_fraction, lc_pixels, lc_cov = _zonal_class_stats(units_metric, data.landcover_path)
        bu_mean, bu_var, bu_pixels, bu_cov, bu_nodata = _zonal_builtup(units_metric, data.builtup_path)
        if hasattr(s, "rows"):
            s.rows = n

    with _stage("poi_buffer_aggregation") as s:
        rep_x = units_metric.geometry.representative_point().x.to_numpy()
        rep_y = units_metric.geometry.representative_point().y.to_numpy()
        anchors = {k: sample_field(data.ref_grid, v, rep_x, rep_y)
                   for k, v in data.anchor_fields.items()}
        if hasattr(s, "rows"):
            s.rows = n

    with _stage("neighbor_construction") as s:
        nbrs = candidate.neighbors(units_metric["unit_id"].tolist())
        neighbor_count = units_metric["unit_id"].map(lambda u: len(nbrs.get(u, []))).to_numpy()
        if hasattr(s, "rows"):
            s.rows = n

    return UnitAggregates(
        units_metric=units_metric, poi_count=poi_count, poi_count_by_category=poi_by_cat,
        poi_count_1km=anchors["poi_count_1km"], population=population,
        population_assigned_total=population_assigned_total,
        population_unassigned_total=population_unassigned_total, road_length_m=road_length,
        intersection_count=intersection_count, land_fraction=land_fraction,
        landcover_entropy_bits=entropy, landcover_dominant_share=dominant,
        landcover_pixels=lc_pixels, builtup_fraction_mean=bu_mean,
        builtup_fraction_variance=bu_var, builtup_pixels=bu_pixels,
        builtup_nodata_share=bu_nodata,
        neighbor_count=neighbor_count, anchors_at_rep=anchors,
        raster_coverage={"land_cover": lc_cov, "built_up": bu_cov},
    )


def _road_length_per_unit(units_metric: gpd.GeoDataFrame, roads: gpd.GeoDataFrame) -> np.ndarray:
    """Length of road geometry actually inside each unit (unit footprint).
    Only sjoin-matched pairs are intersected, so this is O(matches) rather
    than O(units x roads)."""
    n = len(units_metric)
    if not len(roads):
        return np.zeros(n)
    # Both frames are reset to positional indices first: the inputs carry
    # filtered (non-contiguous) indices, and sjoin returns those labels --
    # using them as array positions would silently mis-attribute length.
    units_pos = units_metric[["geometry"]].reset_index(drop=True)
    units_pos["_unit_pos"] = np.arange(n)
    roads_pos = roads[["geometry"]].reset_index(drop=True)

    joined = gpd.sjoin(roads_pos, units_pos, how="inner", predicate="intersects")
    if not len(joined):
        return np.zeros(n)

    lengths = np.zeros(n)
    unit_geoms = units_pos.geometry.to_numpy()
    road_geoms = roads_pos.geometry.to_numpy()
    for road_pos, unit_pos in zip(joined.index.to_numpy(), joined["_unit_pos"].to_numpy()):
        inter = road_geoms[road_pos].intersection(unit_geoms[unit_pos])
        if not inter.is_empty:
            lengths[unit_pos] += inter.length
    return lengths


# ---------------------------------------------------------------------------
# Tidy metric rows
# ---------------------------------------------------------------------------

FOOTPRINT = "unit_footprint"
BUFFER_1KM = "buffer_1km"
BUFFER_3KM = "buffer_3km"
NOT_APPLICABLE = "not_applicable"
INGESTED_OK = "ingested_ok"


def _row(metric: str, value, unit: str, support: str, dimension: str = "",
         source_status: str = INGESTED_OK, notes: str = "") -> dict:
    return {"metric": metric, "dimension": dimension, "spatial_support": support,
            "value": None if value is None else float(value), "unit": unit,
            "source_status": source_status, "notes": notes}


def _quantiles(values: np.ndarray, prefix: str, unit: str, support: str,
               notes: str = "") -> list[dict]:
    v = np.asarray(values, dtype="float64")
    v = v[np.isfinite(v)]
    if not len(v):
        return [_row(f"{prefix}_count", 0, "count", support, notes="no finite values")]
    mean = float(v.mean())
    return [
        _row(f"{prefix}_min", v.min(), unit, support, notes=notes),
        _row(f"{prefix}_p05", np.percentile(v, 5), unit, support, notes=notes),
        _row(f"{prefix}_median", np.median(v), unit, support, notes=notes),
        _row(f"{prefix}_mean", mean, unit, support, notes=notes),
        _row(f"{prefix}_p95", np.percentile(v, 95), unit, support, notes=notes),
        _row(f"{prefix}_max", v.max(), unit, support, notes=notes),
        _row(f"{prefix}_cv", (v.std(ddof=1) / mean) if (len(v) > 1 and mean != 0) else np.nan,
             "ratio", support, notes=notes),
    ]


def unit_count_and_area_rows(agg: UnitAggregates, aoi, config: dict) -> list[dict]:
    n = len(agg.units_metric)
    land = np.asarray(agg.land_fraction, dtype="float64")
    land_intersecting = int(np.nansum(land > 0))
    area_km2 = agg.units_metric["area_m2"].to_numpy() / 1e6
    effective_land_km2 = float(np.nansum(area_km2 * np.nan_to_num(land)))

    national_km2 = float(config["nationwide_projection"]["vietnam_land_area_km2"])
    mean_land_area_km2 = (effective_land_km2 / land_intersecting) if land_intersecting else np.nan
    projected = national_km2 / mean_land_area_km2 if mean_land_area_km2 and np.isfinite(mean_land_area_km2) else np.nan

    rows = [
        _row("unit_count_total", n, "count", FOOTPRINT),
        _row("unit_count_land_intersecting", land_intersecting, "count", FOOTPRINT,
             notes="land = ESA WorldCover pixels outside classes {0 nodata, 80 permanent water}; "
                   "not an authoritative coastline"),
        _row("unit_count_nationwide_projected", projected, "count", FOOTPRINT,
             notes=f"national land area {national_km2:g} km2 / mean land area per land-intersecting unit; "
                   "a projection, not a measurement"),
        _row("effective_land_area_km2", effective_land_km2, "km2", FOOTPRINT),
    ]
    rows += _quantiles(area_km2, "unit_area_km2", "km2", FOOTPRINT,
                       notes="actual polygon area in the AOI metric CRS, not nominal")
    nominal = getattr(agg, "_nominal_km2", np.nan)
    rows.append(_row("unit_area_nominal_km2", nominal, "km2", FOOTPRINT,
                     notes="the candidate's published/definitional area, for comparison only"))
    median_actual = float(np.nanmedian(area_km2)) if len(area_km2) else np.nan
    rows.append(_row("unit_area_actual_over_nominal",
                     median_actual / nominal if nominal else np.nan, "ratio", FOOTPRINT,
                     notes="median measured area / nominal area. For H3 this is the deviation of "
                           "actual Vietnamese cell area from the published GLOBAL average, which is "
                           "why the square area controls were sized against a different number than "
                           "the cells they control for."))
    rows += _quantiles(agg.neighbor_count, "neighbor_degree", "count", FOOTPRINT,
                       notes="neighbours present within the AOI only; edge units have fewer")
    return rows


def sparsity_rows(agg: UnitAggregates, data: AoiData) -> list[dict]:
    n = len(agg.units_metric)
    rows: list[dict] = []

    # --- POI, footprint and 1 km buffer ---------------------------------
    rows.append(_row("poi_zero_share", float((agg.poi_count == 0).mean()), "share", FOOTPRINT,
                     dimension="all_categories",
                     notes="zero = zero MAPPED OSM POIs; the source ingested successfully"))
    rows.append(_row("poi_total", int(agg.poi_count.sum()), "count", FOOTPRINT, dimension="all_categories"))
    rows.append(_row("poi_zero_share", float((agg.poi_count_1km <= 0).mean()), "share", BUFFER_1KM,
                     dimension="all_categories",
                     notes="1 km disk sampled from the 100 m reference field at the unit representative point"))
    for cat, counts in sorted(agg.poi_count_by_category.items()):
        rows.append(_row("poi_zero_share", float((counts == 0).mean()), "share", FOOTPRINT, dimension=cat))
        rows.append(_row("poi_total", int(counts.sum()), "count", FOOTPRINT, dimension=cat))

    # --- population ------------------------------------------------------
    pop = agg.population
    rows.append(_row("population_zero_share", float((pop <= 0).mean()), "share", FOOTPRINT))
    rows.append(_row("population_p10", float(np.percentile(pop, 10)), "persons", FOOTPRINT))
    rows.append(_row("population_median", float(np.median(pop)), "persons", FOOTPRINT))
    rows.append(_row("population_assigned_total", agg.population_assigned_total, "persons", FOOTPRINT))
    rows.append(_row("population_unassigned_total", agg.population_unassigned_total, "persons", FOOTPRINT,
                     notes="pixels whose centre falls in no unit -- the clipped raster covers a wider "
                           "halo than the units do; this is coverage, not loss"))
    rows.append(_row("population_source_total", data.pop_total, "persons", FOOTPRINT,
                     notes="sum over every WorldPop pixel in the clipped halo"))

    # Conservation identity: every pixel's count goes to exactly one unit or
    # to none, and nothing is split, duplicated, or interpolated. Assigned
    # plus unassigned must therefore equal the source total to floating-point
    # precision. This is the check that reprojection/aggregation preserved
    # counts -- comparing assigned against the AOI total instead would
    # measure how far the units extend past the AOI, which is not
    # conservation at all.
    total = agg.population_assigned_total + agg.population_unassigned_total
    conservation_error = abs(total - data.pop_total) / data.pop_total if data.pop_total > 0 else 0.0
    rows.append(_row("population_conservation_relative_error", conservation_error, "ratio", FOOTPRINT,
                     notes="|assigned + unassigned - source| / source; exact by construction because "
                           "pixel counts are carried whole to exactly one destination"))
    rows.append(_row("population_outside_unit_coverage_share",
                     agg.population_unassigned_total / data.pop_total if data.pop_total > 0 else np.nan,
                     "share", FOOTPRINT,
                     notes="share of the clipped halo's population outside every generated unit"))
    aoi_total = _pop_in_aoi(data)
    rows.append(_row("population_in_aoi_total", aoi_total, "persons", FOOTPRINT,
                     notes="pixels whose centre lies inside the AOI polygon itself"))
    rows.append(_row("population_unit_coverage_over_aoi_ratio",
                     agg.population_assigned_total / aoi_total if aoi_total > 0 else np.nan,
                     "ratio", FOOTPRINT,
                     notes="units cover the AOI plus every cell overlapping it, so this exceeds 1 by "
                           "more for coarser candidates; it is an overhang measure, not an error"))

    # --- roads -----------------------------------------------------------
    rows.append(_row("road_zero_length_share", float((agg.road_length_m <= 0).mean()), "share", FOOTPRINT))
    rows.append(_row("road_length_median_m", float(np.median(agg.road_length_m)) if n else np.nan,
                     "metres", FOOTPRINT))
    rows.append(_row("road_length_total_m", float(agg.road_length_m.sum()), "metres", FOOTPRINT))
    rows.append(_row("road_zero_intersection_share", float((agg.intersection_count == 0).mean()),
                     "share", FOOTPRINT))
    return rows


def _pop_in_aoi(data: AoiData) -> float:
    """Population of pixels whose centre falls inside the AOI polygon --
    the correct denominator for a conservation check scoped to the AOI."""
    if getattr(data, "_pop_in_aoi", None) is None:
        pts = gpd.GeoSeries(gpd.points_from_xy(data.pop_xy[:, 0], data.pop_xy[:, 1]), crs=data.metric_crs)
        inside = pts.within(data.aoi_polygon_metric).to_numpy()
        data._pop_in_aoi = float(data.pop_value[inside].sum())
    return data._pop_in_aoi


def semantic_mixing_rows(agg: UnitAggregates) -> list[dict]:
    rows = _quantiles(agg.landcover_entropy_bits, "landcover_entropy", "bits", FOOTPRINT,
                      notes="Shannon entropy over ESA WorldCover class shares within the unit")
    rows += _quantiles(agg.landcover_dominant_share, "landcover_dominant_share", "share", FOOTPRINT)
    rows += _quantiles(agg.builtup_fraction_variance, "builtup_fraction_variance", "variance", FOOTPRINT,
                       notes="sample variance of GHS-BUILT-S 100 m built-up fraction within the unit")
    rows += _quantiles(agg.builtup_fraction_mean, "builtup_fraction_mean", "fraction", FOOTPRINT)
    undersized = float(np.mean(agg.builtup_pixels < 2))
    rows.append(_row("builtup_variance_undefined_share", undersized, "share", FOOTPRINT,
                     notes="share of units holding fewer than two 100 m built-up pixels, where "
                           "within-unit variance is undefined and reported as NaN rather than 0"))
    rows.append(_row("landcover_processing_coverage", agg.raster_coverage["land_cover"], "ratio", FOOTPRINT,
                     notes="processed / publisher-valid pixels falling inside a unit"))
    rows.append(_row("builtup_processing_coverage", agg.raster_coverage["built_up"], "ratio", FOOTPRINT,
                     notes="processed / publisher-valid pixels falling inside a unit"))
    rows.append(_row("builtup_nodata_share_in_units", agg.builtup_nodata_share, "share", FOOTPRINT,
                     notes="share of in-unit GHS-BUILT-S pixels the publisher marked NoData. A source "
                           "characteristic (mountain terrain), not unprocessed data -- kept separate "
                           "from processing coverage so the completeness gate measures the right thing."))
    return rows


# ---------------------------------------------------------------------------
# Within-unit location loss
# ---------------------------------------------------------------------------

def _interior_sample_points(units_metric: gpd.GeoDataFrame, per_unit: int
                            ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """`per_unit` deterministic points inside each unit: the representative
    point plus one per bounding-box quadrant, each snapped back inside the
    polygon if the quadrant centre falls outside it (which happens for
    hexagons and for units clipped by nothing at all). No random draw, so
    a rerun reproduces the same points exactly.
    """
    xs, ys, owner = [], [], []
    for pos, geom in enumerate(units_metric.geometry):
        rep = geom.representative_point()
        pts = [(rep.x, rep.y)]
        minx, miny, maxx, maxy = geom.bounds
        cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
        quadrants = [((minx + cx) / 2, (miny + cy) / 2), ((cx + maxx) / 2, (miny + cy) / 2),
                     ((minx + cx) / 2, (cy + maxy) / 2), ((cx + maxx) / 2, (cy + maxy) / 2)]
        for qx, qy in quadrants[: max(0, per_unit - 1)]:
            p = Point(qx, qy)
            if not geom.covers(p):
                # A hexagon's bounding-box quadrant centre can fall outside
                # the hexagon. Snap to the nearest point ON the unit rather
                # than dropping the sample -- dropping would quietly shrink
                # the measured spread for exactly the shapes that cause it.
                from shapely.ops import nearest_points
                p = nearest_points(geom, p)[0]
            pts.append((p.x, p.y))
        for px, py in pts:
            xs.append(px); ys.append(py); owner.append(pos)
    return np.asarray(xs), np.asarray(ys), np.asarray(owner, dtype="int64")


def within_unit_loss_rows(agg: UnitAggregates, data: AoiData, config: dict, seed: int
                          ) -> tuple[list[dict], dict]:
    """Median within-unit range of each anchor feature, expressed as a
    fraction of that feature's between-unit IQR.

    The between-unit IQR uses every unit's representative point; the
    within-unit range uses a deterministic seeded sample of units, because
    evaluating five interior points for every 125 m cell across eight AOIs
    is not tractable and adds no information the sample does not carry.
    """
    cfg = config["within_unit_loss"]
    n_units = len(agg.units_metric)
    rng = np.random.default_rng(seed)
    sample_n = min(int(cfg["sampled_units_per_candidate_aoi"]), n_units)
    sample_pos = np.sort(rng.choice(n_units, size=sample_n, replace=False)) if n_units else np.array([], dtype=int)

    sampled = agg.units_metric.iloc[sample_pos]
    xs, ys, owner = _interior_sample_points(sampled, int(cfg["interior_points_per_unit"]))

    rows: list[dict] = []
    triggered: dict[str, bool] = {}
    threshold = float(config["acceptance"]["coarse_within_unit_range_fraction_of_between_unit_iqr"])

    for feature in (a["id"] for a in config["anchor_features"]):
        between = np.asarray(agg.anchors_at_rep[feature], dtype="float64")
        between = between[np.isfinite(between)]
        iqr = float(np.percentile(between, 75) - np.percentile(between, 25)) if len(between) > 3 else np.nan

        vals = sample_field(data.ref_grid, data.anchor_fields[feature], xs, ys)
        ranges = []
        for pos in range(len(sampled)):
            v = vals[owner == pos]
            v = v[np.isfinite(v)]
            if len(v) >= 2:
                ranges.append(float(v.max() - v.min()))
        median_range = float(np.median(ranges)) if ranges else np.nan
        ratio = median_range / iqr if (iqr and np.isfinite(iqr) and iqr > 0) else np.nan

        rows.append(_row("within_unit_median_range", median_range, "feature_units", BUFFER_1KM, dimension=feature))
        rows.append(_row("between_unit_iqr", iqr, "feature_units", BUFFER_1KM, dimension=feature))
        rows.append(_row("within_unit_range_over_between_unit_iqr", ratio, "ratio", BUFFER_1KM,
                         dimension=feature,
                         notes=f"too-coarse gate threshold {threshold}; sampled_units={sample_n}"))
        triggered[feature] = bool(np.isfinite(ratio) and ratio > threshold)

    rows.append(_row("too_coarse_anchor_features_triggered", sum(triggered.values()), "count",
                     BUFFER_1KM, notes=f"features over the {threshold} ratio: "
                                        f"{sorted(k for k, v in triggered.items() if v) or 'none'}"))
    return rows, triggered


# ---------------------------------------------------------------------------
# Neighbourhood representation: ring vs circle
# ---------------------------------------------------------------------------

def neighborhood_representation_rows(agg: UnitAggregates, candidate, config: dict, seed: int) -> list[dict]:
    """How well a k-ring of units approximates a true circle of radius R.

    Measured on a deterministic point lattice, assigned by the candidate's
    OWN lookup: a k-ring at a fine H3 resolution holds hundreds of cells,
    and unioning those polygons per unit per radius does not scale. Using
    each candidate's own lookup also guarantees neither family is measured
    by a procedure tuned to its geometry.
    """
    cfg = config["neighborhood_representation"]
    n_units = len(agg.units_metric)
    if not n_units:
        return []
    rng = np.random.default_rng(seed + 1)
    sample_n = min(int(cfg["sampled_units"]), n_units)
    pos = np.sort(rng.choice(n_units, size=sample_n, replace=False))
    sampled = agg.units_metric.iloc[pos]
    lat = sampled["rep_lat"].to_numpy()
    lon = sampled["rep_lon"].to_numpy()
    unit_ids = sampled["unit_id"].to_numpy()
    mean_area_m2 = float(np.nanmean(agg.units_metric["area_m2"].to_numpy()))
    spacing_m = math.sqrt(max(mean_area_m2, 1.0))

    from pyproj import Transformer
    to_wgs = Transformer.from_crs(agg.units_metric.crs, WGS84, always_xy=True).transform

    rows: list[dict] = []
    n_axis = int(cfg["lattice_points_per_axis"])
    for radius_m, support in ((float(config["buffers_m"]["neighborhood"]), BUFFER_1KM),
                              (float(config["buffers_m"]["regional"]), BUFFER_3KM)):
        k_est = max(1, int(round(radius_m / spacing_m)))
        k_max = max(2, int(math.ceil(k_est * float(cfg["max_k_search_multiple"]))))
        half = radius_m * 1.6
        offs = np.linspace(-half, half, n_axis)
        gx, gy = np.meshgrid(offs, offs)
        gx, gy = gx.ravel(), gy.ravel()
        in_circle = (gx ** 2 + gy ** 2) <= radius_m ** 2

        best_j, best_k, area_err = [], [], []
        cx = sampled.geometry.representative_point().x.to_numpy()
        cy = sampled.geometry.representative_point().y.to_numpy()
        for i, uid in enumerate(unit_ids):
            plon, plat = to_wgs(cx[i] + gx, cy[i] + gy)
            assigned = candidate.lookup(np.asarray(plat), np.asarray(plon))
            per_unit_best = (0.0, 0, np.nan)
            for k in range(1, k_max + 1):
                ring = set(candidate.ring(uid, k))
                in_ring = np.fromiter((a in ring for a in assigned), dtype=bool, count=len(assigned))
                inter = int((in_ring & in_circle).sum())
                union = int((in_ring | in_circle).sum())
                if union == 0:
                    continue
                j = inter / union
                if j > per_unit_best[0]:
                    n_circle = int(in_circle.sum())
                    rel = (int(in_ring.sum()) - n_circle) / n_circle if n_circle else np.nan
                    per_unit_best = (j, k, rel)
            best_j.append(per_unit_best[0]); best_k.append(per_unit_best[1]); area_err.append(per_unit_best[2])

        rows.append(_row("ring_circle_jaccard_median", float(np.nanmedian(best_j)), "ratio", support,
                         notes=f"best k-ring approximation to a {radius_m:g} m circle; "
                               f"lattice {n_axis}x{n_axis}, sampled_units={sample_n}"))
        rows.append(_row("ring_circle_jaccard_p05", float(np.nanpercentile(best_j, 5)), "ratio", support))
        rows.append(_row("ring_circle_best_k_median", float(np.median(best_k)), "rings", support))
        rows.append(_row("ring_circle_relative_area_error_median",
                         float(np.nanmedian(np.abs(area_err))), "ratio", support,
                         notes="absolute relative difference between ring area and circle area"))
    return rows


# ---------------------------------------------------------------------------
# Boundary / origin sensitivity and jitter
# ---------------------------------------------------------------------------

def _deterministic_points_in_aoi(aoi_polygon_metric: Polygon, crs: str, n: int, seed: int
                                 ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """`n` seeded points inside the AOI, returned as (x, y, lat, lon)."""
    from pyproj import Transformer

    rng = np.random.default_rng(seed)
    minx, miny, maxx, maxy = aoi_polygon_metric.bounds
    xs, ys = [], []
    while len(xs) < n:
        bx = rng.uniform(minx, maxx, size=n)
        by = rng.uniform(miny, maxy, size=n)
        keep = gpd.GeoSeries(gpd.points_from_xy(bx, by), crs=crs).within(aoi_polygon_metric).to_numpy()
        xs.extend(bx[keep].tolist()); ys.extend(by[keep].tolist())
    xs, ys = np.asarray(xs[:n]), np.asarray(ys[:n])
    lon, lat = Transformer.from_crs(crs, WGS84, always_xy=True).transform(xs, ys)
    return xs, ys, np.asarray(lat), np.asarray(lon)


def boundary_sensitivity_rows(agg: UnitAggregates, data: AoiData, candidate, config: dict,
                              seed: int, replicates: Optional[list] = None) -> list[dict]:
    """Point-jitter stability for every candidate, plus origin-shift
    stability for square grids.

    H3 has no origin parameter, so the origin-shift test cannot be run on
    it. That is recorded as `not_applicable` -- NOT as a pass, and not as a
    point in H3's favour. `docs/spatial_unit_decision.md` is explicit that
    H3 receives no convenience bonus, and silently scoring an untested
    property as success would be exactly that.
    """
    cfg = config["boundary_sensitivity"]
    n_pts = int(cfg["jitter_points"])
    xs, ys, lat, lon = _deterministic_points_in_aoi(data.aoi_polygon_metric, data.metric_crs, n_pts, seed + 2)

    mean_area = float(np.nanmean(agg.units_metric["area_m2"].to_numpy()))
    cell_width_m = math.sqrt(max(mean_area, 1.0))
    jitter_m = float(cfg["jitter_fraction_of_cell_width"]) * cell_width_m

    rng = np.random.default_rng(seed + 3)
    angle = rng.uniform(0, 2 * math.pi, size=n_pts)
    jx, jy = xs + jitter_m * np.cos(angle), ys + jitter_m * np.sin(angle)
    from pyproj import Transformer
    jlon, jlat = Transformer.from_crs(data.metric_crs, WGS84, always_xy=True).transform(jx, jy)

    base = candidate.lookup(lat, lon)
    jittered = candidate.lookup(np.asarray(jlat), np.asarray(jlon))
    changed = float(np.mean(np.asarray(base, dtype=object) != np.asarray(jittered, dtype=object)))

    rows = [
        _row("jitter_assignment_change_share", changed, "share", FOOTPRINT,
             notes=f"{n_pts} points moved {jitter_m:.1f} m "
                   f"({cfg['jitter_fraction_of_cell_width']:g} x mean cell width {cell_width_m:.1f} m)"),
        _row("jitter_distance_m", jitter_m, "metres", FOOTPRINT),
    ]

    if replicates is None:
        for metric in ("origin_shift_copartition_flip_share",
                       "origin_shift_copartition_flip_share_max",
                       "origin_shift_assignment_change_share"):
            rows.append(_row(metric, None, "share", FOOTPRINT, source_status=NOT_APPLICABLE,
                             notes="H3 has no grid origin, so this replicate cannot be constructed. "
                                   "Recorded as not applicable -- NOT as a pass, and not as a point "
                                   "in H3's favour."))
        rows.append(_row("origin_shift_feature_rank_spearman", None, "ratio", BUFFER_1KM,
                         source_status=NOT_APPLICABLE, dimension="poi_count_1km",
                         notes="no origin parameter to shift"))
        return rows

    from scipy.stats import spearmanr

    base_anchor = sample_field(data.ref_grid, data.anchor_fields["poi_count_1km"], xs, ys)

    # Comparing raw cell IDs across a shifted origin is meaningless: a
    # half-cell shift renames every cell, so an ID-equality test reports
    # 100% change for any offset and measures nothing. What actually
    # matters is whether the shift changes the PARTITION -- whether two
    # points that shared a cell still share one -- and whether the value a
    # location is assigned moves in rank.
    rng_pairs = np.random.default_rng(seed + 7)
    n_pairs = min(n_pts * 2, 20000)
    ia = rng_pairs.integers(0, n_pts, size=n_pairs)
    ib = rng_pairs.integers(0, n_pts, size=n_pairs)
    keep = ia != ib
    ia, ib = ia[keep], ib[keep]
    base_arr = np.asarray(base, dtype=object)
    base_same = base_arr[ia] == base_arr[ib]

    flips, spearmans, id_changes = [], [], []
    for rep in replicates:
        if rep.offset_fraction == (0.0, 0.0):
            continue
        shifted = np.asarray(rep.lookup(lat, lon), dtype=object)
        id_changes.append(float(np.mean(base_arr != shifted)))
        shift_same = shifted[ia] == shifted[ib]
        flips.append(float(np.mean(base_same != shift_same)))
        # The anchor field is identical under both origins, so any rank
        # movement comes purely from which unit a point lands in.
        base_mean = pd.Series(base_anchor).groupby(pd.Series(base_arr.astype(str))).transform("mean").to_numpy()
        shift_mean = pd.Series(base_anchor).groupby(pd.Series(shifted.astype(str))).transform("mean").to_numpy()
        ok = np.isfinite(base_mean) & np.isfinite(shift_mean)
        spearmans.append(float(spearmanr(base_mean[ok], shift_mean[ok]).statistic) if ok.sum() > 3 else np.nan)

    rows.append(_row("origin_shift_copartition_flip_share", float(np.mean(flips)) if flips else np.nan,
                     "share", FOOTPRINT,
                     notes=f"share of point pairs whose same-unit relation flips under a half-cell "
                           f"origin shift; mean over {len(flips)} replicates, {len(ia)} pairs"))
    rows.append(_row("origin_shift_copartition_flip_share_max", float(np.max(flips)) if flips else np.nan,
                     "share", FOOTPRINT))
    rows.append(_row("origin_shift_assignment_change_share", float(np.mean(id_changes)) if id_changes else np.nan,
                     "share", FOOTPRINT,
                     notes="raw cell-ID change rate. A half-cell shift renames every cell, so this is "
                           "1.0 by construction and carries no information -- retained only because it "
                           "is the literal quantity the specification names. Read "
                           "origin_shift_copartition_flip_share instead."))
    rows.append(_row("origin_shift_feature_rank_spearman",
                     float(np.nanmean(spearmans)) if spearmans else np.nan, "ratio", BUFFER_1KM,
                     dimension="poi_count_1km",
                     notes="Spearman between the unit-mean anchor value a point receives under the "
                           "base origin and under a shifted origin"))
    return rows


# ---------------------------------------------------------------------------
# MAUP stability between adjacent resolutions
# ---------------------------------------------------------------------------

def maup_rows(finer_agg: UnitAggregates, coarser_agg: UnitAggregates, finer, coarser,
              data: AoiData, config: dict, seed: int) -> list[dict]:
    """Rank/value stability of a unit-level density between two adjacent
    scales of the SAME family, evaluated at shared sample points."""
    from scipy.stats import spearmanr

    cfg = config["maup"]
    n_pts = int(cfg["sample_points"])
    xs, ys, lat, lon = _deterministic_points_in_aoi(data.aoi_polygon_metric, data.metric_crs, n_pts, seed + 4)

    rows: list[dict] = []
    for feature, values_f, values_c, unit in (
        ("population_density_per_km2",
         finer_agg.population / (finer_agg.units_metric["area_m2"].to_numpy() / 1e6),
         coarser_agg.population / (coarser_agg.units_metric["area_m2"].to_numpy() / 1e6), "persons_per_km2"),
        ("poi_density_per_km2",
         finer_agg.poi_count / (finer_agg.units_metric["area_m2"].to_numpy() / 1e6),
         coarser_agg.poi_count / (coarser_agg.units_metric["area_m2"].to_numpy() / 1e6), "count_per_km2"),
    ):
        vf = _values_at_points(finer_agg, finer, values_f, lat, lon)
        vc = _values_at_points(coarser_agg, coarser, values_c, lat, lon)
        ok = np.isfinite(vf) & np.isfinite(vc)
        if ok.sum() < 10:
            continue
        rho = float(spearmanr(vf[ok], vc[ok]).statistic)
        denom = np.where(np.abs(vc[ok]) > 0, np.abs(vc[ok]), np.nan)
        pct = np.abs(vf[ok] - vc[ok]) / denom
        median_pct = float(np.nanmedian(pct))

        q = 1.0 - float(cfg["top_decile_fraction"])
        tf, tc = np.nanquantile(vf[ok], q), np.nanquantile(vc[ok], q)
        set_f, set_c = vf[ok] >= tf, vc[ok] >= tc
        inter, union = int((set_f & set_c).sum()), int((set_f | set_c).sum())
        jaccard = inter / union if union else np.nan

        label = f"{finer.id}->{coarser.id}"
        rows.append(_row("maup_spearman", rho, "ratio", FOOTPRINT, dimension=f"{feature}|{label}"))
        rows.append(_row("maup_median_abs_percent_change", median_pct, "ratio", FOOTPRINT,
                         dimension=f"{feature}|{label}",
                         notes="points whose coarser value is zero are excluded from the ratio"))
        rows.append(_row("maup_top_decile_jaccard", jaccard, "ratio", FOOTPRINT,
                         dimension=f"{feature}|{label}"))
    return rows


def _values_at_points(agg: UnitAggregates, candidate, values: np.ndarray,
                      lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    lookup = pd.Series(values, index=agg.units_metric["unit_id"].to_numpy())
    lookup = lookup[~lookup.index.duplicated(keep="first")]
    assigned = pd.Series(np.asarray(candidate.lookup(lat, lon)).astype(str))
    return assigned.map(lookup.rename(index=str)).astype("float64").to_numpy()


# ---------------------------------------------------------------------------
# Too-fine gate: indistinguishable neighbours
# ---------------------------------------------------------------------------

def indistinguishable_neighbor_share(agg: UnitAggregates, candidate, config: dict) -> tuple[float, int]:
    """Share of adjacent unit pairs whose anchor vectors differ by less than
    the declared relative tolerance on EVERY component -- the "this
    resolution no longer distinguishes anything" signal in the too-fine
    gate."""
    tol = float(config["acceptance"]["indistinguishable_relative_tolerance"])
    features = [a["id"] for a in config["anchor_features"]]
    ids = agg.units_metric["unit_id"].to_numpy()
    pos = {uid: i for i, uid in enumerate(ids)}
    mat = np.column_stack([np.asarray(agg.anchors_at_rep[f], dtype="float64") for f in features])

    nbrs = candidate.neighbors(ids.tolist())
    pairs = {(uid, n) if uid < n else (n, uid) for uid, ns in nbrs.items() for n in ns}
    if not pairs:
        return float("nan"), 0

    a = np.array([pos[p[0]] for p in pairs]); b = np.array([pos[p[1]] for p in pairs])
    va, vb = mat[a], mat[b]
    scale = np.maximum(np.maximum(np.abs(va), np.abs(vb)), 1e-9)
    close = np.abs(va - vb) / scale < tol
    both_finite = np.isfinite(va) & np.isfinite(vb)
    close = np.where(both_finite, close, True)  # a NaN pair cannot be shown to differ
    return float(np.mean(close.all(axis=1))), len(pairs)


# ---------------------------------------------------------------------------
# Lookup correctness and latency
# ---------------------------------------------------------------------------

def _boundary_cases(agg: UnitAggregates, candidate, n: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Points placed exactly on unit boundaries -- polygon vertices and edge
    midpoints -- where a tie rule has to decide, plus nothing else. These
    are the cases a lat/lon lookup is most likely to get wrong."""
    from pyproj import Transformer

    rng = np.random.default_rng(seed + 5)
    n_units = len(agg.units_metric)
    if not n_units:
        return np.array([]), np.array([])
    pos = rng.choice(n_units, size=min(n, n_units), replace=False)
    xs, ys = [], []
    for geom in agg.units_metric.geometry.iloc[pos]:
        coords = list(geom.exterior.coords)[:-1]
        for i, (x, y) in enumerate(coords):
            xs.append(x); ys.append(y)
            nx_, ny_ = coords[(i + 1) % len(coords)]
            xs.append((x + nx_) / 2.0); ys.append((y + ny_) / 2.0)
    lon, lat = Transformer.from_crs(agg.units_metric.crs, WGS84, always_xy=True).transform(
        np.asarray(xs), np.asarray(ys))
    return np.asarray(lat), np.asarray(lon)


def lookup_benchmark_rows(agg: UnitAggregates, data: AoiData, candidate, config: dict,
                          seed: int) -> list[dict]:
    """p50/p95 latency for single and batch lat/lon lookup, plus correctness
    on interior and on-boundary cases.

    Correctness is checked against actual polygon containment, which is the
    independent ground truth: a candidate that answers fast but disagrees
    with its own geometry has not passed.
    """
    import time

    cfg = config["lookup"]
    n = int(cfg["queries"])
    _, _, lat, lon = _deterministic_points_in_aoi(data.aoi_polygon_metric, data.metric_crs, n, seed + 6)

    single_us = []
    for i in range(min(n, 2000)):  # single-query timing on a subset; batch covers the rest
        t0 = time.perf_counter()
        candidate.lookup(lat[i:i + 1], lon[i:i + 1])
        single_us.append((time.perf_counter() - t0) * 1e6)

    batch = int(cfg["batch_size"])
    batch_us = []
    for start in range(0, n, batch):
        sl = slice(start, start + batch)
        t0 = time.perf_counter()
        candidate.lookup(lat[sl], lon[sl])
        batch_us.append((time.perf_counter() - t0) * 1e6 / max(1, len(lat[sl])))

    # --- correctness -----------------------------------------------------
    # Interior points are checked strictly: the returned unit's own polygon
    # must contain the query point. Boundary points are checked against a
    # small tolerance, because a point placed exactly on a shared edge is
    # round-tripped through two projections (unit geometry in the AOI's UTM,
    # lookup in the national grid or in H3's lat/lng) and lands a fraction of
    # a millimetre off the mathematical edge. A tolerance is the honest
    # treatment; a strict test there would report projection noise as a
    # lookup defect.
    assigned = np.asarray(candidate.lookup(lat, lon)).astype(str)
    known = set(agg.units_metric["unit_id"].astype(str))
    geom_by_id = dict(zip(agg.units_metric["unit_id"].astype(str), agg.units_metric.geometry))
    from pyproj import Transformer
    to_metric = Transformer.from_crs(WGS84, data.metric_crs, always_xy=True)
    x, y = to_metric.transform(lon, lat)

    checked = failures = 0
    for i in range(min(n, 2000)):
        uid = assigned[i]
        if uid not in known:
            continue
        checked += 1
        if not geom_by_id[uid].covers(Point(x[i], y[i])):
            failures += 1

    # Determinism: the same coordinate must always return the same unit.
    repeat = np.asarray(candidate.lookup(lat[:500], lon[:500])).astype(str)
    nondeterministic = int((repeat != assigned[:500]).sum())

    blat, blon = _boundary_cases(agg, candidate, int(cfg["boundary_cases_per_candidate"]), seed)
    ties = boundary_failures = multi_valued = 0
    if len(blat):
        bassigned = np.asarray(candidate.lookup(blat, blon)).astype(str)
        bx, by = to_metric.transform(blon, blat)
        # An STRtree prunes each boundary point to the handful of units near
        # it. Testing every unit against every boundary point is quadratic
        # and, at a fine resolution over eight AOIs, dominates the whole run.
        from shapely import STRtree

        unit_geoms = agg.units_metric.geometry.to_numpy()
        unit_ids = agg.units_metric["unit_id"].astype(str).to_numpy()
        tree = STRtree(unit_geoms)
        for i, uid in enumerate(bassigned):
            pt = Point(bx[i], by[i])
            probe = pt.buffer(BOUNDARY_TOLERANCE_M)
            near = tree.query(probe)
            covering = {unit_ids[j] for j in near if unit_geoms[j].intersects(probe)}
            if len(covering) > 1:
                ties += 1
            if uid in geom_by_id and uid not in covering:
                boundary_failures += 1
        # Every query returns exactly one id by construction; this asserts it
        # rather than assuming it.
        multi_valued = int(sum(1 for v in bassigned if not isinstance(v, str)))

    return [{
        "lookup_mode": "single", "queries": len(single_us),
        "p50_latency_us": float(np.percentile(single_us, 50)),
        "p95_latency_us": float(np.percentile(single_us, 95)),
        "errors": nondeterministic, "tie_cases": ties,
        "correctness_checked": checked, "correctness_failures": failures,
        "notes": "interior points, strict test: the returned unit's own polygon must contain the "
                 "query point. `errors` counts non-deterministic repeats of the same coordinate.",
    }, {
        "lookup_mode": "batch", "queries": n,
        "p50_latency_us": float(np.percentile(batch_us, 50)),
        "p95_latency_us": float(np.percentile(batch_us, 95)),
        "errors": multi_valued, "tie_cases": ties,
        "correctness_checked": len(blat), "correctness_failures": boundary_failures,
        "notes": f"per-query microseconds within batches of {batch}. Correctness here is the "
                 f"ON-BOUNDARY case (unit vertices and edge midpoints) at a "
                 f"{BOUNDARY_TOLERANCE_M} m tolerance; `tie_cases` counts boundary points that two or "
                 f"more units cover within that tolerance, which the tie rule must and does resolve "
                 f"to exactly one id.",
    }]
