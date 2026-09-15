"""Deterministic reruns with pinned inputs.

Gate 2's claim is that re-running against the same pinned sources and the
same config yields the same numbers. That is tested here end to end on a
small synthetic AOI -- unit generation, every seeded sample, and the
config/environment identity a benchmark row records.
"""

import numpy as np
import pytest
import yaml

from spatial import metrics as M
from spatial.aoi import aoi_checksum, build_aoi
from spatial.benchmark import code_version, environment, hash_config
from spatial.candidates import H3Grid, SquareGrid

from pathlib import Path

SPEC = {"id": "t_repro", "context": "dense_urban", "lat": 21.028, "lon": 105.852,
        "width_km": 2, "height_km": 2}
CANDIDATES = [SquareGrid(size_m=500), H3Grid(resolution=9)]


@pytest.fixture(scope="module")
def config():
    return yaml.safe_load(open("config/gate2.yaml"))


@pytest.fixture(scope="module")
def aoi():
    return build_aoi(SPEC)


@pytest.mark.parametrize("candidate", CANDIDATES, ids=lambda c: c.id)
def test_unit_generation_is_bit_identical_on_rerun(aoi, candidate):
    a = candidate.units(aoi.polygon, aoi.metric_crs)
    b = candidate.units(aoi.polygon, aoi.metric_crs)
    assert a["unit_id"].tolist() == b["unit_id"].tolist()
    np.testing.assert_array_equal(a["area_m2"].to_numpy(), b["area_m2"].to_numpy())
    np.testing.assert_array_equal(a["rep_lat"].to_numpy(), b["rep_lat"].to_numpy())


def test_seeded_point_sampling_is_reproducible(aoi, config):
    import geopandas as gpd

    poly = gpd.GeoSeries([aoi.polygon], crs="EPSG:4326").to_crs(aoi.metric_crs).iloc[0]
    seed = int(config["run"]["random_seed"])
    a = M._deterministic_points_in_aoi(poly, aoi.metric_crs, 200, seed)
    b = M._deterministic_points_in_aoi(poly, aoi.metric_crs, 200, seed)
    for x, y in zip(a, b):
        np.testing.assert_array_equal(x, y)


def test_a_different_seed_gives_different_points(aoi, config):
    """Reproducibility must come from the seed, not from the sampler being
    degenerate."""
    import geopandas as gpd

    poly = gpd.GeoSeries([aoi.polygon], crs="EPSG:4326").to_crs(aoi.metric_crs).iloc[0]
    a = M._deterministic_points_in_aoi(poly, aoi.metric_crs, 200, 1)
    b = M._deterministic_points_in_aoi(poly, aoi.metric_crs, 200, 2)
    assert not np.array_equal(a[0], b[0])


def test_aoi_checksum_is_reproducible(aoi):
    assert aoi_checksum(aoi) == aoi_checksum(build_aoi(SPEC))


def test_config_hash_is_stable_and_content_addressed(tmp_path):
    a = hash_config(Path("config/gate2.yaml"), Path("config/spatial.yaml"))
    b = hash_config(Path("config/spatial.yaml"), Path("config/gate2.yaml"))
    assert a == b, "hash must not depend on argument order"
    assert len(a) == 64

    changed = tmp_path / "gate2.yaml"
    changed.write_text(Path("config/gate2.yaml").read_text() + "\n# a change\n")
    assert hash_config(changed, Path("config/spatial.yaml")) != a


def test_code_version_marks_an_uncommitted_tree():
    """A run on a dirty tree is legitimate, but the recorded commit must not
    imply a reproducibility guarantee the tree does not offer."""
    version = code_version()
    assert version
    assert version == "unknown" or len(version.split("+")[0]) == 40


def test_environment_records_every_library_that_can_move_a_number():
    env = environment()
    for key in ("python", "platform", "geopandas", "shapely", "rasterio", "numpy", "h3", "pandas"):
        assert env.get(key), key
    assert env["cpu_count_logical"] and env["total_ram_bytes"]


def test_reference_grid_is_a_pure_function_of_its_inputs():
    bounds = (100.0, 200.0, 5100.0, 5200.0)
    a = M._reference_grid(bounds, 100.0, 1000.0)
    b = M._reference_grid(bounds, 100.0, 1000.0)
    assert a == b
    # Origin snapped to the cell grid, so the field does not drift with the
    # AOI's arbitrary bounds.
    assert a["x0"] % 100.0 == 0 and a["y0"] % 100.0 == 0


def test_interior_sample_points_do_not_depend_on_row_order():
    import geopandas as gpd
    from shapely.geometry import box

    geoms = [box(i * 500, 0, (i + 1) * 500, 500) for i in range(4)]
    units = gpd.GeoDataFrame({"unit_id": [f"u{i}" for i in range(4)]},
                             geometry=geoms, crs="EPSG:32648")
    xs_a, ys_a, owner_a = M._interior_sample_points(units, 5)
    reordered = units.iloc[::-1].reset_index(drop=True)
    xs_b, ys_b, owner_b = M._interior_sample_points(reordered, 5)
    # Same set of points, just attributed to reversed positions.
    assert sorted(np.round(xs_a, 6)) == sorted(np.round(xs_b, 6))
