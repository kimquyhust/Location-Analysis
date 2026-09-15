from pathlib import Path

from poi.osm_extract import parse_osm_aoi

FIXTURE = Path("tests/fixtures/tiny_test.osm.pbf")


def test_parses_poi_road_and_intersection():
    extract = parse_osm_aoi(FIXTURE, minimum_degree=3)

    # One POI (the tagged school node) mapped to the right taxonomy leaf.
    assert len(extract.poi_gdf) == 1
    row = extract.poi_gdf.iloc[0]
    assert row["category"] == "school"
    assert row["group"] == "education"
    assert row["name"] == "Test School"

    # Two driveable ways (primary + residential), both accepted.
    assert len(extract.road_gdf) == 2
    assert set(extract.road_gdf["highway"]) == {"primary", "residential"}
    assert extract.road_gdf.set_index("highway").loc["primary", "is_major"]
    assert not extract.road_gdf.set_index("highway").loc["residential", "is_major"]

    # Node 1 is the shared interior node of both ways (degree 2+2=4) --
    # above the minimum_degree=3 threshold, so it must be detected as an
    # intersection even though the two ways never explicitly declare a
    # junction; nodes only touched by one way must NOT appear.
    assert len(extract.intersections_gdf) == 1
    assert extract.intersections_gdf.iloc[0]["node_id"] == 1
    assert extract.intersections_gdf.iloc[0]["degree"] == 4


def test_higher_minimum_degree_finds_no_intersections():
    extract = parse_osm_aoi(FIXTURE, minimum_degree=5)
    assert len(extract.intersections_gdf) == 0


def test_clip_bbox_excludes_geometry_outside_the_box():
    # The school POI sits at (108.0005, 16.0005); a bbox that excludes it
    # should drop it from the exported GeoDataFrame.
    extract = parse_osm_aoi(FIXTURE, minimum_degree=3, clip_bbox=(109.0, 17.0, 110.0, 18.0))
    assert len(extract.poi_gdf) == 0
    assert len(extract.road_gdf) == 0


# --- Gate 3 remediation F1: relation assembly, identity, failure ------------------
#
# A synthetic PBF written with pyosmium's SimpleWriter. Coordinates are in
# degrees near (0, 0); a 0.001 deg step is ~111 m, so areas below are
# compared as ratios, not absolute m^2.

import numpy as np
import osmium
import osmium.osm.mutable as osm_mutable
import pytest
import shapely
from shapely.geometry import Point


def _square(nid0, x0, y0, size):
    """Four node ids + closed node list for a square with lower-left (x0, y0)."""
    coords = [(x0, y0), (x0 + size, y0), (x0 + size, y0 + size), (x0, y0 + size)]
    ids = [nid0 + i for i in range(4)]
    return ids, coords, ids + [ids[0]]


@pytest.fixture(scope="module")
def synthetic_pbf(tmp_path_factory):
    p = tmp_path_factory.mktemp("osm") / "synthetic.osm.pbf"
    w = osmium.SimpleWriter(str(p))
    nodes = {}

    def add_nodes(ids, coords, tags=None):
        for i, (x, y) in zip(ids, coords):
            nodes[i] = (x, y)
            w.add_node(osm_mutable.Node(id=i, location=(x, y), tags=tags or {}))

    # University campus: outer square 0..0.010 with a courtyard hole
    # 0.004..0.006 and a second detached outer square 0.020..0.025.
    o_ids, o_xy, o_ring = _square(100, 0.0, 0.0, 0.010)
    h_ids, h_xy, h_ring = _square(110, 0.004, 0.004, 0.002)
    d_ids, d_xy, d_ring = _square(120, 0.020, 0.0, 0.005)
    add_nodes(o_ids, o_xy); add_nodes(h_ids, h_xy); add_nodes(d_ids, d_xy)
    # The outer way ALSO carries amenity=university (old-style duplicate tagging).
    w.add_way(osm_mutable.Way(id=1000, nodes=o_ring, tags={"amenity": "university", "name": "Campus"}))
    w.add_way(osm_mutable.Way(id=1001, nodes=h_ring, tags={"barrier": "fence"}))
    w.add_way(osm_mutable.Way(id=1002, nodes=d_ring, tags={"building": "yes"}))
    w.add_relation(osm_mutable.Relation(
        id=5000, members=[("w", 1000, "outer"), ("w", 1001, "inner"), ("w", 1002, "outer")],
        tags={"type": "multipolygon", "amenity": "university", "name": "Campus"}))
    # A university NODE inside the campus with the same name: cross-geometry duplicate for dedup.
    add_nodes([130], [(0.002, 0.002)], {"amenity": "university", "name": "Campus"})

    # Industrial site relation: one outer way present, the other outer way
    # (id 1101) deliberately NOT written -> assembly must fail, not vanish.
    i_ids, i_xy, i_ring = _square(200, 0.050, 0.0, 0.010)
    add_nodes(i_ids, i_xy)
    w.add_way(osm_mutable.Way(id=1100, nodes=i_ring, tags={}))
    w.add_relation(osm_mutable.Relation(
        id=5001, members=[("w", 1100, "outer"), ("w", 1101, "outer")],
        tags={"type": "multipolygon", "landuse": "industrial", "name": "Broken site"}))

    # Complete industrial multipolygon with a hole (for area intersection).
    j_ids, j_xy, j_ring = _square(300, 0.100, 0.0, 0.010)
    k_ids, k_xy, k_ring = _square(310, 0.102, 0.002, 0.004)
    add_nodes(j_ids, j_xy); add_nodes(k_ids, k_xy)
    w.add_way(osm_mutable.Way(id=1200, nodes=j_ring, tags={}))
    w.add_way(osm_mutable.Way(id=1201, nodes=k_ring, tags={}))
    w.add_relation(osm_mutable.Relation(
        id=5002, members=[("w", 1200, "outer"), ("w", 1201, "inner")],
        tags={"type": "multipolygon", "landuse": "industrial", "name": "Complete site"}))

    # Park multipolygon (park_area + park_recreation), complete.
    p_ids, p_xy, p_ring = _square(400, 0.200, 0.0, 0.006)
    add_nodes(p_ids, p_xy)
    w.add_way(osm_mutable.Way(id=1300, nodes=p_ring, tags={}))
    w.add_relation(osm_mutable.Relation(id=5003, members=[("w", 1300, "outer")],
                                        tags={"type": "multipolygon", "leisure": "park", "name": "Park"}))

    # Grouping (site) relation: a night market made of two open street segments.
    add_nodes([500, 501, 502], [(0.300, 0.0), (0.301, 0.0), (0.302, 0.0)])
    w.add_way(osm_mutable.Way(id=1400, nodes=[500, 501], tags={"highway": "residential"}))
    w.add_way(osm_mutable.Way(id=1401, nodes=[501, 502], tags={"highway": "residential"}))
    w.add_relation(osm_mutable.Relation(id=5004, members=[("w", 1400, ""), ("w", 1401, "")],
                                        tags={"type": "site", "amenity": "marketplace", "name": "Night market"}))
    # Grouping relation with a missing member -> failed.
    w.add_relation(osm_mutable.Relation(id=5005, members=[("w", 1400, ""), ("w", 9999, "")],
                                        tags={"type": "site", "amenity": "marketplace", "name": "Broken market"}))

    # Open way bus platform (linear entity) and a plain school node.
    add_nodes([600, 601], [(0.400, 0.0), (0.4005, 0.0)])
    w.add_way(osm_mutable.Way(id=1500, nodes=[600, 601], tags={"public_transport": "platform", "bus": "yes"}))
    add_nodes([700], [(0.500, 0.0)], {"amenity": "school", "name": "S"})
    w.close()
    return p


def test_multipolygon_relation_is_assembled_with_hole_and_second_outer(synthetic_pbf):
    ex = parse_osm_aoi(synthetic_pbf)
    uni = ex.poi_gdf[(ex.poi_gdf["category"] == "higher_education") & (ex.poi_gdf["osm_type"] == "relation")]
    assert len(uni) == 1
    g = uni.geometry.iloc[0]
    assert g.geom_type == "MultiPolygon" and len(g.geoms) == 2 and g.is_valid
    big = max(g.geoms, key=lambda x: x.area)
    assert len(big.interiors) == 1
    # area = 0.010^2 - 0.002^2 + 0.005^2 (degrees^2)
    assert g.area == pytest.approx(0.010 ** 2 - 0.002 ** 2 + 0.005 ** 2, rel=1e-9)
    # the hole is not part of the entity
    assert not g.contains(Point(0.005, 0.005)) and g.contains(Point(0.001, 0.001))
    assert ex.assembly["relations"]["higher_education"] == {"relevant": 1, "assembled": 1, "failed": 0, "failed_reasons": {}}


def test_relation_and_member_way_with_same_category_count_once(synthetic_pbf):
    ex = parse_osm_aoi(synthetic_pbf)
    uni = ex.poi_gdf[ex.poi_gdf["category"] == "higher_education"]
    # relation kept, member way 1000 dropped; the node 130 survives here and
    # is collapsed by the cross-geometry dedup step (same name, inside).
    assert set(zip(uni["osm_type"], uni["osm_id"])) == {("relation", 5000), ("node", 130)}
    assert ex.assembly["member_duplicates_dropped"] == {"higher_education": 1}
    assert ex.member_duplicates[0]["dropped_osm_id"] == 1000 and ex.member_duplicates[0]["kept_osm_id"] == 5000
    from poi.dedup import deduplicate_osm_pois
    kept, dropped = deduplicate_osm_pois(uni.copy(), max_distance_m=75, metric_crs="EPSG:32631")
    assert len(kept) == 1 and kept.iloc[0]["osm_type"] == "relation" and len(dropped) == 1


def test_relation_entity_counts_by_point_on_surface_and_measures_distance_to_geometry(synthetic_pbf):
    from features import poi as P
    ex = parse_osm_aoi(synthetic_pbf)
    uni = ex.poi_gdf[(ex.poi_gdf["category"] == "higher_education") & (ex.poi_gdf["osm_type"] == "relation")]
    metric = uni.to_crs("EPSG:32631")
    pois = P.canonical_pois(metric, 0)
    pos = pois.count_points[0]
    assert metric.geometry.iloc[0].contains(pos)            # point_on_surface lies inside a part
    # a representative point 200 m west of the campus edge: the entity is
    # counted at 3 km (its point_on_surface is inside the ~1.1 km square)
    # and not at 100 m; the distance is to the polygon edge (~200 m), not
    # to the centroid of the two-part multipolygon (which is much farther).
    edge = metric.geometry.iloc[0].bounds[0]
    rep = np.array([Point(edge - 200, metric.geometry.iloc[0].centroid.y)], dtype=object)
    assert P.counts_within(rep, pois.count_points, pois.categories, 3000.0, ["higher_education"])[0] == 1
    assert P.counts_within(rep, pois.count_points, pois.categories, 100.0, ["higher_education"])[0] == 0
    d = P.nearest_distance(rep, metric.geometry.to_numpy())[0]
    assert d == pytest.approx(200.0, rel=0.02)
    assert d < rep[0].distance(metric.geometry.iloc[0].centroid) - 500


def test_industrial_multipolygon_area_intersection_excludes_the_hole(synthetic_pbf):
    from features import poi as P
    import geopandas as gpd
    from shapely.geometry import box
    ex = parse_osm_aoi(synthetic_pbf)
    ind = ex.area_gdf[ex.area_gdf["area_category"] == "industrial_site"]
    assert set(zip(ind["osm_type"], ind["osm_id"])) == {("relation", 5002)}   # the broken one is absent
    # a unit covering the western half of the complete site: half the outer minus half the hole
    unit = gpd.GeoDataFrame({"unit_id": ["u"]}, geometry=[box(0.100, 0.0, 0.105, 0.010)], crs="EPSG:4326")
    area = P.intersection_area_per_unit(unit, ind)
    assert area[0] == pytest.approx(0.005 * 0.010 - 0.003 * 0.004, rel=1e-9)


def test_failed_relation_assembly_is_reported_not_dropped(synthetic_pbf):
    ex = parse_osm_aoi(synthetic_pbf)
    failed = {(f["osm_type"], f["osm_id"], f["category"]): f["reason"] for f in ex.assembly["failed_entities"]}
    assert failed[("relation", 5001, "industrial_site")] == "members_missing_from_extract"
    assert failed[("relation", 5005, "marketplace")] == "members_missing_from_extract"
    assert ex.assembly_failures_by_category == {"industrial_site": 1, "marketplace": 1}
    rel = ex.assembly["relations"]
    assert rel["industrial_site"] == {"relevant": 2, "assembled": 1, "failed": 1,
                                      "failed_reasons": {"members_missing_from_extract": 1}}
    assert rel["marketplace"]["relevant"] == 2 and rel["marketplace"]["failed"] == 1
    # the partial geometry of the broken site is recorded for audit
    part = [f for f in ex.assembly["failed_entities"] if f["osm_id"] == 5001][0]["partial_bounds_wgs84"]
    assert part == pytest.approx([0.050, 0.0, 0.060, 0.010])
    # ...and the failure is not clipped away by a bbox that excludes it
    ex2 = parse_osm_aoi(synthetic_pbf, clip_bbox=(0.0, -0.01, 0.03, 0.02))
    assert ex2.assembly_failures_by_category == {"industrial_site": 1, "marketplace": 1}


def test_grouping_relation_and_open_way_become_linear_entities(synthetic_pbf):
    ex = parse_osm_aoi(synthetic_pbf)
    market = ex.poi_gdf[(ex.poi_gdf["category"] == "marketplace")]
    assert set(zip(market["osm_type"], market["osm_id"])) == {("relation", 5004)}
    g = market.geometry.iloc[0]
    assert g.geom_type in ("LineString", "MultiLineString") and g.length == pytest.approx(0.002, rel=1e-9)
    assert g.contains(shapely.Point(0.301, 0.0)) or g.distance(shapely.Point(0.301, 0.0)) < 1e-12
    bus = ex.poi_gdf[ex.poi_gdf["category"] == "transit_bus_stop"] if "transit_bus_stop" in set(ex.poi_gdf["category"]) \
        else ex.poi_gdf[ex.poi_gdf["category"] == "transport_bus_stop"]
    assert len(bus) == 1 and bus.geometry.iloc[0].geom_type == "LineString"
    assert ex.open_way_entity_counts == {"transport_bus_stop": 1}
    # point_on_surface of a line lies on the line
    pos = bus.geometry.iloc[0].representative_point()
    assert bus.geometry.iloc[0].distance(pos) < 1e-12


def test_park_relation_feeds_both_area_and_poi_tables_once(synthetic_pbf):
    from features import poi as P
    ex = parse_osm_aoi(synthetic_pbf)
    parks_area = ex.area_gdf[ex.area_gdf["area_category"] == "park_area"]
    parks_poi = ex.poi_gdf[ex.poi_gdf["category"] == "park_recreation"]
    assert list(parks_area["osm_id"]) == [5003] and list(parks_poi["osm_id"]) == [5003]
    assert len(P.park_geometries(parks_area, parks_poi)) == 1
