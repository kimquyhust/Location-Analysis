"""Gate 3 per-AOI feature computation from prepared inputs.

`compute_aoi_features` is a pure function of an `AoiInputs` bundle plus
the configs, so the whole feature contract can be exercised on a synthetic
AOI (tests) exactly as it is on a real one (runner). All I/O -- parsing
the PBF, opening rasters, resolving provenance -- lives in
`run_gate3_mvp.py`.

Feature semantics come from `config/features.yaml` `semantics`
(feature_set_version 0.3.0); `config/gate3_mvp.yaml` only says which AOIs
run and which sources are (not) available.

Denominator policy (`semantics.raster.worldcover`): `valid_land_support_
area_km2` = cell area x (valid classified WorldCover fraction - permanent-
water fraction). It is the denominator of every density and ratio that
the dictionary defines "per valid land-support area"; a cell with no land
support (open water) gets `denominator_zero`, one below the floor
`denominator_below_minimum`.

Ratio policy (`semantics.ratios`): the numerator of `built_up_ratio` and
`osm_industrial_site_area_ratio` is measured INSIDE the same land-support
mask -- built-up surface or industrial polygon lying over WorldCover
permanent water / NoData is excluded -- so the ratio is <= 1 by
construction. Both numerators are computed as fractions of the cell in the
raster CRS, exactly like the denominator, so no cross-CRS area ratio can
push a value over 1. Nothing is clipped: the unmasked numerators are kept
as QA columns (`_..._unmasked`) and any public ratio outside [0, 1] beyond
the configured tolerance fails validation.

Entity policy (`semantics.osm_entities`): when the OSM parser could not
assemble a relevant entity of category C in this AOI, every feature that
reads C -- its count, richness/total, its distance, industrial
area/distance -- is null with `entity_assembly_failed` for the whole AOI.
When the OSM source itself is unavailable every OSM-derived feature is
null with `source_unavailable` and `osm_query_complete` is false.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from shapely.geometry import Polygon
from shapely.ops import transform as shp_transform
from shapely.ops import unary_union

from .poi import (OK, canonical_pois, complete_search_radius, counts_within,
                  distance_with_status, nearest_distance, park_geometries, richness_within)
from .raster import RasterBand, class_area_fractions, pixel_weights, valid_mask, weighted_sum
from .roads import road_features
from .schema import (COUNT_FEATURES_1KM, COUNT_FEATURES_3KM, DISTANCE_FEATURES, STATUS_COLUMN_OF,
                     contract_columns)

WGS84 = "EPSG:4326"
SOURCE_UNAVAILABLE = "source_unavailable"


def denominator_status(land_support_km2: np.ndarray, area_m2: np.ndarray, lc_ok: np.ndarray,
                       min_fraction: float, other_ok: Optional[np.ndarray] = None,
                       other_failure: str = "coverage_incomplete") -> np.ndarray:
    """Status of any feature divided by valid land support: the numerator's
    own precondition (`other_ok`), then land-cover coverage, then a zero or
    below-floor denominator. Vectorised over cells."""
    n = len(land_support_km2)
    ok_other = np.ones(n, dtype=bool) if other_ok is None else np.asarray(other_ok, dtype=bool)
    ls = np.nan_to_num(np.asarray(land_support_km2, dtype="float64"), nan=0.0)
    frac = np.where(area_m2 > 0, ls * 1e6 / area_m2, 0.0)
    status = np.full(n, OK, dtype=object)
    status[frac < min_fraction] = "denominator_below_minimum"
    status[ls <= 0] = "denominator_zero"
    status[~np.asarray(lc_ok, dtype=bool)] = "coverage_incomplete"
    status[~ok_other] = other_failure
    return status


def unit_interval(values: np.ndarray, tolerance: float) -> np.ndarray:
    """Snap float noise within `tolerance` of 0 or 1 back onto the
    interval; leave anything further outside untouched so validation sees
    it. This is NOT clipping."""
    v = np.asarray(values, dtype="float64").copy()
    v[(v < 0) & (v >= -tolerance)] = 0.0
    v[(v > 1) & (v <= 1 + tolerance)] = 1.0
    return v


@dataclass
class AoiInputs:
    aoi_id: str
    context: str
    metric_crs: str
    units: gpd.GeoDataFrame            # EPSG:4326; unit_id, area_m2, aoi_overlap_fraction, rep_lat, rep_lon
    halo_polygon_metric: Polygon       # the clipped source's extent, in metric CRS
    poi_metric: gpd.GeoDataFrame       # deduplicated canonical entities, original geometry
    roads_metric: gpd.GeoDataFrame     # accepted driveable ways with is_major
    intersections_metric: gpd.GeoDataFrame
    area_metric: gpd.GeoDataFrame      # area_categories (industrial_site, park_area, ...)
    poi_duplicates_dropped: int
    worldcover: RasterBand
    worldpop: RasterBand
    builtup: RasterBand
    osm_ingest_status: str = "ok"
    # category -> number of relevant OSM entities the parser could not
    # assemble in this AOI (poi.osm_extract `assembly_failures_by_category`).
    entity_assembly_failures: dict = field(default_factory=dict)


# --- raster block ----------------------------------------------------------

def _land_fraction_of(geom_wc, wc: RasterBand, nodata_class: int, land_excl: list[int]) -> float:
    """Share of `geom_wc` (already in the WorldCover CRS) under valid
    land-support pixels."""
    if geom_wc.is_empty or geom_wc.area <= 0:
        return 0.0
    w = pixel_weights(geom_wc, wc.transform, wc.shape)
    fracs, valid = class_area_fractions(wc, w, nodata_class)
    return valid - sum(fracs.get(c, 0.0) for c in land_excl)


def _built_up_fractions(geom_bu, geom_wc, bu: RasterBand, bu_valid: np.ndarray, pixel_area_m2: float,
                        mask_needed: bool, to_wc, wc: RasterBand, nodata_class: int,
                        land_excl: list[int]) -> tuple[float, float, float, float]:
    """(native weighted sum, valid coverage, built fraction of the cell,
    built fraction of the cell inside the land-support mask).

    The fraction of the cell that is built-up is sum over pixels of
    (value / pixel_area) x (pixel area inside the cell / cell area), all in
    the built-up raster CRS. With `mask_needed`, every built-up pixel box
    is reprojected onto the WorldCover CRS, intersected with the cell
    polygon THERE (`geom_wc`, the same geometry the denominator uses), and
    its built-up share is scaled by the land-support area of that piece
    (uniform-within-pixel assumption). Reprojected boxes share edges and
    are disjoint, so the masked numerator is a subset measure of the
    denominator's land-support area in one CRS: <= 1 by construction, not
    by clipping."""
    w = pixel_weights(geom_bu, bu.transform, bu.shape)
    total, vfrac, _ = weighted_sum(bu, w, bu_valid)
    if not len(w.rows):
        return total, vfrac, 0.0, 0.0
    v = bu_valid[w.rows, w.cols]
    vals = bu.array[w.rows, w.cols].astype("float64")
    share = np.where(v, vals / pixel_area_m2, 0.0)          # built share of each pixel
    piece_frac_of_cell = w.fraction * w.pixel_area / w.unit_area  # each piece's share of the cell
    built_frac = float((share * piece_frac_of_cell).sum())
    if not mask_needed:
        return total, vfrac, built_frac, built_frac
    a, e = bu.transform.a, bu.transform.e
    cell_area_wc = geom_wc.area
    masked = 0.0
    for r, c, s in zip(w.rows, w.cols, share):
        if s <= 0:
            continue
        x0 = bu.transform.c + c * a
        y1 = bu.transform.f + r * e
        box_wc = shp_transform(to_wc, shapely.box(x0, y1 + e, x0 + a, y1))
        piece = box_wc.intersection(geom_wc)
        if piece.is_empty or piece.area <= 0:
            continue
        land_area = _land_fraction_of(piece, wc, nodata_class, land_excl) * piece.area
        masked += s * land_area / cell_area_wc
    return total, vfrac, built_frac, float(masked)


def raster_block(inputs: AoiInputs, sem: dict) -> pd.DataFrame:
    """Area-weighted raster features for every unit plus their coverage and
    the land-support denominator."""
    rc = sem["raster"]
    min_cov = float(rc["minimum_coverage_fraction"])
    wc_cfg = rc["worldcover"]
    nodata_class = int(wc_cfg["nodata_class"])
    rollups = {k: [int(c) for c in v] for k, v in wc_cfg["rollups"].items()}
    land_excl = [int(c) for c in wc_cfg["land_support_excludes"]]
    min_ls = float(wc_cfg["minimum_land_support_fraction"])
    tol = float(sem["ratios"]["unit_interval_tolerance"])

    units = inputs.units
    n = len(units)
    area_m2 = units["area_m2"].to_numpy(dtype="float64")

    # --- WorldCover: class fractions of the unit ------------------------
    wc = inputs.worldcover
    units_wc = units.to_crs(wc.crs)
    valid_frac = np.zeros(n); land_frac = np.zeros(n)
    rollup_frac = {k: np.zeros(n) for k in rollups}
    for i, geom in enumerate(units_wc.geometry.to_numpy()):
        w = pixel_weights(geom, wc.transform, wc.shape)
        fracs, valid = class_area_fractions(wc, w, nodata_class)
        valid_frac[i] = valid
        land_frac[i] = valid - sum(fracs.get(c, 0.0) for c in land_excl)
        for name, codes in rollups.items():
            rollup_frac[name][i] = sum(fracs.get(c, 0.0) for c in codes)
    lc_ok = valid_frac >= min_cov
    lc_status = np.where(lc_ok, OK, "coverage_incomplete").astype(object)
    land_support_km2 = np.where(lc_ok, land_frac * area_m2 / 1e6, np.nan)
    land_valid_km2 = np.where(lc_ok, valid_frac * area_m2 / 1e6, np.nan)

    out = pd.DataFrame(index=units.index)
    for name in rollups:
        with np.errstate(invalid="ignore", divide="ignore"):
            ratio = np.where(valid_frac > 0, rollup_frac[name] / valid_frac, np.nan)
        out[name] = np.where(lc_ok, unit_interval(ratio, tol), np.nan)
    out["land_cover_ratio_status"] = lc_status
    out["land_cover_coverage_fraction"] = unit_interval(valid_frac, tol)
    out["land_cover_valid_area_km2"] = land_valid_km2
    out["valid_land_support_area_km2"] = land_support_km2
    out["_land_support_fraction"] = land_frac

    # --- WorldPop: area-conserving count --------------------------------
    wp = inputs.worldpop
    wp_valid = valid_mask(wp)
    units_wp = units.to_crs(wp.crs)
    pop = np.zeros(n); pop_window = np.zeros(n); pop_nodata = np.zeros(n)
    for i, geom in enumerate(units_wp.geometry.to_numpy()):
        w = pixel_weights(geom, wp.transform, wp.shape)
        total, vfrac, ndfrac = weighted_sum(wp, w, wp_valid)
        pop[i] = total
        pop_window[i] = w.window_fraction
        pop_nodata[i] = ndfrac
    if rc["worldpop"].get("nodata_means_zero_persons", False):
        pop_ok = pop_window >= min_cov          # publisher NoData is 0 persons, not missing
    else:
        pop_ok = (pop_window - pop_nodata) >= min_cov
    out["population_count"] = np.where(pop_ok, pop, np.nan)
    out["population_count_status"] = np.where(pop_ok, OK, "coverage_incomplete").astype(object)
    out["population_coverage_fraction"] = unit_interval(pop_window, tol)
    out["population_nodata_area_fraction"] = unit_interval(pop_nodata, tol)

    dens_status = denominator_status(land_support_km2, area_m2, lc_ok, min_ls, other_ok=pop_ok)
    with np.errstate(invalid="ignore", divide="ignore"):
        dens = pop / land_support_km2
    out["population_density"] = np.where(dens_status == OK, dens, np.nan)
    out["population_density_status"] = dens_status

    # --- GHS-BUILT-S: built-up share inside the land-support mask -----------
    bu = inputs.builtup
    bu_valid = valid_mask(bu)
    units_bu = units.to_crs(bu.crs)
    pixel_area_m2 = float(rc["ghs_built_s"]["pixel_area_m2"])
    to_wc = Transformer.from_crs(bu.crs, wc.crs, always_xy=True).transform
    built_native = np.zeros(n); bu_vfrac = np.zeros(n)
    built_frac = np.zeros(n); built_frac_masked = np.zeros(n)
    wc_geoms = units_wc.geometry.to_numpy()
    for i, geom in enumerate(units_bu.geometry.to_numpy()):
        # A cell entirely under land-support pixels needs no mask.
        mask_needed = land_frac[i] < 1.0 - tol
        built_native[i], bu_vfrac[i], built_frac[i], built_frac_masked[i] = _built_up_fractions(
            geom, wc_geoms[i], bu, bu_valid, pixel_area_m2, mask_needed, to_wc, wc, nodata_class, land_excl)
    bu_ok = bu_vfrac >= min_cov
    bu_status = denominator_status(land_support_km2, area_m2, lc_ok, min_ls, other_ok=bu_ok)
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio_masked = built_frac_masked / land_frac
        ratio_unmasked = built_frac / land_frac
    out["built_up_ratio"] = np.where(bu_status == OK, unit_interval(ratio_masked, tol), np.nan)
    out["built_up_ratio_status"] = bu_status
    out["built_up_coverage_fraction"] = unit_interval(bu_vfrac, tol)
    out["_built_up_ratio_unmasked"] = np.where(bu_status == OK, ratio_unmasked, np.nan)
    out["_built_up_m2"] = built_native                       # raster-native sum, for conservation
    out["_built_up_m2_on_land_support"] = built_frac_masked * area_m2
    return out


# --- vector block ----------------------------------------------------------

def _radius_for(feature: str, buffers: dict) -> float:
    if feature.endswith("_1km"):
        return float(buffers["neighborhood"])
    if feature.endswith("_3km"):
        return float(buffers["regional"])
    raise ValueError(f"{feature}: no buffer radius suffix")


def _count_spec(features_cfg: dict, taxonomy: dict) -> dict[str, list[str]]:
    """Feature -> leaf categories it counts (rollups from features.yaml)."""
    rollups = features_cfg["parameters"]["poi_rollups"]
    all_cats = list(taxonomy["canonical_categories"].keys())
    spec = {
        "transit_stop_count_1km": rollups["transit_stop"],
        "school_count_1km": ["school"],
        "higher_education_count_3km": ["higher_education"],
        "hospital_count_3km": ["hospital"],
        "clinic_count_1km": ["clinic"],
        "pharmacy_count_1km": ["pharmacy"],
        "food_drink_count_1km": ["food_drink"],
        "retail_count_1km": rollups["retail"],
        "marketplace_count_1km": ["marketplace"],
        "mall_count_3km": ["mall"],
        "lodging_count_1km": ["lodging"],
        "attraction_culture_count_3km": ["attraction_culture"],
        "park_recreation_count_1km": ["park_recreation"],
        "poi_total_count_1km": all_cats,
        "poi_category_richness_1km": all_cats,
    }
    unknown = {c for cats in spec.values() for c in cats} - set(all_cats)
    if unknown:
        raise ValueError(f"count features reference categories absent from the taxonomy: {sorted(unknown)}")
    return spec


def _distance_spec(features_cfg: dict) -> dict[str, tuple[list[str], str]]:
    """Distance feature -> (categories read, spatial.yaml cap key)."""
    rollups = features_cfg["parameters"]["poi_rollups"]
    return {
        "distance_nearest_transit_stop_m": (rollups["transit_stop"], "transit_stop"),
        "distance_nearest_transport_hub_m": (rollups["transport_hub"], "transport_hub"),
        "distance_nearest_higher_education_m": (["higher_education"], "higher_education"),
        "distance_nearest_hospital_m": (["hospital"], "hospital"),
        "distance_nearest_park_m": (["park_recreation", "park_area"], "park"),
        "distance_nearest_osm_industrial_site_m": (["industrial_site"], "industrial_site"),
    }


OSM_DERIVED_FEATURES = (
    ["road_length_km", "major_road_length_km", "road_density_km_per_km2", "intersection_density_per_km2",
     "distance_nearest_major_road_m", "osm_industrial_site_area_ratio"]
    + COUNT_FEATURES_1KM + COUNT_FEATURES_3KM
    + [f for f in DISTANCE_FEATURES if f != "distance_nearest_urban_centre_km"]
)


def _industrial_fractions(units_wc: gpd.GeoDataFrame, industrial_wc, wc: RasterBand, nodata_class: int,
                          land_excl: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """(fraction of each cell under industrial polygons, fraction of each
    cell under industrial polygons AND land-support pixels), both measured
    in the WorldCover CRS like the denominator."""
    n = len(units_wc)
    raw = np.zeros(n); masked = np.zeros(n)
    if industrial_wc is None or industrial_wc.is_empty:
        return raw, masked
    parts = np.array(list(industrial_wc.geoms) if hasattr(industrial_wc, "geoms") else [industrial_wc], dtype=object)
    tree = shapely.STRtree(parts)
    unit_geoms = units_wc.geometry.to_numpy()
    unit_idx, part_idx = tree.query(unit_geoms, predicate="intersects")
    for i in np.unique(unit_idx):
        cell = unit_geoms[i]
        inter = unary_union([shapely.intersection(cell, parts[j]) for j in part_idx[unit_idx == i]])
        if inter.is_empty or inter.area <= 0:
            continue
        share = inter.area / cell.area
        raw[i] = share
        masked[i] = share * _land_fraction_of(inter, wc, nodata_class, land_excl)
    return raw, masked


def vector_block(inputs: AoiInputs, cfg: dict, sem: dict, spatial_cfg: dict, features_cfg: dict,
                 taxonomy: dict, land_support_km2: np.ndarray, land_frac: np.ndarray,
                 lc_ok: np.ndarray) -> pd.DataFrame:
    units = inputs.units
    n = len(units)
    area_m2 = units["area_m2"].to_numpy(dtype="float64")
    min_ls = float(sem["raster"]["worldcover"]["minimum_land_support_fraction"])
    tol = float(sem["ratios"]["unit_interval_tolerance"])
    fail_status = str(sem["osm_entities"]["assembly_failure_status"])
    units_metric = units.to_crs(inputs.metric_crs)
    rep = units_metric.geometry.representative_point().to_numpy()
    buffers = spatial_cfg["buffers_m"]
    caps = spatial_cfg["distance_search_caps_m"]
    regional = float(buffers["regional"])
    complete_r = complete_search_radius(rep, inputs.halo_polygon_metric)
    osm_ok = inputs.osm_ingest_status == "ok"
    failed_cats = {c for c, k in (inputs.entity_assembly_failures or {}).items() if k}
    out = pd.DataFrame(index=units.index)
    out["distance_search_complete_radius_m"] = complete_r

    if not osm_ok:
        # F4: nothing OSM-derived is computed from the (possibly stale or
        # empty) input frames when the source itself failed.
        for f in OSM_DERIVED_FEATURES:
            out[f] = np.nan
        for col in {STATUS_COLUMN_OF[f] for f in OSM_DERIVED_FEATURES}:
            out[col] = SOURCE_UNAVAILABLE
        out["_intersection_count"] = np.nan
        out["_industrial_ratio_unmasked"] = np.nan
        out["_industrial_area_m2_raw"] = np.nan
        out["_industrial_area_m2_on_land_support"] = np.nan
        out["distance_nearest_urban_centre_km"] = np.nan
        out["distance_nearest_urban_centre_km_status"] = cfg["sources"]["urban_centres"]["status"]
        out["osm_query_complete"] = False
        return out

    # --- roads -----------------------------------------------------------
    rf = road_features(units_metric, inputs.roads_metric, inputs.intersections_metric)
    out["road_length_km"] = rf.road_length_m / 1000.0
    out["major_road_length_km"] = rf.major_road_length_m / 1000.0
    out["road_features_status"] = OK
    dens_status = denominator_status(land_support_km2, area_m2, lc_ok, min_ls)
    with np.errstate(invalid="ignore", divide="ignore"):
        out["road_density_km_per_km2"] = np.where(dens_status == OK, rf.road_length_m / 1000.0 / land_support_km2, np.nan)
        out["intersection_density_per_km2"] = np.where(dens_status == OK, rf.intersection_count / land_support_km2, np.nan)
    out["road_density_status"] = dens_status
    out["intersection_density_status"] = dens_status.copy()
    out["_intersection_count"] = rf.intersection_count

    major = inputs.roads_metric[inputs.roads_metric["is_major"].astype(bool)] if len(inputs.roads_metric) else inputs.roads_metric
    d = nearest_distance(rep, major.geometry.to_numpy())
    out["distance_nearest_major_road_m"], out["distance_nearest_major_road_m_status"] = \
        distance_with_status(d, float(caps["major_road"]), complete_r)

    # --- POI counts (one status column per feature) -------------------------
    pois = canonical_pois(inputs.poi_metric, inputs.poi_duplicates_dropped)
    query_complete = complete_r >= regional
    spec = _count_spec(features_cfg, taxonomy)
    enabled = list(taxonomy["canonical_categories"].keys())
    for feature, cats in spec.items():
        radius = _radius_for(feature, buffers)
        if feature == "poi_category_richness_1km":
            vals = richness_within(rep, pois.count_points, pois.categories, radius, enabled)
        else:
            vals = counts_within(rep, pois.count_points, pois.categories, radius, cats)
        status = np.where(query_complete, OK, "coverage_incomplete").astype(object)
        if failed_cats.intersection(cats):
            status[:] = fail_status
        out[feature] = np.where(status == OK, vals, np.nan)
        out[STATUS_COLUMN_OF[feature]] = status

    # --- POI distances (original geometry) ---------------------------------
    def target_geoms(cats):
        if not len(pois.frame):
            return np.array([], dtype=object)
        return pois.frame[pois.frame["category"].isin(cats)].geometry.to_numpy()

    for feature, (cats, cap_key) in _distance_spec(features_cfg).items():
        if feature == "distance_nearest_park_m":
            targets = park_geometries(inputs.area_metric, inputs.poi_metric)
        elif feature == "distance_nearest_osm_industrial_site_m":
            targets = (inputs.area_metric[inputs.area_metric["area_category"] == "industrial_site"].geometry.to_numpy()
                       if len(inputs.area_metric) else np.array([], dtype=object))
        else:
            targets = target_geoms(cats)
        d = nearest_distance(rep, targets)
        value, status = distance_with_status(d, float(caps[cap_key]), complete_r)
        if failed_cats.intersection(cats):
            value, status = np.full(n, np.nan), np.full(n, fail_status, dtype=object)
        out[feature], out[f"{feature}_status"] = value, status

    # --- industrial area ratio (numerator inside the land-support mask) -----
    industrial = (inputs.area_metric[inputs.area_metric["area_category"] == "industrial_site"]
                  if len(inputs.area_metric) else inputs.area_metric)
    wc = inputs.worldcover
    wc_cfg = sem["raster"]["worldcover"]
    industrial_wc = (unary_union(industrial.to_crs(wc.crs).geometry.to_numpy()) if len(industrial) else None)
    ind_raw_frac, ind_masked_frac = _industrial_fractions(
        units.to_crs(wc.crs), industrial_wc, wc, int(wc_cfg["nodata_class"]),
        [int(c) for c in wc_cfg["land_support_excludes"]])
    ind_status = dens_status.copy()
    if "industrial_site" in failed_cats:
        ind_status[:] = fail_status
    with np.errstate(invalid="ignore", divide="ignore"):
        ind_ratio = ind_masked_frac / land_frac
        ind_ratio_unmasked = ind_raw_frac / land_frac
    out["osm_industrial_site_area_ratio"] = np.where(ind_status == OK, unit_interval(ind_ratio, tol), np.nan)
    out["osm_industrial_site_area_ratio_status"] = ind_status
    out["_industrial_ratio_unmasked"] = np.where(dens_status == OK, ind_ratio_unmasked, np.nan)
    out["_industrial_area_m2_raw"] = ind_raw_frac * area_m2
    out["_industrial_area_m2_on_land_support"] = ind_masked_frac * area_m2

    # --- urban centre: source not acquired ---------------------------------
    out["distance_nearest_urban_centre_km"] = np.nan
    out["distance_nearest_urban_centre_km_status"] = cfg["sources"]["urban_centres"]["status"]
    out["osm_query_complete"] = query_complete
    return out


# --- assembly ----------------------------------------------------------------

def compute_aoi_features(inputs: AoiInputs, cfg: dict, spatial_cfg: dict, features_cfg: dict,
                         taxonomy: dict, run_id: str, source_manifest_id: str,
                         computed_at_utc: str) -> pd.DataFrame:
    sem = features_cfg["semantics"]
    units = inputs.units
    r = raster_block(inputs, sem)
    lc_ok = (r["land_cover_ratio_status"] == OK).to_numpy()
    v = vector_block(inputs, cfg, sem, spatial_cfg, features_cfg, taxonomy,
                     r["valid_land_support_area_km2"].to_numpy(dtype="float64"),
                     r["_land_support_fraction"].to_numpy(dtype="float64"), lc_ok)

    unit = spatial_cfg["spatial_unit"]
    meta = pd.DataFrame({
        "spatial_unit_id": units["unit_id"].to_numpy(),
        "spatial_method": unit["method"],
        "spatial_resolution": int(unit["h3_resolution"]),
        "spatial_unit_area_km2": units["area_m2"].to_numpy(dtype="float64") / 1e6,
        "representative_lat": units["rep_lat"].to_numpy(dtype="float64"),
        "representative_lon": units["rep_lon"].to_numpy(dtype="float64"),
        "admin_province_code": None,
        "admin_commune_code": None,
        "run_id": run_id,
        "feature_set_version": str(features_cfg["feature_set_version"]),
        "source_manifest_id": source_manifest_id,
        "computed_at_utc": computed_at_utc,
        "osm_ingest_status": inputs.osm_ingest_status,
        "poi_taxonomy_version": str(taxonomy["version"]),
        "admin_province_match_status": cfg["sources"]["admin_province"]["status"],
        "admin_commune_match_status": cfg["sources"]["admin_commune"]["status"],
        "aoi_id": inputs.aoi_id, "aoi_context": inputs.context,
        "aoi_overlap_fraction": units["aoi_overlap_fraction"].to_numpy(dtype="float64"),
        "spatial_decision_status": unit.get("decision_status"),
        "spatial_metric_crs": inputs.metric_crs,
        "poi_source_policy": cfg["sources"]["poi_source_policy"],
        "road_source_policy": cfg["sources"]["road_source_policy"],
        "osm_entity_assembly_failures": (
            ";".join(f"{c}:{k}" for c, k in sorted((inputs.entity_assembly_failures or {}).items()) if k) or "none"),
    }, index=units.index)
    meta["admin_match_status"] = (f"province:{cfg['sources']['admin_province']['status']};"
                                  f"commune:{cfg['sources']['admin_commune']['status']}")
    meta["admin_province_code"] = meta["admin_province_code"].astype(object)
    meta["admin_commune_code"] = meta["admin_commune_code"].astype(object)

    df = pd.concat([meta, r, v], axis=1)
    cols = contract_columns(features_cfg)
    qa = [c for c in df.columns if c not in cols]
    return df[cols + qa].reset_index(drop=True)
