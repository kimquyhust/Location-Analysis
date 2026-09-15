"""POI, park and industrial-site features per unit, from canonical OSM
entities (`config/poi_taxonomy.yaml`) after cross-geometry deduplication.

Contract points implemented here (docs/feature_dictionary.md):

- a canonical entity is counted when its point, or its polygon's
  `point_on_surface`, lies within the buffer around the unit's
  representative point; raw OSM elements are never counted;
- distances are measured from the representative point to the ORIGINAL
  geometry (a polygon's edge, not its centroid);
- rollups (`transit_stop`, `transport_hub`, `retail`) come from
  `config/features.yaml` and are disjoint by construction because every
  entity has exactly one leaf category -- an entity contributes once to
  `poi_total_count_1km` and once to at most one leaf in richness;
- industrial-site area is the intersection of the ORIGINAL `landuse=
  industrial` polygons (unioned first so overlapping polygons cannot be
  double-counted) with the unit footprint.

Search completeness: the OSM source is a halo clip, so a nearest-entity
search is only complete out to the point's distance from the halo edge.
`distance_with_status` returns `ok` only when the nearest entity is closer
than both the cap and that radius; otherwise the value is null with a
status that names why (`not_found_within_cap` when the search really was
complete out to the cap, `search_truncated_by_extract` when it was not).
"""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely import STRtree
from shapely.ops import unary_union

OK = "ok"
NOT_FOUND = "not_found_within_cap"
TRUNCATED = "search_truncated_by_extract"


@dataclass
class CanonicalPois:
    """Deduplicated canonical entities in the AOI metric CRS."""
    frame: gpd.GeoDataFrame          # original geometry, columns: osm_type, osm_id, category, raw_tags
    count_points: np.ndarray         # point_on_surface per entity (shapely Points)
    categories: np.ndarray           # leaf category per entity
    duplicates_dropped: int


def canonical_pois(poi_metric: gpd.GeoDataFrame, duplicates_dropped: int) -> CanonicalPois:
    if len(poi_metric):
        count_points = poi_metric.geometry.representative_point().to_numpy()
        cats = poi_metric["category"].to_numpy()
    else:
        count_points, cats = np.array([], dtype=object), np.array([], dtype=object)
    return CanonicalPois(poi_metric, count_points, cats, duplicates_dropped)


# --- counts ----------------------------------------------------------------

def counts_within(rep_points: np.ndarray, count_points: np.ndarray, categories: np.ndarray,
                  radius_m: float, wanted: list[str]) -> np.ndarray:
    """Number of entities whose category is in `wanted` within `radius_m`
    of each representative point. Each entity is matched to a point at most
    once per query, so an entity never counts twice in one feature."""
    n = len(rep_points)
    out = np.zeros(n, dtype="int64")
    if not n or not len(count_points):
        return out
    sel = np.isin(categories, wanted)
    if not sel.any():
        return out
    tree = STRtree(count_points[sel])
    pt_idx, _ = tree.query(rep_points, predicate="dwithin", distance=radius_m)
    np.add.at(out, pt_idx, 1)
    return out


def richness_within(rep_points: np.ndarray, count_points: np.ndarray, categories: np.ndarray,
                    radius_m: float, enabled: list[str]) -> np.ndarray:
    """Number of enabled leaf categories with at least one entity within
    `radius_m`."""
    n = len(rep_points)
    out = np.zeros(n, dtype="int64")
    if not n or not len(count_points):
        return out
    tree = STRtree(count_points)
    pt_idx, ent_idx = tree.query(rep_points, predicate="dwithin", distance=radius_m)
    if not len(pt_idx):
        return out
    cats = categories[ent_idx]
    keep = np.isin(cats, enabled)
    pairs = pd.DataFrame({"pt": pt_idx[keep], "cat": cats[keep]}).drop_duplicates()
    counts = pairs.groupby("pt").size()
    out[counts.index.to_numpy()] = counts.to_numpy()
    return out


# --- distances -------------------------------------------------------------

def nearest_distance(rep_points: np.ndarray, targets: np.ndarray) -> np.ndarray:
    n = len(rep_points)
    if not n or not len(targets):
        return np.full(n, np.nan)
    tree = STRtree(targets)
    idx = tree.nearest(rep_points)
    return shapely.distance(rep_points, targets[idx])


def distance_with_status(distances: np.ndarray, cap_m: float, complete_radius_m: np.ndarray
                         ) -> tuple[np.ndarray, np.ndarray]:
    """Apply the search cap and the extract-completeness radius.

    ok                          nearest found, d <= cap and d <= complete radius
    not_found_within_cap        search complete to the cap, nothing within it
    search_truncated_by_extract nothing found (or found only beyond the
                                complete radius) and the extract does not
                                reach the cap -- the true nearest may be
                                outside the clipped source
    The value is null unless the status is ok; the cap is never returned.
    """
    d = np.asarray(distances, dtype="float64")
    cr = np.asarray(complete_radius_m, dtype="float64")
    found = np.isfinite(d)
    ok = found & (d <= cap_m) & (d <= cr)
    complete_to_cap = cr >= cap_m
    status = np.where(ok, OK, np.where(complete_to_cap, NOT_FOUND, TRUNCATED)).astype(object)
    value = np.where(ok, d, np.nan)
    return value, status


def complete_search_radius(rep_points: np.ndarray, halo_polygon_metric) -> np.ndarray:
    """Distance from each point to the halo boundary: the radius within
    which the clipped source is guaranteed complete."""
    boundary = halo_polygon_metric.exterior
    return shapely.distance(rep_points, boundary)


# --- areal -----------------------------------------------------------------

def intersection_area_per_unit(units_metric: gpd.GeoDataFrame, polygons: gpd.GeoDataFrame) -> np.ndarray:
    """Area of the union of `polygons` inside each unit footprint. The union
    is taken first so overlapping mapped polygons cannot exceed the unit."""
    n = len(units_metric)
    out = np.zeros(n, dtype="float64")
    if not n or not len(polygons):
        return out
    merged = unary_union(polygons.geometry.to_numpy())
    if merged.is_empty:
        return out
    parts = np.array(list(merged.geoms) if hasattr(merged, "geoms") else [merged], dtype=object)
    tree = STRtree(parts)
    unit_geoms = units_metric.geometry.to_numpy()
    unit_idx, part_idx = tree.query(unit_geoms, predicate="intersects")
    if not len(unit_idx):
        return out
    inter = shapely.intersection(unit_geoms[unit_idx], parts[part_idx])
    np.add.at(out, unit_idx, shapely.area(inter))
    return out


def park_geometries(area_metric: gpd.GeoDataFrame, poi_metric: gpd.GeoDataFrame) -> np.ndarray:
    """OSM park polygons (`park_area`, leisure=park) plus `park_recreation`
    entities whose tag is leisure=park (points or polygons not captured as
    areas), each OSM element once."""
    seen: set[tuple] = set()
    geoms: list = []
    if len(area_metric):
        for row in area_metric[area_metric["area_category"] == "park_area"].itertuples():
            key = (row.osm_type, row.osm_id)
            if key not in seen:
                seen.add(key); geoms.append(row.geometry)
    if len(poi_metric):
        sub = poi_metric[poi_metric["category"] == "park_recreation"]
        for row in sub.itertuples():
            tags = row.raw_tags if isinstance(row.raw_tags, dict) else {}
            if tags.get("leisure") != "park":
                continue
            key = (row.osm_type, row.osm_id)
            if key not in seen:
                seen.add(key); geoms.append(row.geometry)
    return np.array(geoms, dtype=object)
