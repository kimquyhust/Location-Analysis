import geopandas as gpd
import shapely.geometry as sgeom

from poi.dedup import deduplicate_osm_pois, normalize_name

SMALL_POLY_A = sgeom.Polygon([
    (108.19995, 15.99995), (108.20005, 15.99995),
    (108.20005, 16.00005), (108.19995, 16.00005),
])
SMALL_POLY_B = sgeom.Polygon([  # a second, distinct polygon nearby
    (108.20025, 15.99995), (108.20035, 15.99995),
    (108.20035, 16.00005), (108.20025, 16.00005),
])


def _row(osm_type, osm_id, category, name, geometry, raw_tags=None):
    return {
        "osm_type": osm_type, "osm_id": osm_id, "category": category,
        "group": "commercial", "name": name, "raw_tags": raw_tags or {},
        "geometry": geometry,
    }


def _gdf(rows):
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def test_normalize_name_folds_case_and_diacritics():
    assert normalize_name("Winmart+") == "winmart"
    assert normalize_name("  Ngân Hàng  ") == "ngan hang"
    assert normalize_name(None) is None
    assert normalize_name("") is None


def test_node_polygon_same_name_within_tolerance_is_merged():
    node = _row("node", 1, "convenience", "WinMart", sgeom.Point(108.20, 16.00))
    poly = _row("way", 2, "convenience", "WinMart", SMALL_POLY_A)
    gdf = _gdf([node, poly])

    deduped, dups = deduplicate_osm_pois(gdf)

    assert len(deduped) == 1
    assert len(dups) == 1
    assert deduped.iloc[0]["osm_type"] == "way"  # polygon kept over point


def test_node_node_same_name_and_close_is_NOT_merged():
    # Two different node-mapped businesses with the same (franchise) name,
    # close together -- these are two real stores, not one place mapped
    # twice. Cross-geometry dedup must never touch a node-node pair.
    a = _row("node", 1, "convenience", "WinMart", sgeom.Point(108.20, 16.00))
    b = _row("node", 2, "convenience", "WinMart", sgeom.Point(108.20001, 16.00001))
    gdf = _gdf([a, b])

    deduped, dups = deduplicate_osm_pois(gdf)

    assert len(deduped) == 2
    assert len(dups) == 0


def test_way_way_same_name_and_close_is_NOT_merged():
    a = _row("way", 1, "convenience", "WinMart", SMALL_POLY_A)
    b = _row("way", 2, "convenience", "WinMart", SMALL_POLY_B)
    gdf = _gdf([a, b])

    deduped, dups = deduplicate_osm_pois(gdf)

    assert len(deduped) == 2
    assert len(dups) == 0


def test_far_apart_node_polygon_same_name_not_merged():
    node = _row("node", 1, "convenience", "WinMart", sgeom.Point(108.20, 16.00))
    poly = _row("way", 2, "convenience", "WinMart", sgeom.Polygon([
        (108.35, 16.10), (108.35001, 16.10), (108.35001, 16.10001), (108.35, 16.10001),
    ]))
    gdf = _gdf([node, poly])

    deduped, dups = deduplicate_osm_pois(gdf)

    assert len(deduped) == 2
    assert len(dups) == 0


def test_different_names_node_polygon_not_merged_even_if_close():
    node = _row("node", 1, "convenience", "WinMart", sgeom.Point(108.20, 16.00))
    poly = _row("way", 2, "convenience", "Circle K", SMALL_POLY_A)
    gdf = _gdf([node, poly])

    deduped, dups = deduplicate_osm_pois(gdf)

    assert len(deduped) == 2
    assert len(dups) == 0


def test_missing_name_never_merged():
    node = _row("node", 1, "school", None, sgeom.Point(108.20, 16.00))
    poly = _row("way", 2, "school", None, SMALL_POLY_A)
    gdf = _gdf([node, poly])

    deduped, dups = deduplicate_osm_pois(gdf)

    assert len(deduped) == 2
    assert len(dups) == 0


def test_brand_match_merges_even_without_matching_name():
    node = _row("node", 1, "convenience", "Cua hang so 5", SMALL_POLY_A.centroid,
                raw_tags={"brand": "WinMart"})
    node["geometry"] = sgeom.Point(108.20, 16.00)
    poly = _row("way", 2, "convenience", "WinMart Da Nang Branch", SMALL_POLY_A,
                raw_tags={"brand": "WinMart"})
    gdf = _gdf([node, poly])

    deduped, dups = deduplicate_osm_pois(gdf)

    assert len(deduped) == 1
    assert len(dups) == 1


def test_chained_candidates_transitively_merge_via_shared_polygon():
    # Two entrance/info nodes both plausibly referring to the same mapped
    # polygon (e.g. duplicate entrance tagging) -- point1<->polygon and
    # polygon<->point2 edges should merge all three into ONE cluster even
    # though point1 and point2 are farther apart from each other than the
    # tolerance, because the graph is built on point-polygon edges and
    # connectivity is transitive.
    point1 = _row("node", 1, "hospital", "City Hospital", sgeom.Point(108.19998, 16.00000))
    polygon = _row("way", 2, "hospital", "City Hospital", SMALL_POLY_A)
    point2 = _row("node", 3, "hospital", "City Hospital", sgeom.Point(108.20002, 16.00000))
    gdf = _gdf([point1, polygon, point2])

    deduped, dups = deduplicate_osm_pois(gdf)

    assert len(deduped) == 1
    assert len(dups) == 2
    assert deduped.iloc[0]["osm_type"] == "way"


def test_chained_candidates_are_deterministic_across_row_order():
    point1 = _row("node", 1, "hospital", "City Hospital", sgeom.Point(108.19998, 16.00000))
    polygon = _row("way", 2, "hospital", "City Hospital", SMALL_POLY_A)
    point2 = _row("node", 3, "hospital", "City Hospital", sgeom.Point(108.20002, 16.00000))

    forward = deduplicate_osm_pois(_gdf([point1, polygon, point2]))
    reversed_order = deduplicate_osm_pois(_gdf([point2, polygon, point1]))

    assert sorted(forward[0]["osm_id"].tolist()) == sorted(reversed_order[0]["osm_id"].tolist())
