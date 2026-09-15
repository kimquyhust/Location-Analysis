"""Gate 2 spatial-unit candidates: deterministic generation, stable IDs,
actual areas, neighbours, and lat/lon lookup.

Two families are implemented behind one interface so every metric treats
them identically and neither gets a structural convenience advantage:

- `SquareGrid`  -- axis-aligned cells on ONE national grid CRS with ONE
  documented origin, so a cell ID is stable and unique nationwide rather
  than per-AOI. Cells are half-open `[x0, x0 + size) x [y0, y0 + size)`,
  which makes a point on a shared edge resolve to exactly one cell.
- `H3Grid`      -- H3 v4 cells. H3's own `latlng_to_cell` is the lookup and
  its own tie behaviour on a shared edge is what gets measured; nothing is
  smoothed over on its behalf.

Nominal size is never used as area. Every unit's area is measured from its
actual geometry in the AOI's local metric CRS, because H3 cell area varies
with latitude and a square defined in one national CRS varies with distance
from that CRS's central meridian. Both effects are real and both are
reported rather than assumed away.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional, Protocol

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Polygon, box

WGS84 = "EPSG:4326"

# Process-wide transformer cache -- see SquareGrid._transformer.
_TRANSFORMER_CACHE: dict = {}


# ---------------------------------------------------------------------------

class Candidate(Protocol):
    """One spatial-unit candidate (e.g. `square_500m`, `h3_r9`)."""

    id: str
    family: str

    def units(self, aoi_polygon: Polygon, aoi_crs: str) -> gpd.GeoDataFrame: ...
    def lookup(self, lat: np.ndarray, lon: np.ndarray) -> np.ndarray: ...
    def neighbors(self, unit_ids: Iterable[str]) -> dict[str, list[str]]: ...
    def ring(self, unit_id: str, k: int) -> list[str]: ...


# ---------------------------------------------------------------------------
# Square grid on a national origin
# ---------------------------------------------------------------------------

@dataclass
class SquareGrid:
    """`size_m` cells on `national_crs`, indexed from `(origin_x, origin_y)`.

    `offset_fraction` shifts the origin by a fraction of a cell width and
    exists only for the origin-sensitivity replicates; the operational grid
    always uses (0, 0). A shifted grid gets a distinct `id` so a replicate
    can never be mistaken for the real candidate in an artifact.
    """

    size_m: float
    national_crs: str = "EPSG:3405"
    origin_x: float = 0.0
    origin_y: float = 0.0
    offset_fraction: tuple[float, float] = (0.0, 0.0)
    role: str = "operational"
    family: str = "square"

    @property
    def id(self) -> str:
        base = f"square_{self._size_label}"
        fx, fy = self.offset_fraction
        return base if (fx, fy) == (0.0, 0.0) else f"{base}_off{fx:g}x{fy:g}"

    @property
    def _size_label(self) -> str:
        return f"{int(self.size_m)}m" if float(self.size_m).is_integer() else f"{self.size_m:g}m"

    @property
    def _ox(self) -> float:
        return self.origin_x + self.offset_fraction[0] * self.size_m

    @property
    def _oy(self) -> float:
        return self.origin_y + self.offset_fraction[1] * self.size_m

    @property
    def nominal_area_km2(self) -> float:
        return (self.size_m / 1000.0) ** 2

    # -- identity ----------------------------------------------------------

    def cell_index(self, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Column/row indices in the national grid. `floor` implements the
        half-open convention: a coordinate exactly on a cell's lower/left
        edge belongs to that cell, and one on its upper/right edge belongs
        to the next cell along."""
        col = np.floor((np.asarray(x, dtype="float64") - self._ox) / self.size_m).astype("int64")
        row = np.floor((np.asarray(y, dtype="float64") - self._oy) / self.size_m).astype("int64")
        return col, row

    def unit_id(self, col: np.ndarray, row: np.ndarray) -> np.ndarray:
        prefix = f"{self.id}|"
        return np.char.add(prefix, np.char.add(
            np.asarray(col).astype(str), np.char.add("_", np.asarray(row).astype(str))))

    @staticmethod
    def parse_unit_id(unit_id: str) -> tuple[str, int, int]:
        candidate_id, _, index = unit_id.partition("|")
        col, _, row = index.partition("_")
        return candidate_id, int(col), int(row)

    def cell_polygon(self, col: int, row: int) -> Polygon:
        x0 = self._ox + col * self.size_m
        y0 = self._oy + row * self.size_m
        return box(x0, y0, x0 + self.size_m, y0 + self.size_m)

    # -- generation --------------------------------------------------------

    def units(self, aoi_polygon: Polygon, aoi_crs: str) -> gpd.GeoDataFrame:
        """Every cell whose geometry intersects the AOI, as EPSG:4326
        geometry with `area_m2` measured in the AOI's own metric CRS."""
        aoi_national = (
            gpd.GeoSeries([aoi_polygon], crs=WGS84).to_crs(self.national_crs).iloc[0]
        )
        minx, miny, maxx, maxy = aoi_national.bounds
        c0, r0 = (int(v) for v in (a.item() for a in self.cell_index(np.array([minx]), np.array([miny]))))
        c1, r1 = (int(v) for v in (a.item() for a in self.cell_index(np.array([maxx]), np.array([maxy]))))

        cols, rows = np.meshgrid(np.arange(c0, c1 + 1), np.arange(r0, r1 + 1))
        cols, rows = cols.ravel(), rows.ravel()
        x0 = self._ox + cols * self.size_m
        y0 = self._oy + rows * self.size_m
        geoms = [box(a, b, a + self.size_m, b + self.size_m) for a, b in zip(x0, y0)]

        gdf = gpd.GeoDataFrame(
            {"unit_id": self.unit_id(cols, rows), "col": cols, "row": rows},
            geometry=geoms, crs=self.national_crs,
        )
        gdf = gdf[gdf.intersects(aoi_national)].reset_index(drop=True)
        return _finalize_units(gdf, self.id, self.family, aoi_polygon, aoi_crs)

    # -- lookup / topology -------------------------------------------------

    def _transformer(self):
        """Cached WGS84 -> national-grid transformer.

        Building a `pyproj.Transformer` costs milliseconds; constructing one
        per call made single-query lookup measure pyproj setup rather than
        the grid, and would have charged every square candidate a ~13 ms
        per-query cost that is an artefact of this code, not a property of
        square grids.
        """
        from pyproj import Transformer

        key = (WGS84, self.national_crs)
        cached = _TRANSFORMER_CACHE.get(key)
        if cached is None:
            cached = Transformer.from_crs(*key, always_xy=True)
            _TRANSFORMER_CACHE[key] = cached
        return cached

    def lookup(self, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        x, y = self._transformer().transform(
            np.asarray(lon, dtype="float64"), np.asarray(lat, dtype="float64"))
        return self.unit_id(*self.cell_index(x, y))

    def ring(self, unit_id: str, k: int) -> list[str]:
        """Chebyshev disk of radius `k` -- the square analogue of H3's
        `grid_disk`: the cell plus everything within `k` steps including
        diagonals."""
        _, col, row = self.parse_unit_id(unit_id)
        cols = np.arange(col - k, col + k + 1)
        rows = np.arange(row - k, row + k + 1)
        cc, rr = np.meshgrid(cols, rows)
        return list(self.unit_id(cc.ravel(), rr.ravel()))

    def neighbors(self, unit_ids: Iterable[str]) -> dict[str, list[str]]:
        present = set(unit_ids)
        out = {}
        for uid in present:
            ring = [n for n in self.ring(uid, 1) if n != uid and n in present]
            out[uid] = sorted(ring)
        return out


# ---------------------------------------------------------------------------
# H3 v4
# ---------------------------------------------------------------------------

@dataclass
class H3Grid:
    resolution: int
    role: str = "operational"
    family: str = "h3"

    @property
    def id(self) -> str:
        return f"h3_r{self.resolution}"

    @property
    def nominal_area_km2(self) -> float:
        import h3

        return h3.average_hexagon_area(self.resolution, unit="km^2")

    def units(self, aoi_polygon: Polygon, aoi_crs: str) -> gpd.GeoDataFrame:
        """Every H3 cell whose geometry intersects the AOI.

        `h3shape_to_cells` returns centroid-contained cells only, which
        would drop edge cells that genuinely overlap the AOI and bias unit
        counts downward. Instead the AOI is buffered by one average edge
        length, converted to cells, and the result filtered by an actual
        geometric intersection test -- the same inclusion rule the square
        grid uses, so the two families are counted on identical terms.
        """
        import h3
        from shapely.geometry import Polygon as ShapelyPolygon

        edge_km = h3.average_hexagon_edge_length(self.resolution, unit="km")
        buffered = (
            gpd.GeoSeries([aoi_polygon], crs=WGS84)
            .to_crs(aoi_crs).buffer(edge_km * 2000.0).to_crs(WGS84).iloc[0]
        )
        shape = h3.geo_to_h3shape(buffered.__geo_interface__)
        cells = sorted(set(h3.h3shape_to_cells(shape, self.resolution)))

        geoms = [ShapelyPolygon([(lng, lat) for lat, lng in h3.cell_to_boundary(c)]) for c in cells]
        gdf = gpd.GeoDataFrame({"unit_id": cells}, geometry=geoms, crs=WGS84)
        gdf = gdf[gdf.intersects(aoi_polygon)].reset_index(drop=True)
        return _finalize_units(gdf, self.id, self.family, aoi_polygon, aoi_crs)

    def lookup(self, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        import h3

        lat = np.asarray(lat, dtype="float64")
        lon = np.asarray(lon, dtype="float64")
        return np.array([h3.latlng_to_cell(a, b, self.resolution) for a, b in zip(lat, lon)], dtype=object)

    def ring(self, unit_id: str, k: int) -> list[str]:
        import h3

        return list(h3.grid_disk(unit_id, k))

    def neighbors(self, unit_ids: Iterable[str]) -> dict[str, list[str]]:
        import h3

        present = set(unit_ids)
        return {uid: sorted(n for n in h3.grid_disk(uid, 1) if n != uid and n in present)
                for uid in present}


# ---------------------------------------------------------------------------

def _finalize_units(gdf: gpd.GeoDataFrame, candidate_id: str, family: str,
                    aoi_polygon: Polygon, aoi_crs: str) -> gpd.GeoDataFrame:
    """Store geometry in EPSG:4326; measure area and AOI overlap in the
    AOI's own metric CRS. Areas are ACTUAL polygon areas, never nominal."""
    gdf = gdf.to_crs(WGS84) if gdf.crs != WGS84 else gdf
    metric = gdf.to_crs(aoi_crs)
    aoi_metric = gpd.GeoSeries([aoi_polygon], crs=WGS84).to_crs(aoi_crs).iloc[0]

    gdf = gdf.copy()
    gdf["candidate_id"] = candidate_id
    gdf["family"] = family
    gdf["area_m2"] = metric.area.to_numpy()
    gdf["aoi_overlap_m2"] = metric.intersection(aoi_metric).area.to_numpy()
    gdf["aoi_overlap_fraction"] = gdf["aoi_overlap_m2"] / gdf["area_m2"]
    centroids_metric = metric.representative_point()
    centroids = gpd.GeoSeries(centroids_metric, crs=aoi_crs).to_crs(WGS84)
    gdf["rep_lon"] = centroids.x.to_numpy()
    gdf["rep_lat"] = centroids.y.to_numpy()
    return gdf.sort_values("unit_id").reset_index(drop=True)


def build_candidates(config: dict) -> list:
    """Every enabled candidate from `config/gate2.yaml`, in a stable order."""
    national = config["national_grid"]
    out: list = []
    for spec in config["candidates"]["square_m"]:
        out.append(SquareGrid(
            size_m=float(spec["size_m"]), national_crs=national["crs"],
            origin_x=float(national["origin_easting_m"]), origin_y=float(national["origin_northing_m"]),
            role=spec["role"],
        ))
    for res in config["candidates"]["h3_resolutions"]:
        out.append(H3Grid(resolution=int(res)))
    return sorted(out, key=lambda c: (c.family, c.nominal_area_km2))


def origin_shift_replicates(grid: SquareGrid, fractions: list) -> list:
    """Origin-shifted copies of a square grid, for the sensitivity test."""
    return [
        SquareGrid(size_m=grid.size_m, national_crs=grid.national_crs,
                   origin_x=grid.origin_x, origin_y=grid.origin_y,
                   offset_fraction=(float(fx), float(fy)), role=f"{grid.role}_origin_replicate")
        for fx, fy in fractions
    ]


def adjacent_pairs(candidates: list) -> list[tuple]:
    """(finer, coarser) pairs within each family, ordered by nominal area.
    MAUP stability is only meaningful between adjacent scales of the SAME
    family -- comparing a square to a hexagon confounds shape with scale."""
    pairs = []
    for family in sorted({c.family for c in candidates}):
        members = sorted([c for c in candidates if c.family == family],
                         key=lambda c: c.nominal_area_km2)
        # Area controls and operational sizes interleave; adjacency is by
        # measured nominal area within the family, which is the scale axis.
        pairs.extend(zip(members[:-1], members[1:]))
    return pairs
