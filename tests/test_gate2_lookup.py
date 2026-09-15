"""Deterministic lat/lon lookup: boundary ties, coastal/edge behaviour,
origin-shift and jitter arithmetic, and rerun reproducibility.

These are the properties `docs/spatial_unit_decision.md` requires a spatial
unit to have before it can be a storage/index key at all, so they are
tested directly rather than inferred from the benchmark table.
"""

import numpy as np
import pytest
from shapely.geometry import Point

from spatial.aoi import build_aoi
from spatial.candidates import H3Grid, SquareGrid, origin_shift_replicates

COASTAL = {"id": "t_coast", "context": "tourism", "lat": 15.880, "lon": 108.330,
           "width_km": 4, "height_km": 4}
INLAND = {"id": "t_inland", "context": "dense_urban", "lat": 21.028, "lon": 105.852,
          "width_km": 2, "height_km": 2}

CANDIDATES = [SquareGrid(size_m=500), SquareGrid(size_m=125), H3Grid(resolution=9), H3Grid(resolution=10)]


@pytest.mark.parametrize("candidate", CANDIDATES, ids=lambda c: c.id)
def test_lookup_returns_exactly_one_unit_per_query(candidate):
    lat = np.array([21.028, 15.880, 10.776])
    lon = np.array([105.852, 108.330, 106.700])
    out = candidate.lookup(lat, lon)
    assert len(out) == 3
    assert all(isinstance(v, str) and v for v in out)


@pytest.mark.parametrize("candidate", CANDIDATES, ids=lambda c: c.id)
def test_lookup_is_deterministic_across_repeats_and_call_shapes(candidate):
    lat = np.array([21.028, 15.880])
    lon = np.array([105.852, 108.330])
    batch = list(candidate.lookup(lat, lon))
    singles = [candidate.lookup(lat[i:i + 1], lon[i:i + 1])[0] for i in range(2)]
    assert batch == singles
    assert batch == list(candidate.lookup(lat, lon))


def test_square_lookup_agrees_with_generated_cell_geometry():
    """The unit a coordinate is looked up into must be the unit whose own
    polygon contains that coordinate -- lookup and generation cannot drift."""
    aoi = build_aoi(INLAND)
    grid = SquareGrid(size_m=500)
    units = grid.units(aoi.polygon, aoi.metric_crs).to_crs(aoi.metric_crs)
    geom_by_id = dict(zip(units["unit_id"], units.geometry))

    rng = np.random.default_rng(5)
    minx, miny, maxx, maxy = aoi.polygon.bounds
    lon = rng.uniform(minx, maxx, 200)
    lat = rng.uniform(miny, maxy, 200)
    assigned = grid.lookup(lat, lon)

    from pyproj import Transformer
    x, y = Transformer.from_crs("EPSG:4326", aoi.metric_crs, always_xy=True).transform(lon, lat)
    checked = 0
    for uid, px, py in zip(assigned, x, y):
        if uid not in geom_by_id:
            continue
        checked += 1
        assert geom_by_id[uid].buffer(0.01).covers(Point(px, py))
    assert checked > 100


def test_square_boundary_point_resolves_to_the_upper_cell():
    """The documented tie rule: cells are [x0, x0+s) x [y0, y0+s), so a
    coordinate exactly on a shared edge belongs to the cell above/right of
    it, deterministically."""
    grid = SquareGrid(size_m=1000)
    exact = grid.cell_index(np.array([5000.0]), np.array([5000.0]))
    just_below = grid.cell_index(np.array([4999.999]), np.array([4999.999]))
    assert (exact[0][0], exact[1][0]) == (5, 5)
    assert (just_below[0][0], just_below[1][0]) == (4, 4)


def test_coastal_lookup_still_returns_a_unit_over_water():
    """A coastal AOI contains sea. The index must still resolve every
    coordinate: a unit key is a partition of space, not of land, and the
    land question is answered by the land_fraction column instead."""
    aoi = build_aoi(COASTAL)
    minx, miny, maxx, maxy = aoi.polygon.bounds
    lat = np.array([miny, maxy, (miny + maxy) / 2])
    lon = np.array([minx, maxx, (minx + maxx) / 2])
    for candidate in CANDIDATES:
        out = candidate.lookup(lat, lon)
        assert all(isinstance(v, str) and v for v in out), candidate.id


def test_coastal_units_report_partial_land_rather_than_being_dropped():
    aoi = build_aoi(COASTAL)
    units = H3Grid(resolution=9).units(aoi.polygon, aoi.metric_crs)
    assert len(units)
    # Every generated unit overlaps the AOI; overlap fraction is recorded so
    # an edge-clipped unit is visible rather than silently full-weight.
    assert (units["aoi_overlap_fraction"] > 0).all()
    assert (units["aoi_overlap_fraction"] <= 1.0 + 1e-9).all()
    assert (units["aoi_overlap_fraction"] < 0.999).any(), "edge units must be partially covered"


# --- origin shift and jitter ---------------------------------------------

def test_origin_shift_renames_every_cell_which_is_why_ids_are_not_the_metric():
    """A half-cell shift changes every cell ID by construction. This pins
    that fact, which is exactly why the reported sensitivity metric is the
    co-partition flip rate and not an ID-equality rate."""
    base = SquareGrid(size_m=500)
    shifted = origin_shift_replicates(base, [[0.5, 0.5]])[0]
    lat = np.array([21.028, 21.029, 21.030])
    lon = np.array([105.852, 105.853, 105.854])
    assert not any(a == b for a, b in zip(base.lookup(lat, lon), shifted.lookup(lat, lon)))


def test_origin_shift_mostly_preserves_which_points_share_a_cell():
    """The meaningful stability question: do points that shared a cell still
    share one? For a half-cell shift most pairs must survive, or the grid is
    not a stable partition of space at all."""
    base = SquareGrid(size_m=1000)
    shifted = origin_shift_replicates(base, [[0.5, 0.5]])[0]
    rng = np.random.default_rng(9)
    lat = 21.028 + rng.normal(0, 0.01, 400)
    lon = 105.852 + rng.normal(0, 0.01, 400)

    b = np.asarray(base.lookup(lat, lon), dtype=object)
    s = np.asarray(shifted.lookup(lat, lon), dtype=object)
    ia = rng.integers(0, 400, 4000)
    ib = rng.integers(0, 400, 4000)
    keep = ia != ib
    flip = np.mean((b[ia[keep]] == b[ib[keep]]) != (s[ia[keep]] == s[ib[keep]]))
    assert 0.0 <= flip < 0.25


def test_jitter_below_a_cell_width_changes_few_assignments():
    grid = SquareGrid(size_m=1000)
    rng = np.random.default_rng(13)
    lat = 21.028 + rng.uniform(-0.02, 0.02, 500)
    lon = 105.852 + rng.uniform(-0.02, 0.02, 500)
    # ~100 m of jitter against a 1 km cell: roughly a tenth of points should
    # cross a boundary, and certainly not most of them.
    dlat = 100.0 / 111_320.0
    moved = np.mean(np.asarray(grid.lookup(lat, lon), dtype=object)
                    != np.asarray(grid.lookup(lat + dlat, lon), dtype=object))
    assert 0.0 < moved < 0.30


def test_h3_has_no_origin_to_shift():
    """H3 exposes no origin parameter, so the origin-shift replicate cannot
    be constructed for it at all -- which is why the metric is recorded as
    not_applicable rather than as a pass."""
    assert not hasattr(H3Grid(resolution=9), "offset_fraction")
    assert not hasattr(H3Grid(resolution=9), "origin_x")
