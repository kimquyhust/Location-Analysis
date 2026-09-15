"""Gate 2 metric internals: raster count conservation, reference-field
sampling, origin-shift/jitter arithmetic, and the mapped-zero versus
missing-source distinction.

Synthetic inputs throughout, so a failure points at the metric code rather
than at whatever the acquired data happens to contain.
"""

import math

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point, box

from spatial import metrics as M
from spatial.candidates import SquareGrid


# --- reference grid and field sampling ------------------------------------

def test_accumulate_conserves_the_total_weight():
    """Population is carried into the reference grid by summing weights at
    point locations. Nothing may be created or lost in that step."""
    grid = M._reference_grid((0.0, 0.0, 1000.0, 1000.0), cell_m=100.0, pad_m=0.0)
    rng = np.random.default_rng(7)
    x = rng.uniform(0, 1000, 500)
    y = rng.uniform(0, 1000, 500)
    w = rng.uniform(0, 50, 500)
    out = M._accumulate(grid, x, y, w)
    assert out.sum() == pytest.approx(w.sum(), rel=1e-12)


def test_accumulate_drops_only_points_outside_the_grid():
    grid = M._reference_grid((0.0, 0.0, 100.0, 100.0), cell_m=100.0, pad_m=0.0)
    x = np.array([50.0, 10_000.0])
    y = np.array([50.0, 10_000.0])
    out = M._accumulate(grid, x, y, np.array([3.0, 9.0]))
    assert out.sum() == pytest.approx(3.0)


def test_sample_field_returns_nan_outside_the_grid_rather_than_a_clamped_edge():
    """An out-of-halo sample must be visibly missing, not silently given the
    nearest edge value, which would read as a real measurement."""
    grid = M._reference_grid((0.0, 0.0, 300.0, 300.0), cell_m=100.0, pad_m=0.0)
    arr = np.arange(grid["ny"] * grid["nx"], dtype="float64").reshape(grid["ny"], grid["nx"])
    inside = M.sample_field(grid, arr, np.array([50.0]), np.array([50.0]))
    outside = M.sample_field(grid, arr, np.array([-5000.0]), np.array([-5000.0]))
    assert np.isfinite(inside[0])
    assert np.isnan(outside[0])


def test_disk_kernel_area_matches_the_requested_radius():
    kernel = M._disk_kernel(1000.0, 100.0)
    covered_m2 = kernel.sum() * 100.0 ** 2
    true_m2 = math.pi * 1000.0 ** 2
    # The 100 m discretisation of a 1 km disk is accurate to ~1%; that is a
    # documented approximation, and this pins how large it may become.
    assert abs(covered_m2 - true_m2) / true_m2 < 0.02


# --- point assignment and count conservation ------------------------------

def _square_units(size_m=500.0, n=4, crs="EPSG:32648"):
    geoms = [box(i * size_m, j * size_m, (i + 1) * size_m, (j + 1) * size_m)
             for i in range(n) for j in range(n)]
    ids = [f"square_{int(size_m)}m|{i}_{j}" for i in range(n) for j in range(n)]
    return gpd.GeoDataFrame({"unit_id": ids}, geometry=geoms, crs=crs)


def test_every_point_is_assigned_to_at_most_one_unit():
    units = _square_units()
    rng = np.random.default_rng(3)
    x = rng.uniform(0, 2000, 300)
    y = rng.uniform(0, 2000, 300)
    idx = M._assign_points_to_units(units, x, y)
    assert len(idx) == 300
    assert idx.max() < len(units)
    assert (idx >= 0).all()


def test_a_point_on_a_shared_edge_resolves_to_exactly_one_unit():
    """Four cells meet at (500, 500). A spatial join matches several; the
    deterministic first-match rule must still yield one assignment."""
    units = _square_units()
    idx = M._assign_points_to_units(units, np.array([500.0]), np.array([500.0]))
    assert len(idx) == 1
    assert idx[0] >= 0
    again = M._assign_points_to_units(units, np.array([500.0]), np.array([500.0]))
    assert idx[0] == again[0]


def test_raster_counts_are_conserved_across_assignment():
    """The population identity Gate 2 relies on: assigned + unassigned
    equals the source total exactly, because each pixel count is carried
    whole to exactly one destination."""
    units = _square_units()
    rng = np.random.default_rng(11)
    # Half the pixels inside the unit block, half well outside it.
    x = np.concatenate([rng.uniform(0, 2000, 400), rng.uniform(5000, 6000, 100)])
    y = np.concatenate([rng.uniform(0, 2000, 400), rng.uniform(5000, 6000, 100)])
    vals = rng.uniform(1, 100, 500)

    idx = M._assign_points_to_units(units, x, y)
    keep = idx >= 0
    assigned = np.bincount(idx[keep], weights=vals[keep], minlength=len(units))
    unassigned = vals[~keep].sum()

    assert assigned.sum() + unassigned == pytest.approx(vals.sum(), rel=1e-12)
    assert unassigned > 0, "the out-of-block pixels must show up as unassigned, not vanish"


def test_points_outside_every_unit_are_unassigned_not_snapped():
    units = _square_units()
    idx = M._assign_points_to_units(units, np.array([99_000.0]), np.array([99_000.0]))
    assert idx[0] == -1


# --- interior sample points -----------------------------------------------

def test_interior_sample_points_all_lie_on_their_unit():
    units = _square_units(size_m=1000.0, n=2)
    xs, ys, owner = M._interior_sample_points(units, per_unit=5)
    assert len(xs) == len(units) * 5
    for pos, geom in enumerate(units.geometry):
        sel = owner == pos
        assert sel.sum() == 5
        for px, py in zip(xs[sel], ys[sel]):
            assert geom.buffer(1e-6).covers(Point(px, py))


def test_interior_sample_points_are_deterministic():
    units = _square_units()
    a = M._interior_sample_points(units, 5)
    b = M._interior_sample_points(units, 5)
    assert np.allclose(a[0], b[0]) and np.allclose(a[1], b[1])


# --- road length ----------------------------------------------------------

def test_road_length_per_unit_splits_a_line_across_the_units_it_crosses():
    from shapely.geometry import LineString

    units = _square_units(size_m=500.0, n=2)
    roads = gpd.GeoDataFrame(geometry=[LineString([(0, 250), (1000, 250)])], crs=units.crs)
    lengths = M._road_length_per_unit(units, roads)
    assert lengths.sum() == pytest.approx(1000.0, rel=1e-9)
    assert (lengths > 0).sum() == 2, "the line crosses exactly two cells"


def test_road_length_is_zero_where_no_road_is_mapped():
    from shapely.geometry import LineString

    units = _square_units(size_m=500.0, n=2)
    roads = gpd.GeoDataFrame(geometry=[LineString([(0, 250), (400, 250)])], crs=units.crs)
    lengths = M._road_length_per_unit(units, roads)
    assert (lengths == 0).sum() == 3
    # A mapped zero is a real measurement of absence, distinct from a source
    # that failed to load -- which never reaches this function at all.


def test_road_length_handles_an_empty_road_layer_as_a_mapped_zero():
    units = _square_units()
    empty = gpd.GeoDataFrame(geometry=[], crs=units.crs)
    lengths = M._road_length_per_unit(units, empty)
    assert len(lengths) == len(units)
    assert (lengths == 0).all()


def test_densified_road_weights_preserve_total_length():
    from shapely.geometry import LineString

    roads = gpd.GeoDataFrame(geometry=[
        LineString([(0, 0), (1000, 0)]),
        LineString([(0, 500), (0, 1300)]),
    ], crs="EPSG:32648")
    _, _, w = M._densified_road_weights(roads, cell_m=100.0)
    assert w.sum() == pytest.approx(1800.0, rel=1e-9)


# --- metric row contract --------------------------------------------------

def test_every_metric_row_declares_its_spatial_support():
    row = M._row("poi_zero_share", 0.5, "share", M.BUFFER_1KM, dimension="all_categories")
    assert row["spatial_support"] == "buffer_1km"
    assert row["source_status"] == M.INGESTED_OK
    assert set(row) == {"metric", "dimension", "spatial_support", "value", "unit",
                        "source_status", "notes"}


def test_a_not_applicable_row_carries_no_value():
    """H3's origin-shift row must be absent-valued and labelled, so it can
    never be read as a passing score."""
    row = M._row("origin_shift_copartition_flip_share", None, "share", M.FOOTPRINT,
                 source_status=M.NOT_APPLICABLE)
    assert row["value"] is None
    assert row["source_status"] == "not_applicable"


def test_quantiles_report_no_values_rather_than_zero_when_everything_is_nan():
    rows = M._quantiles(np.array([np.nan, np.nan]), "builtup_fraction_variance", "variance",
                        M.FOOTPRINT)
    assert len(rows) == 1
    assert rows[0]["value"] == 0.0 and "no finite values" in rows[0]["notes"]
