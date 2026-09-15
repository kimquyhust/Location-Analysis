"""AOI construction, metric-CRS selection, checksums, and halo derivation.

The AOI definitions are the fixed frame the whole experiment is measured
in. A silently moved centre or resized window would invalidate every
comparison across runs, so the checksum that would catch it is tested here.
"""

import json
import math
from pathlib import Path

import pytest
import yaml
from shapely.geometry import shape

from spatial.aoi import (Aoi, aoi_checksum, build_aoi, load_aois, utm_epsg_from_longitude,
                         write_aoi_geojson)

SPEC = {"id": "t", "context": "dense_urban", "lat": 21.028, "lon": 105.852,
        "width_km": 6, "height_km": 6}


def test_utm_zone_selection_covers_both_vietnam_zones():
    assert utm_epsg_from_longitude(105.852) == "EPSG:32648"
    assert utm_epsg_from_longitude(108.330) == "EPSG:32649"
    assert utm_epsg_from_longitude(103.960) == "EPSG:32648"


def test_aoi_dimensions_are_exact_on_the_ground():
    import geopandas as gpd

    aoi = build_aoi(SPEC)
    metric = gpd.GeoSeries([aoi.polygon], crs="EPSG:4326").to_crs(aoi.metric_crs).iloc[0]
    minx, miny, maxx, maxy = metric.bounds
    assert (maxx - minx) == pytest.approx(6000.0, abs=1.0)
    assert (maxy - miny) == pytest.approx(6000.0, abs=1.0)
    assert metric.area == pytest.approx(36_000_000.0, rel=1e-4)


def test_aoi_is_centred_on_the_configured_coordinate():
    aoi = build_aoi(SPEC)
    w, s, e, n = aoi.bounds
    assert (s + n) / 2 == pytest.approx(SPEC["lat"], abs=1e-4)
    assert (w + e) / 2 == pytest.approx(SPEC["lon"], abs=1e-4)


def test_all_eight_configured_aois_build():
    aois = load_aois()
    assert len(aois) == 8
    assert {a.id for a in aois} == {
        "hanoi_core", "hcmc_core", "thu_duc_east", "dong_thap_rural",
        "mu_cang_chai", "binh_duong_industrial", "hoi_an", "phu_quoc_coast"}
    assert {a.context for a in aois} >= {
        "dense_urban", "suburban", "rural_delta", "rural_mountain", "industrial", "tourism"}


def test_aoi_checksum_is_stable_across_rebuilds():
    assert aoi_checksum(build_aoi(SPEC)) == aoi_checksum(build_aoi(SPEC))


@pytest.mark.parametrize("field,delta", [("lat", 0.001), ("lon", 0.001), ("width_km", 1)])
def test_aoi_checksum_changes_if_a_centre_or_dimension_moves(field, delta):
    """A silently altered AOI is the failure mode this checksum exists to
    catch."""
    moved = dict(SPEC, **{field: SPEC[field] + delta})
    assert aoi_checksum(build_aoi(SPEC)) != aoi_checksum(build_aoi(moved))


def test_aoi_geojson_round_trips_with_its_checksum(tmp_path):
    aois = load_aois()
    path, sha = write_aoi_geojson(aois, tmp_path / "aois.geojson")
    fc = json.loads(path.read_text())
    assert len(fc["features"]) == len(aois)
    assert len(sha) == 64
    for feature, aoi in zip(fc["features"], aois):
        assert feature["properties"]["aoi_checksum"] == aoi_checksum(aoi)
        assert feature["properties"]["storage_crs"] == "EPSG:4326"
        assert shape(feature["geometry"]).is_valid


def test_aoi_geojson_is_byte_identical_on_rewrite(tmp_path):
    aois = load_aois()
    _, a = write_aoi_geojson(aois, tmp_path / "a.geojson")
    _, b = write_aoi_geojson(aois, tmp_path / "b.geojson")
    assert a == b


def test_halo_bbox_extends_far_enough_for_the_widest_buffer():
    """1 km and 3 km buffer metrics read outside the AOI. Without a halo
    they would be truncated at the edge and read as real sparsity."""
    from ingestion.acquire_gate2 import HALO_KM, halo_bbox

    config = yaml.safe_load(open("config/gate2.yaml"))
    assert HALO_KM * 1000 >= config["buffers_m"]["regional"]

    aoi = build_aoi(SPEC)
    hw, hs, he, hn = halo_bbox(aoi)
    w, s, e, n = aoi.bounds
    assert hw < w and hs < s and he > e and hn > n
    # Roughly HALO_KM of latitude on each side (about 0.0315 deg per 3.5 km).
    assert (s - hs) == pytest.approx(HALO_KM / 111.32, abs=0.005)


def test_worldcover_and_ghsl_tile_ids_are_computed_not_hardcoded():
    from ingestion.acquire_gate2 import ghsl_tile_id, required_tiles, worldcover_tile_id

    assert worldcover_tile_id(21.028, 105.852) == "N21E105"
    assert worldcover_tile_id(15.880, 108.330) == "N15E108"
    assert worldcover_tile_id(20.9689, 105.852) == "N18E105"  # a halo edge crossing a tile line

    row, col = ghsl_tile_id(105.852, 21.028)
    assert isinstance(row, int) and isinstance(col, int) and row > 0 and col > 0

    wc, gh = required_tiles(load_aois())
    assert len(wc) >= 5 and len(gh) >= 2
    assert all(t.startswith("N") for t in wc)
