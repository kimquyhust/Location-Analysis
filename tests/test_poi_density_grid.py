import geopandas as gpd
import shapely.geometry as sgeom

from audit.poi_audit import density_grid

# A ~2.2km x 2.2km box in EPSG:4326 at this latitude -- big enough for a
# handful of 1km cells, small enough to keep the test fast.
BBOX = (108.00, 16.00, 108.02, 16.02)


def test_density_grid_includes_zero_count_cells():
    # A single point in one corner of the bbox -- most cells must be
    # reported as empty (count=0), not simply absent from the output.
    gdf = gpd.GeoDataFrame({"geometry": [sgeom.Point(108.001, 16.001)]}, crs="EPSG:4326")
    grid = density_grid(gdf, BBOX, cell_size_m=1000.0)

    assert len(grid) > 1
    assert (grid["count"] == 0).any()
    assert grid["count"].sum() == 1


def test_density_grid_empty_input_still_covers_full_extent():
    gdf = gpd.GeoDataFrame({"geometry": []}, crs="EPSG:4326")
    grid = density_grid(gdf, BBOX, cell_size_m=1000.0)

    assert len(grid) > 1
    assert (grid["count"] == 0).all()
