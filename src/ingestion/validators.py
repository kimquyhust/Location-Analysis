"""Validation checks for acquired/derived assets: raster CRS/bounds/NoData,
OSM PBF structural validity. Every function raises a `ValidationError` on
failure -- callers are expected to let that propagate (fail loudly) rather
than catch-and-continue.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

import rasterio


class ValidationError(RuntimeError):
    pass


def validate_raster(
    path: Path,
    expected_crs: Optional[str] = None,
    expected_nodata: Optional[float] = None,
    nodata_tol: float = 1e-6,
    require_finite_bounds: bool = True,
) -> dict:
    """Opens `path` with rasterio and checks CRS/NoData against expected
    values (when given). Returns a dict of observed metadata for the
    manifest. Raises ValidationError on any mismatch or unreadable file.
    """
    try:
        with rasterio.open(path) as src:
            crs = src.crs.to_string() if src.crs else None
            nodata = src.nodata
            bounds = tuple(src.bounds)
            width, height = src.width, src.height
            band_count = src.count
    except Exception as e:
        raise ValidationError(f"{path}: could not open as a raster: {e}") from e

    if expected_crs is not None and crs != expected_crs:
        raise ValidationError(f"{path}: CRS {crs!r} != expected {expected_crs!r}")
    if expected_nodata is not None:
        if nodata is None or abs(nodata - expected_nodata) > nodata_tol:
            raise ValidationError(f"{path}: NoData {nodata!r} != expected {expected_nodata!r}")
    if require_finite_bounds and not all(map(_is_finite, bounds)):
        raise ValidationError(f"{path}: non-finite bounds {bounds}")
    if width <= 0 or height <= 0:
        raise ValidationError(f"{path}: non-positive raster dimensions {width}x{height}")

    return {"crs": crs, "nodata": nodata, "bounds": list(bounds), "width": width, "height": height, "band_count": band_count}


def _is_finite(x: float) -> bool:
    return x == x and x not in (float("inf"), float("-inf"))


def validate_osm_pbf(path: Path, min_nodes: int = 1, min_ways: int = 1) -> dict:
    """Runs `osmium fileinfo -e -f json` and checks the file parses and
    contains at least `min_nodes` nodes and `min_ways` ways -- catches a
    truncated/corrupt download or an AOI extract that came back empty.
    """
    try:
        result = subprocess.run(
            ["osmium", "fileinfo", "-e", "-j", str(path)],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError as e:
        raise ValidationError(f"{path}: `osmium fileinfo` failed: {e.stderr}") from e
    except FileNotFoundError as e:
        raise ValidationError("osmium is not installed -- cannot validate PBF structure") from e

    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise ValidationError(f"{path}: could not parse `osmium fileinfo` JSON output: {e}") from e

    data = info.get("data", {})
    node_count = data.get("count", {}).get("nodes", 0)
    way_count = data.get("count", {}).get("ways", 0)
    if node_count < min_nodes:
        raise ValidationError(f"{path}: only {node_count} nodes (< {min_nodes} required) -- likely empty/corrupt extract")
    if way_count < min_ways:
        raise ValidationError(f"{path}: only {way_count} ways (< {min_ways} required) -- likely empty/corrupt extract")

    return {
        "node_count": node_count, "way_count": way_count,
        "relation_count": data.get("count", {}).get("relations", 0),
        "bbox": data.get("bbox"),
        "timestamp_last": data.get("timestamp", {}).get("last"),
    }
