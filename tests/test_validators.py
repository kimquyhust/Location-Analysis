from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from ingestion.validators import ValidationError, validate_osm_pbf, validate_raster

FIXTURE_PBF = Path("tests/fixtures/tiny_test.osm.pbf")


def _write_raster(path, crs="EPSG:4326", nodata=-99999.0):
    array = np.ones((5, 5), dtype="float32")
    transform = from_origin(108.0, 16.0, 0.001, 0.001)
    with rasterio.open(
        path, "w", driver="GTiff", height=5, width=5, count=1,
        dtype="float32", crs=crs, transform=transform, nodata=nodata,
    ) as dst:
        dst.write(array, 1)


def test_validate_raster_accepts_matching_crs_and_nodata(tmp_path):
    path = tmp_path / "ok.tif"
    _write_raster(path)
    meta = validate_raster(path, expected_crs="EPSG:4326", expected_nodata=-99999.0)
    assert meta["crs"] == "EPSG:4326"
    assert meta["width"] == 5 and meta["height"] == 5


def test_validate_raster_rejects_crs_mismatch(tmp_path):
    path = tmp_path / "wrong_crs.tif"
    _write_raster(path, crs="EPSG:32649")
    with pytest.raises(ValidationError, match="CRS"):
        validate_raster(path, expected_crs="EPSG:4326")


def test_validate_raster_rejects_nodata_mismatch(tmp_path):
    path = tmp_path / "wrong_nodata.tif"
    _write_raster(path, nodata=-1.0)
    with pytest.raises(ValidationError, match="NoData"):
        validate_raster(path, expected_nodata=-99999.0)


def test_validate_raster_no_expectations_still_checks_openability(tmp_path):
    path = tmp_path / "ok2.tif"
    _write_raster(path)
    meta = validate_raster(path)
    assert meta["width"] == 5


def test_validate_osm_pbf_accepts_valid_fixture():
    meta = validate_osm_pbf(FIXTURE_PBF)
    assert meta["node_count"] == 6
    assert meta["way_count"] == 2


def test_validate_osm_pbf_rejects_too_few_nodes():
    with pytest.raises(ValidationError, match="nodes"):
        validate_osm_pbf(FIXTURE_PBF, min_nodes=1000)


def test_validate_osm_pbf_rejects_too_few_ways():
    with pytest.raises(ValidationError, match="ways"):
        validate_osm_pbf(FIXTURE_PBF, min_ways=1000)


def test_validate_osm_pbf_rejects_nonexistent_file(tmp_path):
    with pytest.raises(ValidationError):
        validate_osm_pbf(tmp_path / "does_not_exist.osm.pbf")
