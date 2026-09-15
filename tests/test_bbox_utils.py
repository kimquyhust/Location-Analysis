import geopandas as gpd
import shapely.geometry as sgeom

from audit.bbox_utils import clip_to_bbox

BBOX = (0.0, 0.0, 10.0, 10.0)


def test_point_inside_bbox_kept():
    gdf = gpd.GeoDataFrame({"geometry": [sgeom.Point(5, 5)]}, crs="EPSG:4326")
    out = clip_to_bbox(gdf, BBOX)
    assert len(out) == 1


def test_point_outside_bbox_dropped():
    gdf = gpd.GeoDataFrame({"geometry": [sgeom.Point(50, 50)]}, crs="EPSG:4326")
    out = clip_to_bbox(gdf, BBOX)
    assert len(out) == 0


def test_line_straddling_boundary_is_cut_not_just_filtered():
    # A line from (5,5) to (20,5) only half falls inside the bbox -- the
    # clipped geometry's length must reflect that, not the full line.
    line = sgeom.LineString([(5, 5), (20, 5)])
    gdf = gpd.GeoDataFrame({"geometry": [line]}, crs="EPSG:4326")
    out = clip_to_bbox(gdf, BBOX)
    assert len(out) == 1
    assert out.geometry.iloc[0].length == 5.0  # clipped at x=10, not 15


def test_empty_input_returns_empty():
    gdf = gpd.GeoDataFrame({"geometry": []}, crs="EPSG:4326")
    out = clip_to_bbox(gdf, BBOX)
    assert len(out) == 0
