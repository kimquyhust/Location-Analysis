"""Shared bbox-clip helper for the POI and road audits."""

from __future__ import annotations

import geopandas as gpd
import shapely.geometry as sgeom


def clip_to_bbox(gdf: gpd.GeoDataFrame, bbox: tuple) -> gpd.GeoDataFrame:
    """`bbox`: (west, south, east, north) in the same CRS as `gdf`. Returns
    geometries clipped (not just filtered) to the box -- a line straddling
    the boundary is cut at the boundary, so length sums reflect only the
    portion actually inside `bbox`."""
    if len(gdf) == 0:
        return gdf
    west, south, east, north = bbox
    return gpd.clip(gdf, sgeom.box(west, south, east, north))
