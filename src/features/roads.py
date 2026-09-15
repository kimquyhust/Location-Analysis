"""Road features per unit: clipped centreline length, major-road length,
shared-node intersection count, and distance to the nearest major road.

Inputs are the OSM canonical road graph as parsed by
`poi.osm_extract.parse_osm_aoi` (road classes and link policy from
`config/features.yaml`; intersections = shared OSM nodes with accepted-road
degree >= the configured minimum, never geometric crossings). Everything
here is measured in the AOI's metric CRS; lengths are clipped to the unit
footprint BEFORE summing, so a road crossing three cells is split between
them rather than credited to any one.
"""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import shapely
from shapely import STRtree


@dataclass
class RoadFeatures:
    road_length_m: np.ndarray
    major_road_length_m: np.ndarray
    intersection_count: np.ndarray


def clipped_length_per_unit(units_metric: gpd.GeoDataFrame, lines: gpd.GeoDataFrame) -> np.ndarray:
    """Sum of line length inside each unit polygon. Only STRtree-matched
    pairs are intersected, so this is O(matches), and every unit's total is
    the length of the geometric intersection -- never the whole way."""
    n = len(units_metric)
    out = np.zeros(n, dtype="float64")
    if not n or not len(lines):
        return out
    unit_geoms = units_metric.geometry.to_numpy()
    line_geoms = lines.geometry.to_numpy()
    tree = STRtree(line_geoms)
    unit_idx, line_idx = tree.query(unit_geoms, predicate="intersects")
    if not len(unit_idx):
        return out
    inter = shapely.intersection(line_geoms[line_idx], unit_geoms[unit_idx])
    np.add.at(out, unit_idx, shapely.length(inter))
    return out


def points_per_unit(units_metric: gpd.GeoDataFrame, points: gpd.GeoDataFrame) -> np.ndarray:
    """Count of points inside each unit (a point on a shared edge is
    counted once, for the first unit in order -- units are a partition, so
    this only matters for exact-edge coincidences)."""
    n = len(units_metric)
    out = np.zeros(n, dtype="int64")
    if not n or not len(points):
        return out
    tree = STRtree(units_metric.geometry.to_numpy())
    pt_idx, unit_idx = tree.query(points.geometry.to_numpy(), predicate="intersects")
    if not len(pt_idx):
        return out
    # keep the first unit per point
    order = np.lexsort((unit_idx, pt_idx))
    pt_idx, unit_idx = pt_idx[order], unit_idx[order]
    first = np.concatenate([[True], pt_idx[1:] != pt_idx[:-1]])
    np.add.at(out, unit_idx[first], 1)
    return out


def road_features(units_metric: gpd.GeoDataFrame, roads_metric: gpd.GeoDataFrame,
                  intersections_metric: gpd.GeoDataFrame) -> RoadFeatures:
    major = roads_metric[roads_metric["is_major"].astype(bool)] if len(roads_metric) else roads_metric
    return RoadFeatures(
        road_length_m=clipped_length_per_unit(units_metric, roads_metric),
        major_road_length_m=clipped_length_per_unit(units_metric, major),
        intersection_count=points_per_unit(units_metric, intersections_metric),
    )


def nearest_distance(rep_points: np.ndarray, targets: np.ndarray) -> np.ndarray:
    """Metric distance from each representative point to the nearest target
    geometry (original geometry: lines or polygons, never centroids). NaN
    when there are no targets at all."""
    n = len(rep_points)
    if not n or not len(targets):
        return np.full(n, np.nan)
    tree = STRtree(targets)
    idx = tree.nearest(rep_points)
    return shapely.distance(rep_points, targets[idx])
