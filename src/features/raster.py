"""Area-weighted raster aggregation over unit footprints.

Every pixel contributes to a unit by the FRACTION of the pixel's area that
lies inside the unit polygon (exact polygon-pixel intersection on boundary
pixels, 1.0 for interior pixels). This is what makes a sum over units that
tile a region equal the sum over the pixels of that region -- population
is conserved by construction, and a boundary pixel is split between the
cells it straddles instead of being handed whole to whichever cell holds
its centre.

The raster is never resampled or reprojected: the unit polygon is
reprojected INTO the raster's CRS and the pixel grid is read as-is. Area
fractions are computed in the raster CRS (a ratio, so the projection's
scale factor cancels within a pixel); absolute areas in m^2 are then
`fraction_of_unit x unit_area_m2` with the unit's actual metric area, so
no degree-squared quantity is ever reported as an area.

Coverage is measured, not assumed: `covered_fraction` is the share of the
unit's area under pixels the publisher marked valid (or, when asked, under
any pixel of the window), computed from the same intersection areas. A
unit that falls partly outside the raster window, or over NoData, shows it
here rather than appearing as a smaller value.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
import shapely
from rasterio.transform import rowcol
from shapely.geometry.base import BaseGeometry


@dataclass
class PixelWeights:
    rows: np.ndarray            # pixel row indices (within the raster)
    cols: np.ndarray            # pixel col indices
    fraction: np.ndarray        # fraction of each pixel's area inside the unit (0, 1]
    pixel_area: float           # one pixel's area in raster-CRS units
    unit_area: float            # unit polygon area in raster-CRS units
    window_fraction: float      # share of the unit lying inside the raster window

    @property
    def covered_area(self) -> float:
        return float(self.fraction.sum() * self.pixel_area)


def pixel_weights(geom: BaseGeometry, transform, shape: tuple[int, int]) -> PixelWeights:
    """Exact area fractions of every pixel that intersects `geom` (already
    in the raster CRS). Pixels outside the raster window are not returned;
    their absence shows up as `window_fraction < 1`."""
    height, width = shape
    unit_area = float(geom.area)
    a, e = transform.a, transform.e  # pixel width (>0) and height (<0)
    pixel_area = abs(a * e)
    if geom.is_empty or unit_area <= 0:
        return PixelWeights(np.array([], dtype="int64"), np.array([], dtype="int64"),
                            np.array([], dtype="float64"), pixel_area, unit_area, 0.0)

    minx, miny, maxx, maxy = geom.bounds
    r0, c0 = rowcol(transform, minx, maxy)
    r1, c1 = rowcol(transform, maxx, miny)
    r0, r1 = max(0, min(r0, r1)), min(height - 1, max(r0, r1))
    c0, c1 = max(0, min(c0, c1)), min(width - 1, max(c0, c1))
    if r1 < r0 or c1 < c0:
        return PixelWeights(np.array([], dtype="int64"), np.array([], dtype="int64"),
                            np.array([], dtype="float64"), pixel_area, unit_area, 0.0)

    rr, cc = np.meshgrid(np.arange(r0, r1 + 1), np.arange(c0, c1 + 1), indexing="ij")
    rr, cc = rr.ravel(), cc.ravel()
    x0 = transform.c + cc * a
    y1 = transform.f + rr * e          # top edge (e < 0 so y1 is the larger y)
    boxes = shapely.box(x0, y1 + e, x0 + a, y1)

    if not shapely.is_prepared(geom):
        shapely.prepare(geom)  # in place; contains/intersects use it automatically
    inside = shapely.contains_properly(geom, boxes)
    touches = shapely.intersects(geom, boxes) & ~inside
    fraction = np.zeros(len(boxes), dtype="float64")
    fraction[inside] = 1.0
    if touches.any():
        inter = shapely.intersection(geom, boxes[touches])
        fraction[touches] = shapely.area(inter) / pixel_area
    keep = fraction > 0
    rows, cols, fraction = rr[keep], cc[keep], fraction[keep]
    window_fraction = float(fraction.sum() * pixel_area / unit_area) if unit_area > 0 else 0.0
    # Float noise can put this a hair above 1 for a unit fully inside.
    window_fraction = min(window_fraction, 1.0 + 1e-9)
    return PixelWeights(rows, cols, fraction, pixel_area, unit_area, window_fraction)


@dataclass
class RasterBand:
    path: Path
    array: np.ndarray
    transform: object
    crs: str
    nodata: Optional[float]

    @property
    def shape(self) -> tuple[int, int]:
        return self.array.shape


def open_band(path: Path) -> RasterBand:
    with rasterio.open(path) as src:
        return RasterBand(path=Path(path), array=src.read(1), transform=src.transform,
                          crs=src.crs.to_string(), nodata=src.nodata)


def valid_mask(band: RasterBand, extra_nodata: Optional[float] = None) -> np.ndarray:
    arr = band.array
    ok = np.isfinite(arr.astype("float64"))
    if band.nodata is not None:
        ok &= arr != band.nodata
    if extra_nodata is not None:
        ok &= arr != extra_nodata
    return ok


def weighted_sum(band: RasterBand, w: PixelWeights, valid: np.ndarray) -> tuple[float, float, float]:
    """(sum of value x fraction over VALID pixels, valid covered fraction of
    the unit, NoData covered fraction of the unit)."""
    if not len(w.rows):
        return 0.0, 0.0, 0.0
    v = valid[w.rows, w.cols]
    vals = band.array[w.rows, w.cols].astype("float64")
    total = float((vals[v] * w.fraction[v]).sum())
    valid_frac = float((w.fraction[v]).sum() * w.pixel_area / w.unit_area)
    nodata_frac = float((w.fraction[~v]).sum() * w.pixel_area / w.unit_area)
    return total, valid_frac, nodata_frac


def class_area_fractions(band: RasterBand, w: PixelWeights, nodata_class: int
                         ) -> tuple[dict[int, float], float]:
    """Fraction of the UNIT's area under each class code (valid classes
    only), plus the total valid fraction. Fractions of the unit, not of the
    valid area, so the caller chooses the denominator explicitly."""
    if not len(w.rows):
        return {}, 0.0
    codes = band.array[w.rows, w.cols]
    out: dict[int, float] = {}
    scale = w.pixel_area / w.unit_area
    for code in np.unique(codes):
        if int(code) == nodata_class:
            continue
        out[int(code)] = float(w.fraction[codes == code].sum() * scale)
    return out, float(sum(out.values()))
