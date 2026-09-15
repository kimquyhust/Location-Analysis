"""Cross-GEOMETRY-TYPE deduplication for OSM POIs, per
`config/poi_taxonomy.yaml` `entity_policy.cross_geometry_deduplication`.

A POI is sometimes mapped twice in OSM -- once as a node and once as the
way/area it sits inside (e.g. a hospital node inside a hospital-tagged
building polygon). This collapses same-category POINT+POLYGON pairs within
`max_distance_m` of each other, where the entities share a normalized name
OR a normalized `brand` tag, into one canonical record (keeping the polygon
geometry, which is more precise than a point).

Two entities of the SAME geometry kind (node+node, or way/polygon+way/
polygon) are NEVER merged by this function, even if same category, same
name, and close together -- per config, cross-geometry dedup is about one
real place being mapped twice with two different representations, not
about two nearby businesses that happen to share a generic/franchise name
(two different WinMart branches 50m apart are two real stores, not a
duplicate). No separate same-geometry proximity-dedup policy is configured
anywhere in this project, so same-geometry nearby records are preserved
here, per the review's explicit instruction.

Clustering is transitive (via union-find over point<->polygon edges only)
and deterministic (fixed sort order for cluster/keeper selection).
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

import geopandas as gpd
import pandas as pd
from shapely import STRtree

DEFAULT_MAX_DISTANCE_M = 75.0  # config/poi_taxonomy.yaml entity_policy.cross_geometry_deduplication.maximum_representative_point_distance_m


def normalize_name(name) -> str | None:
    if name is None or (isinstance(name, float)):
        return None
    text = str(name).strip().lower()
    if not text:
        return None
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return text or None


def _extract_brand(raw_tags) -> str | None:
    if not isinstance(raw_tags, dict):
        return None
    return normalize_name(raw_tags.get("brand"))


class _UnionFind:
    def __init__(self, items):
        self.parent = {x: x for x in items}

    def find(self, x):
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        # Deterministic: always attach the numerically-larger root under
        # the smaller one, independent of call order.
        if ra < rb:
            self.parent[rb] = ra
        else:
            self.parent[ra] = rb


def deduplicate_osm_pois(
    poi_gdf: gpd.GeoDataFrame,
    max_distance_m: float = DEFAULT_MAX_DISTANCE_M,
    metric_crs: str = "EPSG:32649",
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Returns (deduplicated_gdf, duplicate_records_gdf). `duplicate_records_gdf`
    has one row per DROPPED record (not per pair), each naming which kept
    record it was merged into -- duplicates are never silently discarded,
    only flagged and collapsed."""
    if len(poi_gdf) == 0:
        return poi_gdf, poi_gdf.iloc[0:0]

    working = poi_gdf.copy()
    working["_norm_name"] = working["name"].apply(normalize_name)
    working["_norm_brand"] = working["raw_tags"].apply(_extract_brand) if "raw_tags" in working.columns else None
    working["_metric_geom"] = working.to_crs(metric_crs).geometry
    working["_is_point"] = working.geometry.geom_type == "Point"

    uf = _UnionFind(working.index.tolist())

    for category, group in working.groupby("category", sort=True):
        named = group[group["_norm_name"].notna() | group["_norm_brand"].notna()]
        points = named[named["_is_point"]]
        polys = named[~named["_is_point"]]
        if len(points) == 0 or len(polys) == 0:
            continue

        poly_geoms = polys["_metric_geom"].values
        poly_labels = polys.index.values
        tree = STRtree(poly_geoms)

        for p_idx, prow in points.iterrows():
            nearby = tree.query(prow["_metric_geom"], predicate="dwithin", distance=max_distance_m)
            for j in nearby:
                poly_label = poly_labels[j]
                poly_row = polys.loc[poly_label]
                same_name = prow["_norm_name"] is not None and prow["_norm_name"] == poly_row["_norm_name"]
                same_brand = prow["_norm_brand"] is not None and prow["_norm_brand"] == poly_row["_norm_brand"]
                if same_name or same_brand:
                    uf.union(p_idx, poly_label)

    clusters = defaultdict(list)
    for idx in working.index:
        clusters[uf.find(idx)].append(idx)

    keep_mask = pd.Series(True, index=poi_gdf.index)
    duplicate_records = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        members_sorted = sorted(members)  # deterministic
        member_rows = poi_gdf.loc[members_sorted]
        polys_in_cluster = member_rows[member_rows.geometry.geom_type != "Point"]
        keeper_pool = polys_in_cluster if len(polys_in_cluster) else member_rows
        keeper = keeper_pool.sort_values("osm_id").index[0]
        for m in members_sorted:
            if m != keeper:
                keep_mask.loc[m] = False
                duplicate_records.append({
                    "kept_osm_type": poi_gdf.loc[keeper, "osm_type"],
                    "kept_osm_id": poi_gdf.loc[keeper, "osm_id"],
                    "dropped_osm_type": poi_gdf.loc[m, "osm_type"],
                    "dropped_osm_id": poi_gdf.loc[m, "osm_id"],
                    "category": poi_gdf.loc[m, "category"],
                    "geometry": poi_gdf.loc[m, "geometry"],
                })

    deduped = poi_gdf[keep_mask].copy()
    dup_gdf = gpd.GeoDataFrame(duplicate_records, geometry="geometry", crs=poi_gdf.crs) if duplicate_records else gpd.GeoDataFrame(
        columns=["kept_osm_type", "kept_osm_id", "dropped_osm_type", "dropped_osm_id", "category", "geometry"],
        geometry="geometry", crs=poi_gdf.crs,
    )
    return deduped, dup_gdf
