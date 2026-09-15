"""Gate 2 areas of interest: deterministic geometry, per-AOI metric CRS,
and persisted GeoJSON + checksum.

An AOI is defined in `config/spatial.yaml` by a centre lat/lon and a
width/height in kilometres. The rectangle is built in the AOI's own metric
CRS so the stated dimensions are exact on the ground, then stored in
EPSG:4326. Centres and dimensions come from the config and are never
adjusted here -- `aoi_checksum` makes any change visible.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml
from shapely.geometry import Polygon, mapping
from shapely.ops import transform as shapely_transform

DEFAULT_SPATIAL_CONFIG = Path("config/spatial.yaml")


def utm_epsg_from_longitude(lon: float, northern: bool = True) -> str:
    """WGS84 UTM zone for a longitude. Vietnam spans zones 48N and 49N."""
    zone = int((lon + 180.0) // 6.0) + 1
    if not 1 <= zone <= 60:
        raise ValueError(f"longitude {lon} is outside the UTM zone range")
    return f"EPSG:{(32600 if northern else 32700) + zone}"


@dataclass(frozen=True)
class Aoi:
    id: str
    context: str
    centre_lat: float
    centre_lon: float
    width_km: float
    height_km: float
    metric_crs: str
    polygon: Polygon  # EPSG:4326

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """(west, south, east, north) in EPSG:4326."""
        return self.polygon.bounds

    @property
    def area_km2_nominal(self) -> float:
        return self.width_km * self.height_km

    def geojson(self) -> dict:
        return {
            "type": "Feature",
            "geometry": mapping(self.polygon),
            "properties": {
                "aoi_id": self.id,
                "context": self.context,
                "centre_lat": self.centre_lat,
                "centre_lon": self.centre_lon,
                "width_km": self.width_km,
                "height_km": self.height_km,
                "metric_crs": self.metric_crs,
                "storage_crs": "EPSG:4326",
                "construction": (
                    "axis-aligned rectangle of width_km x height_km centred on "
                    "(centre_lat, centre_lon) in metric_crs, reprojected to EPSG:4326"
                ),
            },
        }


def _to_metric(lon: float, lat: float, metric_crs: str):
    from pyproj import Transformer

    return Transformer.from_crs("EPSG:4326", metric_crs, always_xy=True).transform(lon, lat)


def build_aoi(spec: dict, metric_crs: Optional[str] = None) -> Aoi:
    from pyproj import Transformer

    lat, lon = float(spec["lat"]), float(spec["lon"])
    crs = metric_crs or utm_epsg_from_longitude(lon)
    cx, cy = _to_metric(lon, lat, crs)
    half_w, half_h = float(spec["width_km"]) * 500.0, float(spec["height_km"]) * 500.0

    rect = Polygon([
        (cx - half_w, cy - half_h),
        (cx + half_w, cy - half_h),
        (cx + half_w, cy + half_h),
        (cx - half_w, cy + half_h),
    ])
    back = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
    polygon = shapely_transform(back, rect)

    return Aoi(
        id=spec["id"], context=spec["context"], centre_lat=lat, centre_lon=lon,
        width_km=float(spec["width_km"]), height_km=float(spec["height_km"]),
        metric_crs=crs, polygon=polygon,
    )


def load_aois(config_path: Path = DEFAULT_SPATIAL_CONFIG) -> list[Aoi]:
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return [build_aoi(spec) for spec in cfg["representative_aois"]]


def aoi_checksum(aoi: Aoi) -> str:
    """SHA-256 of the AOI's canonical GeoJSON. Any change to a centre,
    dimension, or metric CRS changes this value, so a silently-moved AOI
    cannot pass unnoticed between runs."""
    payload = json.dumps(aoi.geojson(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_aoi_geojson(aois: list[Aoi], out_path: Path) -> tuple[Path, str]:
    """Writes all AOIs as one FeatureCollection and returns (path, sha256)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fc = {
        "type": "FeatureCollection",
        "features": [dict(a.geojson(), properties=dict(a.geojson()["properties"], aoi_checksum=aoi_checksum(a))) for a in aois],
    }
    payload = json.dumps(fc, sort_keys=True, indent=2)
    out_path.write_text(payload)
    return out_path, hashlib.sha256(payload.encode("utf-8")).hexdigest()
