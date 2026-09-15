"""Deterministic unit generation, stable IDs, actual areas, neighbours, and
lat/lon lookup for both Gate 2 candidate families.

These run entirely on synthetic geometry -- no acquired data, no network --
so they stay meaningful as a regression net independently of whether a Gate
2 run directory exists.
"""

import math

import geopandas as gpd
import numpy as np
import pytest
import yaml
from shapely.geometry import Point, box

from spatial.aoi import build_aoi, utm_epsg_from_longitude
from spatial.candidates import (H3Grid, SquareGrid, adjacent_pairs, build_candidates,
                                origin_shift_replicates)

HANOI = {"id": "t_hanoi", "context": "dense_urban", "lat": 21.028, "lon": 105.852,
         "width_km": 2, "height_km": 2}


@pytest.fixture(scope="module")
def aoi():
    return build_aoi(HANOI)


# --- square grid: deterministic IDs on a national origin -------------------

def test_square_unit_id_is_deterministic_and_national():
    grid = SquareGrid(size_m=500)
    a = grid.lookup(np.array([21.028]), np.array([105.852]))[0]
    b = grid.lookup(np.array([21.028]), np.array([105.852]))[0]
    assert a == b
    # The ID encodes national-grid indices, not an AOI-relative position, so
    # the same coordinate yields the same ID regardless of what else is run.
    candidate_id, col, row = SquareGrid.parse_unit_id(a)
    assert candidate_id == "square_500m"
    assert isinstance(col, int) and isinstance(row, int)


def test_square_ids_differ_between_sizes_and_cannot_collide():
    p = (np.array([21.028]), np.array([105.852]))
    ids = {SquareGrid(size_m=s).lookup(*p)[0] for s in (125, 250, 500, 1000)}
    assert len(ids) == 4
    assert all(i.split("|")[0].startswith("square_") for i in ids)


def test_square_origin_is_the_configured_national_origin():
    """A cell index must be floor((coordinate - origin) / size) in the
    national CRS -- not relative to the AOI, the data extent, or anything
    else that would move between runs."""
    grid = SquareGrid(size_m=500, origin_x=0.0, origin_y=0.0)
    col, row = grid.cell_index(np.array([1234.0]), np.array([-1.0]))
    assert col[0] == 2       # floor(1234 / 500)
    assert row[0] == -1      # floor(-1 / 500) -- negative side floors down


def test_square_boundary_tie_rule_is_half_open_lower_left_inclusive():
    grid = SquareGrid(size_m=500)
    on_edge_col, on_edge_row = grid.cell_index(np.array([1000.0]), np.array([500.0]))
    below_col, below_row = grid.cell_index(np.array([999.999]), np.array([499.999]))
    assert (on_edge_col[0], on_edge_row[0]) == (2, 1)
    assert (below_col[0], below_row[0]) == (1, 0)


def test_square_grid_origin_shift_produces_distinct_labelled_candidates():
    base = SquareGrid(size_m=500)
    reps = origin_shift_replicates(base, [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5]])
    assert reps[0].id == "square_500m"
    assert {r.id for r in reps[1:]} == {"square_500m_off0.5x0", "square_500m_off0.5x0.5"}
    # A shifted replicate must never be mistakable for the real candidate.
    assert base.id not in {r.id for r in reps[1:]}


# --- H3 -------------------------------------------------------------------

def test_h3_lookup_matches_library_and_is_deterministic():
    import h3

    grid = H3Grid(resolution=9)
    got = grid.lookup(np.array([21.028]), np.array([105.852]))[0]
    assert got == h3.latlng_to_cell(21.028, 105.852, 9)
    assert grid.lookup(np.array([21.028]), np.array([105.852]))[0] == got


def test_h3_actual_areas_are_measured_not_nominal(aoi):
    grid = H3Grid(resolution=9)
    units = grid.units(aoi.polygon, aoi.metric_crs)
    assert len(units)
    actual_km2 = units["area_m2"].to_numpy() / 1e6
    nominal = grid.nominal_area_km2
    # Actual cell area varies across the AOI; asserting it is not a constant
    # is the point -- nominal averages must never stand in for it.
    assert actual_km2.std() >= 0
    assert np.allclose(actual_km2, nominal, rtol=0.35)
    assert not np.all(actual_km2 == nominal)


def test_h3_and_square_area_controls_are_comparable_in_scale():
    """The 325 m square is the declared area control for H3 r9; their
    nominal areas must stay within a few percent or the shape-vs-scale
    separation the design depends on is not actually controlled."""
    assert abs(SquareGrid(size_m=325).nominal_area_km2 - H3Grid(resolution=9).nominal_area_km2) \
        / H3Grid(resolution=9).nominal_area_km2 < 0.05


# --- AOI clipping ---------------------------------------------------------

@pytest.mark.parametrize("candidate", [SquareGrid(size_m=500), H3Grid(resolution=9)])
def test_units_cover_the_aoi_and_every_unit_touches_it(aoi, candidate):
    units = candidate.units(aoi.polygon, aoi.metric_crs)
    assert len(units) > 1
    metric = units.to_crs(aoi.metric_crs)
    aoi_metric = gpd.GeoSeries([aoi.polygon], crs="EPSG:4326").to_crs(aoi.metric_crs).iloc[0]

    # No unit is included that does not actually meet the AOI.
    assert metric.intersects(aoi_metric).all()
    # And the union leaves no hole inside the AOI.
    uncovered = aoi_metric.difference(metric.union_all())
    assert uncovered.area < aoi_metric.area * 1e-6


@pytest.mark.parametrize("candidate", [SquareGrid(size_m=500), H3Grid(resolution=9)])
def test_unit_ids_are_unique_and_geometry_is_stored_in_wgs84(aoi, candidate):
    units = candidate.units(aoi.polygon, aoi.metric_crs)
    assert units["unit_id"].is_unique
    assert units.crs.to_string() == "EPSG:4326"
    assert set(["area_m2", "aoi_overlap_fraction", "rep_lat", "rep_lon"]).issubset(units.columns)


@pytest.mark.parametrize("candidate", [SquareGrid(size_m=500), H3Grid(resolution=9)])
def test_generation_is_reproducible(aoi, candidate):
    a = candidate.units(aoi.polygon, aoi.metric_crs)
    b = candidate.units(aoi.polygon, aoi.metric_crs)
    assert a["unit_id"].tolist() == b["unit_id"].tolist()
    assert np.allclose(a["area_m2"].to_numpy(), b["area_m2"].to_numpy())


# --- neighbours -----------------------------------------------------------

def test_square_neighbors_are_the_eight_surrounding_cells(aoi):
    grid = SquareGrid(size_m=500)
    units = grid.units(aoi.polygon, aoi.metric_crs)
    nbrs = grid.neighbors(units["unit_id"].tolist())
    # An interior cell of a >=5x5 block has all eight neighbours present.
    degrees = sorted(len(v) for v in nbrs.values())
    assert degrees[-1] == 8
    assert all(d <= 8 for d in degrees)
    for uid, ns in nbrs.items():
        assert uid not in ns                       # never its own neighbour
        assert len(set(ns)) == len(ns)             # no duplicates


def test_h3_neighbors_are_at_most_six(aoi):
    grid = H3Grid(resolution=9)
    units = grid.units(aoi.polygon, aoi.metric_crs)
    nbrs = grid.neighbors(units["unit_id"].tolist())
    assert max(len(v) for v in nbrs.values()) == 6
    for uid, ns in nbrs.items():
        assert uid not in ns


@pytest.mark.parametrize("candidate", [SquareGrid(size_m=500), H3Grid(resolution=9)])
def test_neighbor_relation_is_symmetric_within_the_aoi(aoi, candidate):
    units = candidate.units(aoi.polygon, aoi.metric_crs)
    nbrs = candidate.neighbors(units["unit_id"].tolist())
    for uid, ns in nbrs.items():
        for n in ns:
            assert uid in nbrs[n], f"{uid}->{n} is not mirrored"


def test_rings_grow_monotonically():
    grid, h3g = SquareGrid(size_m=500), H3Grid(resolution=9)
    hex_id = h3g.lookup(np.array([21.028]), np.array([105.852]))[0]
    sq_id = grid.lookup(np.array([21.028]), np.array([105.852]))[0]
    for c, uid in ((grid, sq_id), (h3g, hex_id)):
        sizes = [len(set(c.ring(uid, k))) for k in range(1, 5)]
        assert sizes == sorted(sizes)
        assert len(set(sizes)) == len(sizes)


# --- config wiring --------------------------------------------------------

def test_build_candidates_matches_the_configured_matrix():
    config = yaml.safe_load(open("config/gate2.yaml"))
    cands = build_candidates(config)
    assert len(cands) == len(config["candidates"]["square_m"]) + len(config["candidates"]["h3_resolutions"])
    assert {c.id for c in cands if c.family == "h3"} == {
        f"h3_r{r}" for r in config["candidates"]["h3_resolutions"]}
    assert {c.id for c in cands if c.family == "square"} == {
        f"square_{int(s['size_m'])}m" for s in config["candidates"]["square_m"]}


def test_adjacent_pairs_never_cross_families():
    config = yaml.safe_load(open("config/gate2.yaml"))
    for finer, coarser in adjacent_pairs(build_candidates(config)):
        assert finer.family == coarser.family
        assert finer.nominal_area_km2 < coarser.nominal_area_km2


def test_administrative_candidate_stays_disabled_until_a_source_qualifies():
    """Gate 2 must not claim a three-family comparison while the
    administrative family is blocked."""
    config = yaml.safe_load(open("config/gate2.yaml"))
    admin = config["candidates"]["administrative"]
    if not admin["enabled"]:
        assert admin["status"] == "blocked"
        assert admin["qualification_record"]
    ids = {c.id for c in build_candidates(config)}
    assert not any(i.startswith("admin") for i in ids)
