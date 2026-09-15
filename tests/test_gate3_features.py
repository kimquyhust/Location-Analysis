"""Gate 3 atomic-feature MVP: numerical behaviour of every aggregation on
synthetic inputs, the output contract, zero-vs-missing semantics, distance
caps and extract truncation, provenance verification, and deterministic
reruns. The run-dependent checks at the end skip cleanly without a run.
"""

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
import shapely
import yaml
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, Polygon, box

from features import poi as P
from features import raster as R
from features import roads as RD
from features.compute import AoiInputs, compute_aoi_features, denominator_status
from features.provenance import ProvenanceError, verify_aoi_sources
from features.schema import (STATUS_COLUMN_OF, contract_columns, load_features_config, validate_frame)
from spatial.aoi import build_aoi
from spatial.candidates import H3Grid

GATE3_ROOT = Path("data/gate3")


@pytest.fixture(scope="module")
def cfg():
    return yaml.safe_load(open("config/gate3_mvp.yaml"))


@pytest.fixture(scope="module")
def spatial_cfg():
    return yaml.safe_load(open("config/spatial.yaml"))


@pytest.fixture(scope="module")
def features_cfg():
    return load_features_config()


@pytest.fixture(scope="module")
def taxonomy():
    return yaml.safe_load(open("config/poi_taxonomy.yaml"))


# --- raster area weighting ---------------------------------------------------

def _band(arr, transform, nodata=None, crs="EPSG:32648"):
    return R.RasterBand(path=None, array=np.asarray(arr), transform=transform, crs=crs, nodata=nodata)


def test_boundary_pixels_are_apportioned_by_exact_overlap_area():
    t = from_origin(0, 100, 10, 10)
    arr = np.ones((10, 10))
    w = R.pixel_weights(box(5, 5, 30, 30), t, arr.shape)      # 2.5 x 2.5 pixels
    assert w.fraction.sum() * w.pixel_area == pytest.approx(625.0)
    assert w.window_fraction == pytest.approx(1.0)
    # corner pixels contribute a quarter, edge pixels a half, the centre 1.
    assert sorted(np.round(np.unique(w.fraction), 6)) == [0.25, 0.5, 1.0]


def test_population_is_conserved_when_cells_tile_a_region():
    """The sum over cells that partition a region equals the pixel sum of
    that region -- including pixels split between cells at odd offsets."""
    t = from_origin(0, 100, 10, 10)
    arr = np.random.default_rng(1).uniform(0, 50, (10, 10))
    band = _band(arr, t)
    parts = [box(0, 0, 47, 53), box(47, 0, 100, 53), box(0, 53, 47, 100), box(47, 53, 100, 100)]
    total = sum(R.weighted_sum(band, R.pixel_weights(p, t, arr.shape), R.valid_mask(band))[0] for p in parts)
    assert total == pytest.approx(arr.sum(), rel=1e-12)


def test_pixel_centre_assignment_would_not_conserve_but_area_weighting_does():
    """A 15 x 15 cell over 10 m pixels: centre assignment gives 4 pixels
    (400 units of area) or 1; the exact weighting gives 225."""
    t = from_origin(0, 100, 10, 10)
    w = R.pixel_weights(box(2, 2, 17, 17), t, (10, 10))
    assert w.fraction.sum() * w.pixel_area == pytest.approx(225.0)


def test_nodata_pixels_are_excluded_from_sums_and_reported_as_coverage():
    t = from_origin(0, 100, 10, 10)
    arr = np.full((10, 10), 5.0); arr[0:5, :] = -99999.0
    band = _band(arr, t, nodata=-99999.0)
    w = R.pixel_weights(box(0, 0, 100, 100), t, arr.shape)
    total, valid_frac, nodata_frac = R.weighted_sum(band, w, R.valid_mask(band))
    assert total == pytest.approx(5.0 * 50)
    assert valid_frac == pytest.approx(0.5) and nodata_frac == pytest.approx(0.5)
    assert band.nodata != 0, "NoData must never be zero"


def test_unit_outside_the_raster_window_shows_reduced_window_fraction():
    t = from_origin(0, 100, 10, 10)
    w = R.pixel_weights(box(90, 90, 120, 120), t, (10, 10))
    assert w.window_fraction == pytest.approx(100 / 900)


def test_worldcover_class_fractions_follow_the_legend_rollup(features_cfg):
    t = from_origin(0, 100, 10, 10)
    arr = np.zeros((10, 10), dtype="uint8")
    arr[:, :3] = 10; arr[:, 3:5] = 20; arr[:, 5:6] = 30; arr[:, 6:8] = 80; arr[:, 8:9] = 95; arr[:, 9:] = 0
    band = _band(arr, t, nodata=0)
    w = R.pixel_weights(box(0, 0, 100, 100), t, arr.shape)
    fracs, valid = R.class_area_fractions(band, w, nodata_class=0)
    assert valid == pytest.approx(0.9)                     # class 0 excluded
    roll = features_cfg["semantics"]["raster"]["worldcover"]["rollups"]
    assert sum(fracs.get(c, 0) for c in roll["tree_cover_ratio"]) == pytest.approx(0.3)
    assert sum(fracs.get(c, 0) for c in roll["grass_shrub_ratio"]) == pytest.approx(0.3)
    assert sum(fracs.get(c, 0) for c in roll["water_wetland_ratio"]) == pytest.approx(0.3)
    land = valid - sum(fracs.get(c, 0) for c in features_cfg["semantics"]["raster"]["worldcover"]["land_support_excludes"])
    assert land == pytest.approx(0.7)                      # permanent water leaves land support


def test_denominator_status_orders_failures_and_applies_the_floor():
    ls = np.array([0.1, 0.0, 0.0005, 0.1, 0.1])
    area = np.full(5, 0.1e6)
    lc_ok = np.array([True, True, True, False, True])
    other = np.array([True, True, True, True, False])
    st = denominator_status(ls, area, lc_ok, min_fraction=0.01, other_ok=other, other_failure="source_unavailable")
    assert list(st) == ["ok", "denominator_zero", "denominator_below_minimum", "coverage_incomplete", "source_unavailable"]


# --- roads --------------------------------------------------------------------

def _units(polys, crs="EPSG:32648"):
    return gpd.GeoDataFrame({"unit_id": [f"u{i}" for i in range(len(polys))]}, geometry=polys, crs=crs)


def test_road_length_is_clipped_to_each_unit_and_split_across_units():
    units = _units([box(0, 0, 100, 100), box(100, 0, 200, 100)])
    roads = gpd.GeoDataFrame({"is_major": [True, False]},
                             geometry=[LineString([(-50, 50), (250, 50)]), LineString([(10, 10), (10, 90)])],
                             crs="EPSG:32648")
    rf = RD.road_features(units, roads, gpd.GeoDataFrame(geometry=[], crs="EPSG:32648"))
    assert list(rf.road_length_m) == pytest.approx([180.0, 100.0])
    assert list(rf.major_road_length_m) == pytest.approx([100.0, 100.0])


def test_intersections_are_counted_per_unit_and_a_shared_edge_point_only_once():
    units = _units([box(0, 0, 100, 100), box(100, 0, 200, 100)])
    pts = gpd.GeoDataFrame(geometry=[Point(50, 50), Point(100, 50), Point(150, 50), Point(500, 500)], crs="EPSG:32648")
    counts = RD.points_per_unit(units, pts)
    assert counts.sum() == 3 and list(counts) == [2, 1]


def test_intersections_come_from_shared_osm_nodes_with_degree_at_least_three():
    """Two ways crossing geometrically without a shared node yield no
    intersection; a node shared by two ways (degree 4) does."""
    from poi.osm_extract import parse_osm_aoi
    ex = parse_osm_aoi(Path("tests/fixtures/tiny_test.osm.pbf"))
    assert ex.minimum_degree == 3
    assert (ex.intersections_gdf["degree"] >= 3).all()


def test_road_class_policy_comes_from_features_config(features_cfg):
    from poi.road_classes import classify_highway
    rc = features_cfg["parameters"]["road_classes"]
    assert classify_highway("primary_link", rc) == (True, True, True)
    assert classify_highway("footway", rc) == (False, False, False)
    assert classify_highway("residential", rc) == (True, False, False)


# --- POI ----------------------------------------------------------------------

def _pois():
    rows = [
        ("node", 1, "school", Point(0, 0), {"amenity": "school", "name": "A"}),
        ("node", 2, "school", Point(900, 0), {"amenity": "school", "name": "B"}),
        ("node", 3, "school", Point(1100, 0), {"amenity": "school", "name": "C"}),   # outside 1 km
        ("way", 4, "hospital", box(2000, -50, 2100, 50), {"amenity": "hospital"}),  # polygon, edge at 2000 m
        ("node", 5, "convenience", Point(10, 10), {"shop": "convenience"}),
        ("node", 6, "supermarket", Point(20, 20), {"shop": "supermarket"}),
        ("node", 7, "mall", Point(30, 30), {"shop": "mall"}),
        ("node", 8, "park_recreation", Point(500, 0), {"leisure": "park"}),
    ]
    return gpd.GeoDataFrame({"osm_type": [r[0] for r in rows], "osm_id": [r[1] for r in rows],
                             "category": [r[2] for r in rows], "raw_tags": [r[4] for r in rows]},
                            geometry=[r[3] for r in rows], crs="EPSG:32648")


def test_counts_use_buffer_membership_and_the_1km_boundary_is_inclusive():
    pois = P.canonical_pois(_pois(), 0)
    rep = np.array([Point(0, 0)], dtype=object)
    assert P.counts_within(rep, pois.count_points, pois.categories, 1000.0, ["school"])[0] == 2
    assert P.counts_within(rep, pois.count_points, pois.categories, 1000.0, ["hospital"])[0] == 0
    assert P.counts_within(rep, pois.count_points, pois.categories, 3000.0, ["hospital"])[0] == 1
    # exactly on the buffer edge is inside (dwithin is <=)
    rep_edge = np.array([Point(-100, 0)], dtype=object)
    assert P.counts_within(rep_edge, pois.count_points, pois.categories, 1000.0, ["school"])[0] == 2


def test_rollups_are_disjoint_and_total_counts_each_entity_once(features_cfg, taxonomy):
    pois = P.canonical_pois(_pois(), 0)
    rep = np.array([Point(0, 0)], dtype=object)
    retail = features_cfg["parameters"]["poi_rollups"]["retail"]
    assert "mall" not in retail and "marketplace" not in retail
    assert P.counts_within(rep, pois.count_points, pois.categories, 1000.0, retail)[0] == 2
    all_cats = list(taxonomy["canonical_categories"])
    total = P.counts_within(rep, pois.count_points, pois.categories, 1000.0, all_cats)[0]
    per_cat = sum(P.counts_within(rep, pois.count_points, pois.categories, 1000.0, [c])[0] for c in all_cats)
    assert total == per_cat == 6
    rich = P.richness_within(rep, pois.count_points, pois.categories, 1000.0, all_cats)[0]
    assert rich == 5   # school, convenience, supermarket, mall, park_recreation


def test_polygon_pois_are_counted_by_point_on_surface_and_measured_to_the_edge():
    pois = P.canonical_pois(_pois(), 0)
    hosp = pois.frame[pois.frame["category"] == "hospital"]
    d = P.nearest_distance(np.array([Point(0, 0)], dtype=object), hosp.geometry.to_numpy())
    assert d[0] == pytest.approx(2000.0)                 # edge, not centroid (2050)
    idx = list(pois.frame["osm_id"]).index(4)
    assert hosp.geometry.iloc[0].contains(pois.count_points[idx])


def test_cross_geometry_duplicates_are_collapsed_before_counting():
    from poi.dedup import deduplicate_osm_pois
    node = gpd.GeoDataFrame({"osm_type": ["node", "way"], "osm_id": [1, 2], "category": ["hospital"] * 2,
                             "name": ["Bach Mai", "Bach Mai"], "raw_tags": [{}, {}]},
                            geometry=[Point(105.85, 21.0), box(105.8499, 20.9999, 105.8501, 21.0001)], crs="EPSG:4326")
    kept, dropped = deduplicate_osm_pois(node, max_distance_m=75, metric_crs="EPSG:32648")
    assert len(kept) == 1 and len(dropped) == 1
    assert kept.iloc[0]["osm_type"] == "way"


def test_distance_cap_and_extract_truncation_never_return_the_cap():
    d = np.array([500.0, 6000.0, np.nan, np.nan, 4000.0])
    complete = np.array([3000.0, 3000.0, 3000.0, 60000.0, 5000.0])
    value, status = P.distance_with_status(d, cap_m=50000.0, complete_radius_m=complete)
    assert list(status) == ["ok", "search_truncated_by_extract", "search_truncated_by_extract",
                            "not_found_within_cap", "ok"]
    assert value[0] == 500.0 and value[4] == 4000.0
    assert np.isnan(value[1:4]).all()
    # a found distance beyond the cap but inside a complete search is not found within cap
    value, status = P.distance_with_status(np.array([70000.0]), 50000.0, np.array([80000.0]))
    assert status[0] == "not_found_within_cap" and np.isnan(value[0])


def test_industrial_area_is_polygon_intersection_and_unioned_first():
    units = _units([box(0, 0, 100, 100)])
    polys = gpd.GeoDataFrame({"area_category": ["industrial_site"] * 2},
                             geometry=[box(50, 0, 150, 100), box(60, 0, 160, 100)], crs="EPSG:32648")
    area = P.intersection_area_per_unit(units, polys)
    assert area[0] == pytest.approx(50 * 100)            # overlap not double-counted
    # centroid of the union is outside the unit; a centroid proxy would give 0
    assert not units.geometry.iloc[0].contains(shapely.union_all(polys.geometry.to_numpy()).centroid)


def test_park_geometries_take_each_osm_element_once():
    area = gpd.GeoDataFrame({"osm_type": ["way"], "osm_id": [10], "area_category": ["park_area"]},
                            geometry=[box(0, 0, 10, 10)], crs="EPSG:32648")
    pois = gpd.GeoDataFrame({"osm_type": ["way", "node"], "osm_id": [10, 11], "category": ["park_recreation"] * 2,
                             "raw_tags": [{"leisure": "park"}, {"leisure": "playground"}]},
                            geometry=[box(0, 0, 10, 10), Point(5, 5)], crs="EPSG:32648")
    assert len(P.park_geometries(area, pois)) == 1


# --- end-to-end on a synthetic AOI -----------------------------------------------

def _write_raster(path, arr, transform, crs, nodata, dtype):
    with rasterio.open(path, "w", driver="GTiff", width=arr.shape[1], height=arr.shape[0], count=1,
                       dtype=dtype, crs=crs, transform=transform, nodata=nodata) as dst:
        dst.write(arr.astype(dtype), 1)


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory, spatial_cfg):
    tmp = tmp_path_factory.mktemp("g3")
    aoi = build_aoi({"id": "t_syn", "context": "dense_urban", "lat": 21.028, "lon": 105.852,
                     "width_km": 1.5, "height_km": 1.5})
    units = H3Grid(resolution=int(spatial_cfg["spatial_unit"]["h3_resolution"])).units(aoi.polygon, aoi.metric_crs)
    w, s, e, n = aoi.polygon.buffer(0.04).bounds
    # WorldCover 10 m-ish (1/12000 deg): tree in the west half of the window,
    # cropland in the east, and a water body over the eastern ~35 % of the
    # AOI itself so the H3 cells include open-water cells (denominator_zero)
    # AND water-edge cells with partial land support.
    res = 1 / 12000
    wc = np.full((int((n - s) / res) + 1, int((e - w) / res) + 1), 40, dtype="uint8")
    wc[:, : wc.shape[1] // 2] = 10
    aw, _as, ae, _an = aoi.polygon.bounds
    water_from_col = int((ae - 0.35 * (ae - aw) - w) / res)
    water_to_col = int((ae + 0.1 * (ae - aw) - w) / res)
    wc[:, water_from_col:water_to_col] = 80
    _write_raster(tmp / "wc.tif", wc, from_origin(w, n, res, res), "EPSG:4326", 0, "uint8")
    # WorldPop 100 m-ish with a NoData band
    res_p = 1 / 1200
    wp = np.full((int((n - s) / res_p) + 1, int((e - w) / res_p) + 1), 7.5, dtype="float32")
    wp[:2, :] = -99999.0
    _write_raster(tmp / "wp.tif", wp, from_origin(w, n, res_p, res_p), "EPSG:4326", -99999.0, "float32")
    # GHSL 100 m in Mollweide
    from pyproj import Transformer
    tf = Transformer.from_crs("EPSG:4326", "ESRI:54009", always_xy=True)
    xs, ys = tf.transform([w, e], [s, n])
    x0, y1 = np.floor(min(xs) / 100) * 100 - 200, np.ceil(max(ys) / 100) * 100 + 200
    bu = np.full((int((y1 - np.floor(min(ys) / 100) * 100 + 200) / 100), int((np.ceil(max(xs) / 100) * 100 + 200 - x0) / 100)),
                 2500, dtype="uint16")
    _write_raster(tmp / "bu.tif", bu, from_origin(x0, y1, 100, 100), "ESRI:54009", 65535, "uint16")

    metric = aoi.metric_crs
    centre = gpd.GeoSeries([aoi.polygon], crs="EPSG:4326").to_crs(metric).iloc[0].centroid
    cx, cy = centre.x, centre.y
    pois = gpd.GeoDataFrame({
        "osm_type": ["node", "node", "way", "node"], "osm_id": [1, 2, 3, 4],
        "category": ["school", "hospital", "park_recreation", "transport_bus_stop"],
        "raw_tags": [{"amenity": "school"}, {"amenity": "hospital"}, {"leisure": "park"}, {"highway": "bus_stop"}],
    }, geometry=[Point(cx, cy), Point(cx + 400, cy), box(cx - 300, cy - 300, cx - 200, cy - 200), Point(cx, cy + 200)], crs=metric)
    roads = gpd.GeoDataFrame({"is_major": [True, False]},
                             geometry=[LineString([(cx - 3000, cy), (cx + 3000, cy)]), LineString([(cx, cy - 3000), (cx, cy + 3000)])], crs=metric)
    isec = gpd.GeoDataFrame({"degree": [4]}, geometry=[Point(cx, cy)], crs=metric)
    areas = gpd.GeoDataFrame({"osm_type": ["way"], "osm_id": [9], "area_category": ["industrial_site"]},
                             geometry=[box(cx + 100, cy + 100, cx + 300, cy + 300)], crs=metric)
    halo = gpd.GeoSeries([box(w, s, e, n)], crs="EPSG:4326").to_crs(metric).iloc[0]
    inputs = AoiInputs(aoi_id="t_syn", context="dense_urban", metric_crs=metric, units=units, halo_polygon_metric=halo,
                       poi_metric=pois, roads_metric=roads, intersections_metric=isec, area_metric=areas,
                       poi_duplicates_dropped=0, worldcover=R.open_band(tmp / "wc.tif"),
                       worldpop=R.open_band(tmp / "wp.tif"), builtup=R.open_band(tmp / "bu.tif"))
    return inputs


def test_synthetic_run_satisfies_the_contract_and_is_deterministic(synthetic, cfg, spatial_cfg, features_cfg, taxonomy):
    a = compute_aoi_features(synthetic, cfg, spatial_cfg, features_cfg, taxonomy, "r1", "m1", "t")
    b = compute_aoi_features(synthetic, cfg, spatial_cfg, features_cfg, taxonomy, "r1", "m1", "t")
    pd.testing.assert_frame_equal(a, b)
    report = validate_frame(a, features_cfg, spatial_cfg)
    assert report["passed"], report["problems"]
    assert list(a.columns[: len(contract_columns(features_cfg))]) == contract_columns(features_cfg)
    assert a["spatial_resolution"].eq(spatial_cfg["spatial_unit"]["h3_resolution"]).all()
    assert a["spatial_method"].eq("h3").all()
    assert a["spatial_decision_status"].eq("provisional_mvp").all()


def test_synthetic_features_have_the_expected_values(synthetic, cfg, spatial_cfg, features_cfg, taxonomy):
    df = compute_aoi_features(synthetic, cfg, spatial_cfg, features_cfg, taxonomy, "r1", "m1", "t")
    ok = df["land_cover_ratio_status"] == "ok"
    assert ok.all()
    # rollups partition the valid area (tree + cropland + water = 1 everywhere)
    s = df["tree_cover_ratio"] + df["cropland_ratio"] + df["water_wetland_ratio"]
    assert np.allclose(s, 1.0)
    # water cells lose land support; a fully-water cell has a zero denominator
    water = df[df["water_wetland_ratio"] > 0.999]
    if len(water):
        assert (water["population_density_status"] == "denominator_zero").all()
        assert water["population_density"].isna().all()
        assert water["population_count"].notna().all(), "the numerator is still reported"
    # 7.5 persons per pixel: a fully-covered cell holds 7.5 x (cell area /
    # pixel area), both measured in the raster CRS -- an independent
    # formula from the per-pixel apportioning the code performs.
    full = df[(df["population_nodata_area_fraction"] == 0) & (df["aoi_overlap_fraction"] > 0.999)]
    assert len(full)
    units_wp = synthetic.units.set_index("unit_id").to_crs(synthetic.worldpop.crs)
    t = synthetic.worldpop.transform
    expected = 7.5 * units_wp.loc[full["spatial_unit_id"]].area.to_numpy() / abs(t.a * t.e)
    assert np.allclose(full["population_count"].to_numpy(), expected, rtol=1e-9)
    # and the NoData band contributes nothing: cells touching it have lower counts than their area implies
    banded = df[df["population_nodata_area_fraction"] > 0]
    if len(banded):
        got = banded["population_count"].to_numpy()
        naive = 7.5 * units_wp.loc[banded["spatial_unit_id"]].area.to_numpy() / abs(t.a * t.e)
        assert (got < naive).all()
    # built-up 2500 m^2 per 10,000 m^2 pixel -> 0.25 of every cell is built. With the
    # numerator restricted to the land-support mask (uniform within a pixel) the
    # ratio is 0.25 in EVERY ok cell, water-edge cells included; the unmasked
    # ratio (0.25 / land fraction) is what the 0.2.0 run would have clipped.
    ok_bu = df[df["built_up_ratio_status"] == "ok"]
    assert len(ok_bu)
    assert np.allclose(ok_bu["built_up_ratio"], 0.25, rtol=1e-6)
    edge = ok_bu[ok_bu["valid_land_support_area_km2"] / ok_bu["spatial_unit_area_km2"] < 0.9]
    assert len(edge), "the synthetic AOI has water-edge cells"
    assert (edge["_built_up_ratio_unmasked"] > 0.27).all()
    assert (ok_bu["_built_up_ratio_unmasked"] >= ok_bu["built_up_ratio"] - 1e-12).all()
    # roads: the two 6 km lines cross the AOI; total clipped length over all cells equals the length inside the union
    units_m = synthetic.units.to_crs(synthetic.metric_crs)
    union = shapely.union_all(units_m.geometry.to_numpy())
    expected = sum(shapely.length(shapely.intersection(g, union)) for g in synthetic.roads_metric.geometry)
    assert df["road_length_km"].sum() * 1000 == pytest.approx(expected, rel=1e-9)
    assert df["major_road_length_km"].sum() <= df["road_length_km"].sum()
    # intersection: exactly one node, in exactly one cell
    assert (df["intersection_density_per_km2"] > 0).sum() == 1
    # urban centre / admin are null by contract with explicit statuses
    assert df["distance_nearest_urban_centre_km"].isna().all()
    assert df["distance_nearest_urban_centre_km_status"].eq("source_not_acquired").all()
    assert df["admin_province_code"].isna().all() and df["admin_commune_code"].isna().all()
    assert df["admin_province_match_status"].eq("source_not_acquired").all()
    assert df["admin_commune_match_status"].eq("blocked_no_qualified_geometry").all()
    assert df["admin_match_status"].str.contains("source_not_acquired").all()
    assert df["admin_match_status"].str.contains("blocked_no_qualified_geometry").all()


def test_zero_is_distinct_from_missing(synthetic, cfg, spatial_cfg, features_cfg, taxonomy):
    df = compute_aoi_features(synthetic, cfg, spatial_cfg, features_cfg, taxonomy, "r1", "m1", "t")
    # mapped zero: a count of 0 with status ok
    zeros = df[df["mall_count_3km"] == 0]
    assert len(zeros) == len(df) and (zeros["mall_count_3km_status"] == "ok").all()
    # missing: null with a non-ok status, never 0
    assert df["distance_nearest_urban_centre_km"].isna().all()
    assert not (df["distance_nearest_urban_centre_km"] == 0).any()
    # a feature whose source failed is null + source_unavailable, not zero
    broken = AoiInputs(**{**synthetic.__dict__, "osm_ingest_status": "ingest_failed"})
    d2 = compute_aoi_features(broken, cfg, spatial_cfg, features_cfg, taxonomy, "r1", "m1", "t")
    assert d2["road_length_km"].isna().all() and d2["road_features_status"].eq("source_unavailable").all()
    assert d2["road_density_km_per_km2"].isna().all() and d2["road_density_status"].eq("source_unavailable").all()
    assert validate_frame(d2, features_cfg, spatial_cfg)["passed"]


def test_industrial_ratio_over_water_is_masked_not_clipped(synthetic, cfg, spatial_cfg, features_cfg, taxonomy):
    """Cross-source overlap: an industrial polygon that covers the whole
    AOI, water included. The 0.2.0 code divided the full polygon area by
    the land-support denominator and clipped the >1 result to 1.0/ok. Now
    the numerator is the polygon area INSIDE the land-support mask, so the
    ratio is exactly 1 (not clipped to it), and the unmasked ratio 1/land
    fraction is kept for audit."""
    units_m = synthetic.units.to_crs(synthetic.metric_crs)
    everywhere = gpd.GeoDataFrame({"osm_type": ["way"], "osm_id": [77], "area_category": ["industrial_site"]},
                                  geometry=[shapely.union_all(units_m.geometry.to_numpy()).buffer(50)], crs=synthetic.metric_crs)
    flooded = AoiInputs(**{**synthetic.__dict__, "area_metric": everywhere})
    df = compute_aoi_features(flooded, cfg, spatial_cfg, features_cfg, taxonomy, "r1", "m1", "t")
    ok = df[df["osm_industrial_site_area_ratio_status"] == "ok"]
    assert len(ok)
    assert np.allclose(ok["osm_industrial_site_area_ratio"], 1.0, atol=1e-9)
    edge = ok[ok["valid_land_support_area_km2"] / ok["spatial_unit_area_km2"] < 0.9]
    assert len(edge)
    # the reviewer's case: raw polygon area / land support > 1 -- visible, not hidden
    expected_unmasked = edge["spatial_unit_area_km2"] / edge["valid_land_support_area_km2"]
    assert np.allclose(edge["_industrial_ratio_unmasked"], expected_unmasked, rtol=1e-6)
    assert (edge["_industrial_ratio_unmasked"] > 1.05).all()
    assert (edge["_industrial_area_m2_raw"] > edge["_industrial_area_m2_on_land_support"]).all()
    # water cells (no land support) stay denominator_zero, never 1.0
    assert (df.loc[df["valid_land_support_area_km2"] <= 0, "osm_industrial_site_area_ratio_status"] == "denominator_zero").all()
    assert validate_frame(df, features_cfg, spatial_cfg)["passed"]


def test_ratio_outside_unit_interval_fails_validation(synthetic, cfg, spatial_cfg, features_cfg, taxonomy):
    df = compute_aoi_features(synthetic, cfg, spatial_cfg, features_cfg, taxonomy, "r1", "m1", "t")
    i = df.index[df["osm_industrial_site_area_ratio_status"] == "ok"][0]
    bad = df.copy(); bad.loc[i, "osm_industrial_site_area_ratio"] = 1.0200160189      # the reviewed value
    rep = validate_frame(bad, features_cfg, spatial_cfg)
    assert not rep["passed"] and rep["checks"]["osm_industrial_site_area_ratio_in_unit_interval"] is False
    bad = df.copy(); bad.loc[i, "built_up_ratio"] = 1.02
    assert not validate_frame(bad, features_cfg, spatial_cfg)["passed"]
    bad = df.copy(); bad.loc[i, "tree_cover_ratio"] = -0.01
    assert not validate_frame(bad, features_cfg, spatial_cfg)["passed"]
    bad = df.copy(); bad.loc[i, "population_coverage_fraction"] = 1.5
    assert not validate_frame(bad, features_cfg, spatial_cfg)["passed"]
    # float noise inside the tolerance is not a violation
    noisy = df.copy(); noisy.loc[i, "built_up_ratio"] = 1 + 1e-12
    assert validate_frame(noisy, features_cfg, spatial_cfg)["passed"]
    # and the other invariants are hard checks too
    bad = df.copy(); bad.loc[i, "school_count_1km"] = 1.5
    assert not validate_frame(bad, features_cfg, spatial_cfg)["passed"]
    bad = df.copy(); bad.loc[i, "major_road_length_km"] = bad.loc[i, "road_length_km"] + 1
    assert not validate_frame(bad, features_cfg, spatial_cfg)["passed"]
    bad = df.copy(); bad.loc[i, "poi_category_richness_1km"] = bad.loc[i, "poi_total_count_1km"] + 1
    assert not validate_frame(bad, features_cfg, spatial_cfg)["passed"]
    bad = df.copy(); bad.loc[i, "distance_nearest_major_road_m"] = spatial_cfg["distance_search_caps_m"]["major_road"] + 1
    assert not validate_frame(bad, features_cfg, spatial_cfg)["passed"]
    bad = df.copy(); bad.loc[i, "distance_nearest_hospital_m"] = -1.0
    assert not validate_frame(bad, features_cfg, spatial_cfg)["passed"]
    bad = df.copy(); bad.loc[i, "spatial_unit_id"] = "not-an-h3-id"
    assert not validate_frame(bad, features_cfg, spatial_cfg)["passed"]
    bad = df.copy(); bad.loc[i, "feature_set_version"] = "0.2.0"
    assert not validate_frame(bad, features_cfg, spatial_cfg)["passed"]
    bad = df.copy(); bad.loc[i, "valid_land_support_area_km2"] = bad.loc[i, "spatial_unit_area_km2"] * 1.1
    assert not validate_frame(bad, features_cfg, spatial_cfg)["passed"]


def test_osm_source_failure_nulls_every_osm_derived_feature(synthetic, cfg, spatial_cfg, features_cfg, taxonomy):
    from features.schema import OSM_DERIVED
    broken = AoiInputs(**{**synthetic.__dict__, "osm_ingest_status": "ingest_failed"})
    df = compute_aoi_features(broken, cfg, spatial_cfg, features_cfg, taxonomy, "r1", "m1", "t")
    expected = {"road_length_km", "major_road_length_km", "road_density_km_per_km2", "intersection_density_per_km2",
                "distance_nearest_major_road_m", "osm_industrial_site_area_ratio",
                "distance_nearest_osm_industrial_site_m", "distance_nearest_park_m", "distance_nearest_hospital_m",
                "distance_nearest_higher_education_m", "distance_nearest_transport_hub_m",
                "distance_nearest_transit_stop_m", "transit_stop_count_1km", "school_count_1km",
                "higher_education_count_3km", "hospital_count_3km", "clinic_count_1km", "pharmacy_count_1km",
                "food_drink_count_1km", "retail_count_1km", "marketplace_count_1km", "mall_count_3km",
                "lodging_count_1km", "attraction_culture_count_3km", "park_recreation_count_1km",
                "poi_total_count_1km", "poi_category_richness_1km"}
    assert set(OSM_DERIVED) == expected
    for f in expected:
        assert df[f].isna().all(), f
        assert df[STATUS_COLUMN_OF[f]].eq("source_unavailable").all(), f
    assert not df["osm_query_complete"].astype(bool).any()
    assert df["osm_ingest_status"].eq("ingest_failed").all()
    # raster features are untouched by an OSM failure
    assert df["population_count"].notna().all() and df["tree_cover_ratio"].notna().all()
    rep = validate_frame(df, features_cfg, spatial_cfg)
    assert rep["passed"], rep["problems"]
    # the validator itself catches a stale value leaking through
    leak = df.copy(); leak.loc[leak.index[0], "school_count_1km"] = 0; leak.loc[leak.index[0], "school_count_1km_status"] = "ok"
    assert not validate_frame(leak, features_cfg, spatial_cfg)["passed"]
    leak = df.copy(); leak["osm_query_complete"] = True
    assert not validate_frame(leak, features_cfg, spatial_cfg)["passed"]


def test_entity_assembly_failure_nulls_affected_categories_only(synthetic, cfg, spatial_cfg, features_cfg, taxonomy):
    partial = AoiInputs(**{**synthetic.__dict__, "entity_assembly_failures": {"park_recreation": 1, "industrial_site": 1, "water_body": 3}})
    df = compute_aoi_features(partial, cfg, spatial_cfg, features_cfg, taxonomy, "r1", "m1", "t")
    affected = ["park_recreation_count_1km", "poi_total_count_1km", "poi_category_richness_1km", "distance_nearest_park_m",
                "osm_industrial_site_area_ratio", "distance_nearest_osm_industrial_site_m"]
    for f in affected:
        assert df[f].isna().all(), f
        assert df[STATUS_COLUMN_OF[f]].eq("entity_assembly_failed").all(), f
        assert not (df[f] == 0).any()
    for f in ["school_count_1km", "hospital_count_3km", "distance_nearest_hospital_m", "road_length_km", "transit_stop_count_1km"]:
        assert df[STATUS_COLUMN_OF[f]].eq("ok").all(), f
    assert df["osm_entity_assembly_failures"].eq("industrial_site:1;park_recreation:1;water_body:3").all()
    assert validate_frame(df, features_cfg, spatial_cfg)["passed"]
    clean = compute_aoi_features(synthetic, cfg, spatial_cfg, features_cfg, taxonomy, "r1", "m1", "t")
    assert clean["osm_entity_assembly_failures"].eq("none").all()
    assert (clean["park_recreation_count_1km"] >= 0).all() and clean["park_recreation_count_1km_status"].eq("ok").all()


def test_semantic_parameters_live_in_the_versioned_contract(cfg, features_cfg, taxonomy):
    sem = features_cfg["semantics"]
    assert features_cfg["feature_set_version"] == "0.3.0"
    assert sem["raster"]["worldcover"]["minimum_land_support_fraction"] == 0.01
    assert sem["raster"]["minimum_coverage_fraction"] == 0.999
    assert sem["raster"]["worldpop"]["nodata_means_zero_persons"] is True
    assert sem["raster"]["worldpop"]["evidence"]["release_statement_sha256"].startswith("1a23e31f")
    assert sem["ratios"]["numerator_policy"] == "within_valid_land_support_mask"
    assert sem["osm_entities"]["assembly_failure_status"] == "entity_assembly_failed"
    # the runner config no longer carries any of them
    assert "raster" not in cfg and "distance" not in cfg
    assert not any("nodata" in k or "land_support" in k for k in yaml.safe_load(open("config/gate3_mvp.yaml")))
    assert taxonomy["version"] == "0.3.0" and "LineString" in taxonomy["geometry_policy"]["accepted"]
    # the superseded run keeps its own version and bytes
    old = Path("data/gate3/run_20260914T160806Z")
    if old.exists():
        from spatial.run_gate2_mvp import verify_checksums
        assert json.loads((old / "run_manifest.json").read_text())["feature_set_version"] == "0.2.0"
        assert verify_checksums(old) == []


def test_worldpop_publisher_nodata_is_zero_persons_but_window_gaps_are_missing(cfg, spatial_cfg, features_cfg):
    """The exact R2025A policy: a unit entirely under publisher NoData
    (constrained settlement mask / mastergrid water) INSIDE the raster
    window is 0 persons with status ok and nodata fraction 1; a unit that
    reaches outside the raster window is coverage_incomplete."""
    from features.compute import raster_block
    from features import raster as R
    t = from_origin(0, 1000, 100, 100)
    wp = np.full((10, 10), -99999.0, dtype="float32"); wp[5:, :] = 3.0
    wc = np.full((100, 100), 40, dtype="uint8")
    bu = np.zeros((10, 10), dtype="uint16")
    crs = "EPSG:32648"
    units = gpd.GeoDataFrame({"unit_id": ["all_nodata", "half", "outside"], "area_m2": [4e4, 4e4, 4e4],
                              "aoi_overlap_fraction": [1, 1, 1], "rep_lat": [0, 0, 0], "rep_lon": [0, 0, 0]},
                             geometry=[box(100, 800, 300, 1000), box(100, 400, 300, 600), box(900, 100, 1100, 300)], crs=crs)
    inputs = AoiInputs(aoi_id="t", context="c", metric_crs=crs, units=units, halo_polygon_metric=box(0, 0, 1000, 1000),
                       poi_metric=None, roads_metric=None, intersections_metric=None, area_metric=None, poi_duplicates_dropped=0,
                       worldcover=R.RasterBand(None, wc, from_origin(0, 1000, 10, 10), crs, 0),
                       worldpop=R.RasterBand(None, wp, t, crs, -99999.0),
                       builtup=R.RasterBand(None, bu, t, crs, 65535))
    out = raster_block(inputs, features_cfg["semantics"])
    assert out.loc[0, "population_count"] == 0 and out.loc[0, "population_count_status"] == "ok"
    assert out.loc[0, "population_nodata_area_fraction"] == pytest.approx(1.0)
    assert out.loc[0, "population_coverage_fraction"] == pytest.approx(1.0)
    assert out.loc[1, "population_count"] == pytest.approx(3.0 * 2) and out.loc[1, "population_nodata_area_fraction"] == pytest.approx(0.5)
    assert np.isnan(out.loc[2, "population_count"]) and out.loc[2, "population_count_status"] == "coverage_incomplete"
    assert out.loc[2, "population_coverage_fraction"] == pytest.approx(0.5)
    # and the alternative policy would make the all-NoData unit missing, proving the switch is live
    alt = {**features_cfg["semantics"], "raster": {**features_cfg["semantics"]["raster"],
           "worldpop": {**features_cfg["semantics"]["raster"]["worldpop"], "nodata_means_zero_persons": False}}}
    out2 = raster_block(inputs, alt)
    assert out2.loc[0, "population_count_status"] == "coverage_incomplete" and np.isnan(out2.loc[0, "population_count"])


def test_latest_full_run_skips_newer_smoke_directories(tmp_path):
    from features.run_gate3_mvp import latest_full_run
    root = tmp_path / "gate3"
    for name, kind in (("run_20260101T000000Z", "atomic_feature_mvp"), ("run_20260102T000000Z", "smoke")):
        d = root / name; d.mkdir(parents=True)
        (d / "SHA256SUMS").write_text("")
        (d / "run_manifest.json").write_text(json.dumps({"gate": 3, "run_kind": kind}))
    (root / "run_20260103T000000Z").mkdir()            # incomplete: no checksums
    assert latest_full_run(root).name == "run_20260101T000000Z"
    assert latest_full_run(tmp_path / "missing") is None


def test_validate_frame_rejects_bare_nulls_and_values_with_failure_status(synthetic, cfg, spatial_cfg, features_cfg, taxonomy):
    df = compute_aoi_features(synthetic, cfg, spatial_cfg, features_cfg, taxonomy, "r1", "m1", "t")
    bad = df.copy(); bad.loc[bad.index[0], "population_count"] = np.nan
    assert not validate_frame(bad, features_cfg)["passed"]
    bad = df.copy(); bad.loc[bad.index[0], "distance_nearest_urban_centre_km"] = 12.0
    assert not validate_frame(bad, features_cfg)["passed"]
    bad = df.drop(columns=["poi_total_count_1km"])
    assert "poi_total_count_1km" in validate_frame(bad, features_cfg)["missing_columns"]
    assert set(STATUS_COLUMN_OF) == set(features_cfg["mvp_features"])


def test_h3_units_are_deterministic_and_the_resolution_comes_from_config(spatial_cfg):
    import h3
    aoi = build_aoi({"id": "t", "context": "c", "lat": 21.028, "lon": 105.852, "width_km": 1, "height_km": 1})
    res = int(spatial_cfg["spatial_unit"]["h3_resolution"])
    a = H3Grid(resolution=res).units(aoi.polygon, aoi.metric_crs)
    b = H3Grid(resolution=res).units(aoi.polygon, aoi.metric_crs)
    assert a["unit_id"].tolist() == b["unit_id"].tolist()
    assert all(h3.get_resolution(u) == res for u in a["unit_id"])
    # actual area, not the nominal global average
    assert not np.allclose(a["area_m2"] / 1e6, h3.average_hexagon_area(res, unit="km^2"))
    assert np.allclose(a["area_m2"], a.to_crs(aoi.metric_crs).area)


# --- provenance ------------------------------------------------------------------

def test_source_checksum_mismatch_is_an_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ("osm.osm.pbf", "worldpop2025.tif", "worldcover.tif", "ghs_built_s.tif"):
        (tmp_path / name).write_bytes(name.encode())
    from spatial.benchmark import sha256_of
    good = {k: sha256_of(tmp_path / n) for k, n in (("roads_poi", "osm.osm.pbf"), ("population", "worldpop2025.tif"),
                                                       ("land_cover", "worldcover.tif"), ("built_up", "ghs_built_s.tif"))}
    aoi_entry = {k: {"source_id": f"s_{k}", "path": n, "sha256": good[k]} for k, n in
                 (("roads_poi", "osm.osm.pbf"), ("population", "worldpop2025.tif"),
                  ("land_cover", "worldcover.tif"), ("built_up", "ghs_built_s.tif"))}
    index = {"aois": {"a": {**aoi_entry, "acquisition_run_id": "r", "manifest_path": "m"}}}
    entries = {f"s_{k}": {"sha256": good[k], "release": "x", "license_id": "L"} for k in good}
    rows = verify_aoi_sources("a", index, entries)
    assert len(rows) == 4 and all(r["checksum_verified"] for r in rows)
    (tmp_path / "worldcover.tif").write_bytes(b"tampered")
    with pytest.raises(ProvenanceError, match="sha256"):
        verify_aoi_sources("a", index, entries)
    entries["s_population"]["sha256"] = "0" * 64
    (tmp_path / "worldcover.tif").write_bytes(b"worldcover.tif")
    with pytest.raises(ProvenanceError, match="manifest sha256"):
        verify_aoi_sources("a", index, entries)


# --- the real four-AOI run -----------------------------------------------------------

def _latest_run():
    from features.run_gate3_mvp import latest_full_run
    return latest_full_run(GATE3_ROOT)


requires_run = pytest.mark.skipif(_latest_run() is None, reason="no Gate 3 run present")


@requires_run
def test_real_run_is_complete_and_checksums_verify(features_cfg, spatial_cfg):
    from spatial.run_gate2_mvp import verify_checksums
    from features.run_gate3_mvp import REQUIRED_OUTPUTS
    run = _latest_run()
    for rel in REQUIRED_OUTPUTS + ["SHA256SUMS", "benchmark_runs.parquet"]:
        assert (run / rel).exists(), rel
    assert verify_checksums(run) == []
    manifest = json.loads((run / "run_manifest.json").read_text())
    validation = json.loads((run / "validation_summary.json").read_text())
    assert manifest["gate"] == 3 and manifest["run_kind"] == "atomic_feature_mvp"
    assert validation["full_mvp_run"] and validation["passed"]
    assert set(validation["aois_computed"]) == {"hanoi_core", "hoi_an", "mu_cang_chai", "dong_thap_rural"}
    df = pd.read_parquet(run / "atomic_features.parquet")
    rep = validate_frame(df, features_cfg, spatial_cfg)
    assert rep["passed"], rep["problems"]
    # 0.3.0 lineage: version and semantics pinned identically in rows, manifests and config
    assert manifest["feature_set_version"] == features_cfg["feature_set_version"] == "0.3.0"
    # JSON turns the integer legend keys into strings; compare the JSON forms.
    sem_json = json.loads(json.dumps(features_cfg["semantics"], sort_keys=True))
    assert manifest["feature_semantics"] == sem_json
    assert df["feature_set_version"].eq("0.3.0").all() and df["poi_taxonomy_version"].eq("0.3.0").all()
    fm = json.loads((run / "feature_manifest.json").read_text())
    assert fm["feature_set_version"] == "0.3.0" and fm["feature_semantics"] == sem_json
    assert "config/features.yaml" in manifest["config_sha256"]
    # entity assembly is reported per AOI and every failure has an explicit status, never a zero
    for aoi in validation["aois_computed"]:
        asm = validation["entity_assembly"][aoi]
        assert {"relations", "closed_ways", "failed_entities", "failures_by_category"} <= set(asm)
        sub = df[df["aoi_id"] == aoi]
        failed_cats = set(asm["failures_by_category"])
        if "park_recreation" in failed_cats:
            assert sub["park_recreation_count_1km_status"].eq("entity_assembly_failed").all()
            assert sub["poi_total_count_1km"].isna().all()
        if "industrial_site" in failed_cats:
            assert sub["osm_industrial_site_area_ratio_status"].eq("entity_assembly_failed").all()
    # published ratios are in range; the unmasked audit is present
    for c in ("built_up_ratio", "osm_industrial_site_area_ratio"):
        v = df[c].dropna()
        assert ((v >= 0) & (v <= 1)).all()
    assert "ratio_audit" in validation and "cells" in validation["ratio_audit"]
    assert len(df) == validation["rows"] == sum(v["cells"] for v in validation["per_aoi"].values())
    units = gpd.read_parquet(run / "spatial_units.parquet")
    assert set(units["spatial_unit_id"]) == set(df["spatial_unit_id"])
    assert units.crs.to_string() == "EPSG:4326"
    for aoi, c in validation["conservation"].items():
        assert c["population"]["passed"] and c["built_up_m2"]["passed"], aoi
    assert not any(str(v).startswith("/") for s in manifest["sources"] for v in s.values()), "no absolute paths"
    cov = pd.read_parquet(run / "source_coverage.parquet")
    assert cov["checksum_verified"].all() and len(cov) == 16
    assert not cov["path"].str.startswith("/").any()


@requires_run
def test_real_run_contains_no_customer_or_gate2_anchor_columns():
    df = pd.read_parquet(_latest_run() / "atomic_features.parquet")
    forbidden = ("customer", "trip", "pickup", "dropoff", "od_flow", "segment", "poi_count_1km",
                 "population_1km", "road_length_1km", "percentile", "log1p", "_score")
    assert not [c for c in df.columns if any(f in c for f in forbidden)]
