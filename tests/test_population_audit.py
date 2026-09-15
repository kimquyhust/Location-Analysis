import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from audit.population_audit import _reproject_sum, _target_grid, safe_relative_difference


def _write_synthetic_raster(path, array, transform, crs="EPSG:4326", nodata=-99999.0):
    with rasterio.open(
        path, "w", driver="GTiff", height=array.shape[0], width=array.shape[1],
        count=1, dtype="float32", crs=crs, transform=transform, nodata=nodata,
    ) as dst:
        dst.write(array.astype("float32"), 1)


def test_reproject_sum_conserves_total_population(tmp_path):
    # A 100x100 fine-resolution raster where every cell = 1 person: total
    # population is exactly 10,000. Resampling.sum onto a much coarser
    # common grid must not lose or invent population.
    array = np.ones((100, 100), dtype="float32")
    transform = from_origin(108.0, 16.0, 0.0009, 0.0009)  # ~100m/px near this latitude
    src_path = tmp_path / "synthetic.tif"
    _write_synthetic_raster(src_path, array, transform)

    bounds = (108.0, 16.0 - 100 * 0.0009, 108.0 + 100 * 0.0009, 16.0)
    dst_transform, width, height = _target_grid(bounds, resolution_m=1000.0)
    grid = _reproject_sum(src_path, dst_transform, width, height, src_nodata=-99999.0)

    total = np.nansum(grid)
    assert total == pytest.approx(10_000, rel=0.02)


def test_safe_relative_difference_undefined_near_zero():
    a = np.array([0.0, 0.5, 100.0, 50.0])
    b = np.array([0.0, 0.4, 90.0, 25.0])
    rel_diff, near_zero_mask = safe_relative_difference(a, b, eps=1.0)

    assert near_zero_mask.tolist() == [True, True, False, False]
    assert np.isnan(rel_diff[0]) and np.isnan(rel_diff[1])
    assert rel_diff[2] == pytest.approx(10.0 / 100.0)
    assert rel_diff[3] == pytest.approx(25.0 / 50.0)


def test_safe_relative_difference_handles_all_zero():
    a = np.array([0.0, 0.0])
    b = np.array([0.0, 0.0])
    rel_diff, near_zero_mask = safe_relative_difference(a, b, eps=1.0)
    assert near_zero_mask.all()
    assert np.all(np.isnan(rel_diff))
