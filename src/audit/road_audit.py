"""Road audit: OSM vs. Overture Transportation, for the Da Nang-Hoi An AOI.

Produces comparable subsets and metrics WITHOUT ever unioning the two
sources into one graph, per COWORK_START_PROMPT.md. Overlap/matched-length
is a geometric proximity estimate (buffer-based), not a claim of entity-
level conflation -- the two networks are topologically independent objects
throughout.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import geopandas as gpd
import networkx as nx
from shapely import STRtree
from shapely.ops import unary_union

from ..roads.topology import (
    component_length_shares,
    induced_subgraph_within_bbox,
    intersection_nodes,
    project_node_locations,
)
from .bbox_utils import clip_to_bbox as _clip_to_bbox

METRIC_CRS = "EPSG:32649"
DEFAULT_MATCH_BUFFER_M = 10.0  # proximity tolerance for "the same road" -- a
# documented, reviewable prototype parameter (not a config value, since no
# road-matching-tolerance parameter exists in config/*.yaml and this task's
# scope is not to add new schema; Gate 2 should decide whether to promote
# this into config if the audit becomes a recurring pipeline step).


def length_by_class(gdf_wgs84: gpd.GeoDataFrame, class_col: str, eval_bbox: tuple) -> dict:
    clipped = _clip_to_bbox(gdf_wgs84, eval_bbox)
    if len(clipped) == 0:
        return {}
    projected = clipped.to_crs(METRIC_CRS)
    projected["length_m"] = projected.geometry.length
    return projected.groupby(class_col)["length_m"].sum().sort_values(ascending=False).to_dict()


def _matched_length_one_direction(source: gpd.GeoSeries, other: gpd.GeoSeries, buffer_m: float) -> float:
    """For each geometry in `source`, find nearby geometries in `other`
    (STRtree `dwithin` query -- local, not a global union) and measure how
    much of the source geometry's length falls within `buffer_m` of them.
    Avoids buffering+unioning the entire `other` dataset at once, which
    does not scale to tens of thousands of road segments.
    """
    other_values = other.values
    tree = STRtree(other_values)
    matched = 0.0
    for geom in source.values:
        length = geom.length
        if length == 0:
            continue
        idx = tree.query(geom, predicate="dwithin", distance=buffer_m)
        if len(idx) == 0:
            continue
        nearby_buffer = unary_union([other_values[i].buffer(buffer_m) for i in idx])
        matched += geom.intersection(nearby_buffer).length
    return matched


def matched_length_estimate(
    a_wgs84: gpd.GeoDataFrame,
    b_wgs84: gpd.GeoDataFrame,
    eval_bbox: tuple,
    buffer_m: float = DEFAULT_MATCH_BUFFER_M,
) -> dict:
    """For each line in `a`, find nearby `b` lines (STRtree, localized) and
    measure how much of `a`'s length falls within `buffer_m` of them
    ("matched"), and vice versa. This is a geometric proximity estimate,
    not an entity match -- it says nothing about whether the matched
    segments represent the same real-world way, only that the two networks
    run close together there.
    """
    a = _clip_to_bbox(a_wgs84, eval_bbox).to_crs(METRIC_CRS)
    b = _clip_to_bbox(b_wgs84, eval_bbox).to_crs(METRIC_CRS)
    if len(a) == 0 or len(b) == 0:
        return {
            "a_total_length_m": float(a.geometry.length.sum()) if len(a) else 0.0,
            "b_total_length_m": float(b.geometry.length.sum()) if len(b) else 0.0,
            "a_matched_length_m": 0.0,
            "b_matched_length_m": 0.0,
        }

    a_total = float(a.geometry.length.sum())
    b_total = float(b.geometry.length.sum())

    a_matched = _matched_length_one_direction(a.geometry, b.geometry, buffer_m)
    b_matched = _matched_length_one_direction(b.geometry, a.geometry, buffer_m)

    return {
        "buffer_m": buffer_m,
        "a_total_length_m": a_total,
        "b_total_length_m": b_total,
        "a_matched_length_m": a_matched,
        "a_only_length_m": a_total - a_matched,
        "a_matched_share": (a_matched / a_total) if a_total > 0 else None,
        "b_matched_length_m": b_matched,
        "b_only_length_m": b_total - b_matched,
        "b_matched_share": (b_matched / b_total) if b_total > 0 else None,
    }


def unmatched_major_sample(
    a_wgs84: gpd.GeoDataFrame,
    b_wgs84: gpd.GeoDataFrame,
    eval_bbox: tuple,
    is_major_col: str,
    buffer_m: float = DEFAULT_MATCH_BUFFER_M,
    top_n: int = 15,
) -> list[dict]:
    """Return the longest major-road segments in `a` that have no nearby
    `b` coverage -- a reviewable sample for manual/visual inspection, not a
    claim that inspection has already been performed."""
    a = _clip_to_bbox(a_wgs84[a_wgs84[is_major_col]], eval_bbox)
    b = _clip_to_bbox(b_wgs84, eval_bbox)
    if len(a) == 0:
        return []
    a_m = a.to_crs(METRIC_CRS)
    b_m = b.to_crs(METRIC_CRS) if len(b) else None
    b_tree = STRtree(b_m.geometry.values) if b_m is not None and len(b_m) else None

    rows = []
    for _, row in a_m.iterrows():
        geom = row.geometry
        length_m = geom.length
        if length_m == 0:
            continue
        if b_tree is None:
            unmatched_len = length_m
        else:
            idx = b_tree.query(geom, predicate="dwithin", distance=buffer_m)
            if len(idx) == 0:
                unmatched_len = length_m
            else:
                nearby_buffer = unary_union([b_m.geometry.values[i].buffer(buffer_m) for i in idx])
                unmatched_len = geom.difference(nearby_buffer).length
        if unmatched_len / length_m > 0.5:  # majority of this segment has no nearby counterpart
            centroid = geom.centroid
            rows.append({
                "id": row.get("osm_id", row.get("id")),
                "length_m": length_m,
                "unmatched_length_m": unmatched_len,
                "centroid_x_32649": centroid.x,
                "centroid_y_32649": centroid.y,
            })
    rows.sort(key=lambda r: r["unmatched_length_m"], reverse=True)
    return rows[:top_n]


@dataclass
class RoadAuditResult:
    osm_length_by_class_m: dict
    overture_length_by_class_m: dict
    # Acquisition-halo-scope (unrestricted graph, includes the ~3km halo) --
    # kept only as context, clearly separate from the evaluation-scope
    # numbers the report should lead with.
    osm_connectivity_halo_scope: dict
    overture_connectivity_halo_scope: dict
    osm_intersection_count_halo_scope: int
    overture_connector_intersection_count_halo_scope: int
    # Evaluation-scope (induced subgraph on nodes inside eval_bbox only,
    # both endpoints of every counted edge also inside eval_bbox) -- the
    # scope that is actually comparable to length_by_class/matched_length,
    # and the scope OSM and Overture are both computed in identically.
    osm_connectivity_eval_scope: dict
    overture_connectivity_eval_scope: dict
    osm_intersection_count_eval_scope: int
    overture_connector_intersection_count_eval_scope: int
    matched_length: dict
    unmatched_major_osm_sample: list
    unmatched_major_overture_sample: list
    feature_impact_notes: list = field(default_factory=list)


def run_road_audit(
    osm_road_gdf: gpd.GeoDataFrame,
    osm_road_graph: nx.MultiGraph,
    osm_node_location: dict,
    overture_road_gdf: gpd.GeoDataFrame,
    overture_road_graph: nx.MultiGraph,
    overture_node_xy_wgs84: dict,
    eval_bbox: tuple,
    acquisition_bbox: tuple,
    minimum_degree: int = 3,
    unmatched_major_top_n: int = 8,
) -> RoadAuditResult:
    # --- Acquisition-halo-scope: induced subgraph within acquisition_bbox,
    # NOT the raw unbounded graph. `osmium extract --strategy complete_ways`
    # can pull in the full length of any way that merely touches the
    # requested bbox, which can extend hundreds of km beyond it (observed
    # for this AOI) -- so the raw graph is not a safe stand-in for "the
    # halo." Bounding it here, with the same rule used for evaluation
    # scope, is what makes "halo-scope" and "evaluation-scope" actually
    # comparable, nested scopes rather than one bounded and one not.
    osm_halo_graph, osm_halo_node_location = induced_subgraph_within_bbox(osm_road_graph, osm_node_location, acquisition_bbox)
    overture_halo_graph, overture_halo_node_location = induced_subgraph_within_bbox(overture_road_graph, overture_node_xy_wgs84, acquisition_bbox)

    osm_node_xy_halo = project_node_locations(osm_halo_node_location)
    overture_node_xy_halo = project_node_locations(overture_halo_node_location)

    osm_conn_halo = component_length_shares(osm_halo_graph, osm_node_xy_halo)
    overture_conn_halo = component_length_shares(overture_halo_graph, overture_node_xy_halo)

    osm_intersections_halo = len(intersection_nodes(osm_halo_graph, minimum_degree))
    overture_intersections_halo = len(intersection_nodes(overture_halo_graph, minimum_degree))

    # --- Evaluation-scope (induced subgraph within eval_bbox, same rule
    # applied identically to both sources -- see
    # roads.topology.induced_subgraph_within_bbox for the boundary-node
    # definition) ---
    osm_eval_graph, osm_eval_node_location = induced_subgraph_within_bbox(osm_road_graph, osm_node_location, eval_bbox)
    overture_eval_graph, overture_eval_node_location = induced_subgraph_within_bbox(overture_road_graph, overture_node_xy_wgs84, eval_bbox)

    osm_node_xy_eval = project_node_locations(osm_eval_node_location)
    overture_node_xy_eval = project_node_locations(overture_eval_node_location)

    osm_conn_eval = component_length_shares(osm_eval_graph, osm_node_xy_eval)
    overture_conn_eval = component_length_shares(overture_eval_graph, overture_node_xy_eval)

    osm_intersections_eval = len(intersection_nodes(osm_eval_graph, minimum_degree))
    overture_intersections_eval = len(intersection_nodes(overture_eval_graph, minimum_degree))

    matched = matched_length_estimate(osm_road_gdf, overture_road_gdf, eval_bbox)

    osm_unmatched_major = unmatched_major_sample(osm_road_gdf, overture_road_gdf, eval_bbox, "is_major", top_n=unmatched_major_top_n)
    overture_unmatched_major = unmatched_major_sample(overture_road_gdf, osm_road_gdf, eval_bbox, "is_major", top_n=unmatched_major_top_n)

    notes = []
    if matched.get("a_matched_share") is not None and matched["a_matched_share"] < 0.8:
        notes.append(
            f"OSM matched share is {matched['a_matched_share']:.1%} -- road_length/road_density computed "
            f"from OSM alone would miss a non-trivial amount of Overture-only road geometry in this AOI."
        )
    if osm_conn_eval.get("largest_component_share") is not None and osm_conn_eval["largest_component_share"] < 0.9:
        notes.append(
            f"OSM largest connected component (evaluation scope) covers only "
            f"{osm_conn_eval['largest_component_share']:.1%} of total driveable length -- "
            f"distance/routing-style features would be sensitive to which component a unit falls in."
        )
    halo_vs_eval_gap = None
    if osm_conn_halo.get("largest_component_share") and osm_conn_eval.get("largest_component_share"):
        halo_vs_eval_gap = osm_conn_halo["largest_component_share"] - osm_conn_eval["largest_component_share"]
    if halo_vs_eval_gap is not None and halo_vs_eval_gap > 0.02:
        notes.append(
            f"OSM largest-component share drops by {halo_vs_eval_gap:.1%} when restricted to evaluation "
            f"scope vs. the acquisition-halo-scope graph -- most or all of this is the boundary-cut "
            f"artifact described in roads.topology.induced_subgraph_within_bbox, not necessarily true "
            f"fragmentation of the physical network."
        )

    return RoadAuditResult(
        osm_length_by_class_m=length_by_class(osm_road_gdf, "highway", eval_bbox),
        overture_length_by_class_m=length_by_class(overture_road_gdf, "class", eval_bbox),
        osm_connectivity_halo_scope=osm_conn_halo,
        overture_connectivity_halo_scope=overture_conn_halo,
        osm_intersection_count_halo_scope=osm_intersections_halo,
        overture_connector_intersection_count_halo_scope=overture_intersections_halo,
        osm_connectivity_eval_scope=osm_conn_eval,
        overture_connectivity_eval_scope=overture_conn_eval,
        osm_intersection_count_eval_scope=osm_intersections_eval,
        overture_connector_intersection_count_eval_scope=overture_intersections_eval,
        matched_length=matched,
        unmatched_major_osm_sample=osm_unmatched_major,
        unmatched_major_overture_sample=overture_unmatched_major,
        feature_impact_notes=notes,
    )
