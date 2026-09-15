"""Shared connectivity metrics for a road graph (OSM shared-node topology
or Overture connector topology): connected components and a length-weighted
largest-component share, plus intersection-node extraction by minimum
degree. Deliberately source-agnostic -- both src/poi/osm_extract.py and
src/roads/overture_transportation.py build a networkx graph and hand it
here rather than duplicating this logic per source.
"""

from __future__ import annotations

from typing import Optional

import networkx as nx
from pyproj import Transformer

WGS84 = "EPSG:4326"


def project_node_locations(node_location: dict, target_crs: str = "EPSG:32649") -> dict:
    """`node_location`: {node_id: (lon, lat)}. Returns {node_id: (x, y)} in
    `target_crs` (default EPSG:32649, WGS84 / UTM zone 49N, per
    COWORK_START_PROMPT.md's metric CRS for this AOI)."""
    transformer = Transformer.from_crs(WGS84, target_crs, always_xy=True)
    out = {}
    for node_id, (lon, lat) in node_location.items():
        x, y = transformer.transform(lon, lat)
        out[node_id] = (x, y)
    return out


def intersection_nodes(G: nx.Graph, minimum_degree: int) -> list:
    degree = dict(G.degree())
    return [n for n, d in degree.items() if d >= minimum_degree]


def induced_subgraph_within_bbox(G: nx.Graph, node_location: dict, bbox: tuple) -> tuple:
    """Restrict `G` to the nodes whose (lon, lat) in `node_location` falls
    inside `bbox` (west, south, east, north), plus only the edges where
    BOTH endpoints are in-scope.

    This is the explicit, documented rule for "boundary nodes": a node on
    or outside the AOI edge is simply out of scope, and any edge that
    would cross the boundary is dropped entirely rather than partially
    counted -- so an edge is never attributed to one side of a cut we
    cannot geometrically clip at the graph level. This necessarily makes
    the evaluation-scope graph look *more* fragmented than the true
    physical network (a road that continues into the halo and reconnects
    two "components" there will show as two components here) -- that is a
    known, named artifact of the cut, not evidence the real network is
    fragmented. Compare against the acquisition-halo-scope numbers
    (the unrestricted graph) to see the effect.
    """
    west, south, east, north = bbox
    in_scope_nodes = {
        n for n in G.nodes()
        if n in node_location and west <= node_location[n][0] <= east and south <= node_location[n][1] <= north
    }
    sub = G.subgraph(in_scope_nodes).copy()
    in_scope_xy = {n: node_location[n] for n in in_scope_nodes}
    return sub, in_scope_xy


def component_length_shares(G: nx.Graph, node_xy: dict, top_n: int = 10) -> dict:
    """Connected components of `G`, sized by total projected edge length
    (not just node/edge count), since length is the metric that matters
    for `road_length`/`road_density` impact assessment."""
    components = list(nx.connected_components(G))
    comp_lengths = []
    for comp in components:
        sub = G.subgraph(comp)
        length = 0.0
        for a, b in sub.edges():
            if a not in node_xy or b not in node_xy:
                continue
            ax, ay = node_xy[a]
            bx, by = node_xy[b]
            length += ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
        comp_lengths.append(length)

    total = sum(comp_lengths)
    largest = max(comp_lengths) if comp_lengths else 0.0
    comp_lengths_sorted = sorted(comp_lengths, reverse=True)
    return {
        "component_count": len(components),
        "total_length_m": total,
        "largest_component_length_m": largest,
        "largest_component_share": (largest / total) if total > 0 else None,
        "top_component_lengths_m": comp_lengths_sorted[:top_n],
    }
