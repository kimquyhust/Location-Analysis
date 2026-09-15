"""Parse AOI Overture Transportation segment/connector GeoParquet into a
driveable-road GeoDataFrame and a connector-topology graph, using the SAME
road-class acceptance rules as OSM (config/features.yaml `road_classes`) --
Overture's `class` values are observed (empirically, for this AOI) to use
the same vocabulary as OSM `highway=*` values, so `classify_highway` is
reused as-is rather than duplicated.

Never combined with the OSM graph -- this module only ever powers the
Overture side of a side-by-side comparison in src/audit/road_audit.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import geopandas as gpd
import networkx as nx

from ..poi.road_classes import classify_highway, load_road_classes

WGS84 = "EPSG:4326"


@dataclass
class OvertureRoadExtract:
    road_gdf: gpd.GeoDataFrame
    connector_gdf: gpd.GeoDataFrame
    road_graph: nx.MultiGraph
    non_road_subtype_count: int
    stats: dict = field(default_factory=dict)


def load_overture_roads(
    segments_path: Path,
    connectors_path: Path,
    features_path: Path = Path("config/features.yaml"),
) -> OvertureRoadExtract:
    road_classes = load_road_classes(features_path)

    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")

    seg_df = con.execute(f"""
        SELECT id, subtype, class, connectors, ST_AsText(geometry) AS wkt
        FROM read_parquet('{segments_path}')
    """).fetchdf()
    conn_df = con.execute(f"""
        SELECT id, ST_X(geometry) AS lon, ST_Y(geometry) AS lat
        FROM read_parquet('{connectors_path}')
    """).fetchdf()
    con.close()

    non_road_count = int((seg_df["subtype"] != "road").sum())
    road_df = seg_df[seg_df["subtype"] == "road"].copy()

    def _accept(cls):
        if cls is None:
            return (False, False)
        is_driveable, is_major, _ = classify_highway(cls, road_classes)
        return is_driveable, is_major

    accepted = road_df["class"].apply(_accept)
    road_df["is_driveable"] = accepted.apply(lambda t: t[0])
    road_df["is_major"] = accepted.apply(lambda t: t[1])
    road_df = road_df[road_df["is_driveable"]].copy()

    import shapely.wkt as swkt
    road_df["geometry"] = road_df["wkt"].apply(swkt.loads)
    road_gdf = gpd.GeoDataFrame(
        road_df[["id", "class", "is_major", "geometry"]], geometry="geometry", crs=WGS84
    )

    connector_gdf = gpd.GeoDataFrame(
        conn_df[["id"]],
        geometry=gpd.points_from_xy(conn_df["lon"], conn_df["lat"]),
        crs=WGS84,
    )

    graph = nx.MultiGraph()
    for _, row in road_df.iterrows():
        connectors = row["connectors"]
        if connectors is None or len(connectors) < 2:
            continue
        ordered = sorted(connectors, key=lambda c: c["at"])
        ids = [c["connector_id"] for c in ordered]
        for a, b in zip(ids[:-1], ids[1:]):
            graph.add_edge(a, b, segment_id=row["id"], road_class=row["class"], is_major=row["is_major"])

    return OvertureRoadExtract(
        road_gdf=road_gdf,
        connector_gdf=connector_gdf,
        road_graph=graph,
        non_road_subtype_count=non_road_count,
        stats={
            "driveable_segment_count": len(road_gdf),
            "non_road_subtype_count": non_road_count,
            "connector_count": len(connector_gdf),
            "graph_node_count": graph.number_of_nodes(),
        },
    )
