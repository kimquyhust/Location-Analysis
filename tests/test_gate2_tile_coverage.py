"""Multi-tile selection and clip coverage for Gate 2 raster acquisition.

The invalidated run `run_20260914T091321Z` clipped one tile per AOI --
the tile under the halo CENTRE -- and gdal padded the rest of the window
with NoData. Two AOIs straddle a tile line (Hanoi's WorldCover halo crosses
21N; Mu Cang Chai's GHS-BUILT-S halo crosses the R7_C28/R7_C29 seam) and
were silently truncated. These tests pin the fix: tiles are chosen by halo
EXTENT, a halo that crosses a tile line demands every tile it touches, and
a clip served by too few tiles is an error rather than a NoData band.
"""

import shutil
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from ingestion import acquire_gate2 as G
from ingestion.acquire_gate2 import (NationalAsset, TileCoverageError, aoi_tiles, clip_raster,
                                     ghsl_tile_bounds, ghsl_tiles_for_bbox, halo_bbox,
                                     halo_bbox_in, validate_clip_coverage, window_inside_union,
                                     worldcover_tile_bounds, worldcover_tiles_for_bbox)
from ingestion.manifest import RunManifest
from spatial.aoi import load_aois

needs_gdal = pytest.mark.skipif(
    shutil.which("gdal_translate") is None or shutil.which("gdalbuildvrt") is None,
    reason="GDAL command-line tools not on PATH")


def _aoi(aoi_id: str):
    return next(a for a in load_aois() if a.id == aoi_id)


# --- tile selection by extent, on the real AOI definitions ---------------

def test_hanoi_worldcover_halo_crosses_21n_and_needs_both_tiles():
    wc, _ = aoi_tiles(_aoi("hanoi_core"))
    assert wc == {"N18E105", "N21E105"}
    w, s, e, n = halo_bbox(_aoi("hanoi_core"))
    assert s < 21.0 < n, "the halo straddles the tile line; that is why both tiles are needed"


def test_mu_cang_chai_builtup_halo_crosses_the_c28_c29_seam_and_needs_both_tiles():
    _, gh = aoi_tiles(_aoi("mu_cang_chai"))
    assert gh == {(7, 28), (7, 29)}
    xmin, _, xmax, _ = halo_bbox_in(_aoi("mu_cang_chai"), G.MOLLWEIDE)
    seam = ghsl_tile_bounds(7, 28)[2]
    assert xmin < seam < xmax


def test_the_other_mvp_aois_are_served_by_a_single_tile_each():
    for aoi_id in ("hoi_an", "dong_thap_rural"):
        wc, gh = aoi_tiles(_aoi(aoi_id))
        assert len(wc) == 1 and len(gh) == 1, aoi_id


def test_tile_selection_uses_the_extent_not_the_centre():
    """A window whose centre is in one tile but whose edge crosses into the
    next must list both. This is the exact defect of the invalidated run."""
    assert worldcover_tiles_for_bbox((105.5, 20.9, 105.9, 21.1)) == {"N18E105", "N21E105"}
    assert worldcover_tiles_for_bbox((105.5, 21.1, 105.9, 21.5)) == {"N21E105"}
    # A north edge exactly on the tile line does not pull in the tile above.
    assert worldcover_tiles_for_bbox((105.5, 20.5, 105.9, 21.0)) == {"N18E105"}
    # Crossing a longitude line as well gives four tiles.
    assert worldcover_tiles_for_bbox((104.9, 20.9, 105.1, 21.1)) == {
        "N18E102", "N18E105", "N21E102", "N21E105"}


def test_ghsl_tile_selection_by_extent_matches_the_tiling_scheme():
    xmin, ymin, xmax, ymax = ghsl_tile_bounds(7, 28)
    assert ghsl_tiles_for_bbox((xmin + 10, ymin + 10, xmax - 10, ymax - 10)) == {(7, 28)}
    assert ghsl_tiles_for_bbox((xmax - 10, ymin + 10, xmax + 10, ymax - 10)) == {(7, 28), (7, 29)}
    assert ghsl_tiles_for_bbox((xmin + 10, ymin - 10, xmax - 10, ymin + 10)) == {(7, 28), (8, 28)}
    # Consistent with the point rule used for the centre.
    assert G.ghsl_tile_id(105.852, 21.028) == (7, 29)


def test_tile_bounds_round_trip_their_ids():
    assert worldcover_tile_bounds("N18E105") == (105.0, 18.0, 108.0, 21.0)
    assert worldcover_tile_bounds("N21E102") == (102.0, 21.0, 105.0, 24.0)
    r, c = 7, 29
    xmin, ymin, xmax, ymax = ghsl_tile_bounds(r, c)
    assert G._ghsl_tile_for_xy(xmin + 1, ymax - 1) == (r, c)
    assert G._ghsl_tile_for_xy(xmax - 1, ymin + 1) == (r, c)


# --- window containment ----------------------------------------------------

def test_window_inside_union_requires_every_tile():
    a = (105.0, 18.0, 108.0, 21.0)
    b = (105.0, 21.0, 108.0, 24.0)
    window = (105.7891, 20.9689, 105.915, 21.0871)
    assert window_inside_union(window, [a, b])
    assert not window_inside_union(window, [b]), "the tile under the centre alone is not enough"
    assert not window_inside_union(window, [a])
    assert not window_inside_union(window, [])


# --- clip behaviour on synthetic tiles --------------------------------------

def _write_tile(path: Path, west: float, north: float, size: int, res: float, value: int,
                nodata: int = 0) -> NationalAsset:
    arr = np.full((size, size), value, dtype="uint8")
    with rasterio.open(path, "w", driver="GTiff", width=size, height=size, count=1, dtype="uint8",
                       crs="EPSG:4326", transform=from_origin(west, north, res, res),
                       nodata=nodata) as dst:
        dst.write(arr, 1)
    with rasterio.open(path) as src:
        bounds = list(src.bounds)
    return NationalAsset(
        source_id=path.stem, path=path, provider="test", product="synthetic tile", release="t",
        license_id="CC-BY-4.0", url="synthetic", retrieved_at_utc="2026-01-01T00:00:00+00:00",
        retrieved_at_utc_method="download", sha256=f"{hash(path.stem) & 0xffffffff:064x}",
        bytes=path.stat().st_size,
        validation={"crs": "EPSG:4326", "nodata": float(nodata), "bounds": bounds,
                    "width": size, "height": size, "band_count": 1},
    )


@pytest.fixture
def two_tiles(tmp_path):
    """Two 3-degree tiles stacked at 21N, coarse (0.01 deg) so tests are fast.
    Class 10 south of the line, class 20 north of it."""
    south = _write_tile(tmp_path / "S.tif", west=105.0, north=21.0, size=300, res=0.01, value=10)
    north = _write_tile(tmp_path / "N.tif", west=105.0, north=24.0, size=300, res=0.01, value=20)
    return south, north


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "GATE2_AOI_DIR", tmp_path / "aoi_sources")
    monkeypatch.setattr(G.RunManifest, "__init__", _manifest_init(tmp_path))
    return tmp_path


def _manifest_init(tmp_path):
    original = RunManifest.__init__

    def init(self, run_id=None, manifest_dir=tmp_path / "manifests"):
        original(self, run_id=run_id, manifest_dir=manifest_dir)
    return init


@needs_gdal
def test_clip_fails_when_the_halo_crosses_a_tile_line_but_one_tile_is_supplied(two_tiles, sandbox):
    """This is the invalidated run's exact failure. Hanoi's halo spans
    20.9689-21.0871N; with only the N21E105-equivalent tile the clip must
    refuse rather than pad the southern 3.4 km with NoData."""
    south, north = two_tiles
    aoi = _aoi("hanoi_core")
    with pytest.raises(TileCoverageError, match="not inside the union"):
        clip_raster(aoi, [north], RunManifest(), "worldcover", "test clip")
    with pytest.raises(TileCoverageError, match="not inside the union"):
        clip_raster(aoi, [south], RunManifest(), "worldcover", "test clip")


@needs_gdal
def test_clip_fails_before_clipping_when_a_required_tile_id_is_missing(two_tiles, sandbox):
    south, north = two_tiles
    with pytest.raises(TileCoverageError, match="were not supplied"):
        clip_raster(_aoi("hanoi_core"), [north], RunManifest(), "worldcover", "test clip",
                    required_tile_ids={"N", "S"})


@needs_gdal
def test_clip_mosaics_both_tiles_and_the_result_has_no_truncation_band(two_tiles, sandbox):
    south, north = two_tiles
    aoi = _aoi("hanoi_core")
    rec = clip_raster(aoi, [south, north], RunManifest(), "worldcover", "test clip")
    assert rec["transform"]["op"] == "vrt_mosaic_projwin_no_resample"
    assert rec["transform"]["source_tiles"] == ["S", "N"]
    assert rec["parent_source_ids"] == ["S", "N"]

    cov = rec["coverage"]
    assert cov["window_inside_tile_union"] and cov["window_covered_by_clip"]
    assert cov["edge_full_nodata"] == {"top": 0, "bottom": 0, "left": 0, "right": 0}

    w, s, e, n = halo_bbox(aoi)
    with rasterio.open(rec["path"]) as src:
        assert src.crs.to_string() == "EPSG:4326"
        assert src.nodata == 0.0
        assert abs(src.transform.a - 0.01) < 1e-12, "no resampling: native pixel size preserved"
        bw, bs, be, bn = src.bounds
        assert bw <= w + 0.0101 and bs <= s + 0.0101 and be >= e - 0.0101 and bn >= n - 0.0101
        arr = src.read(1)
        # Both tiles' values are present and nothing is NoData.
        assert (arr == 0).sum() == 0
        assert {10, 20} <= set(np.unique(arr).tolist())
    # No VRT is left behind next to the clip.
    assert not list(Path(rec["path"]).parent.glob("*.vrt"))


@needs_gdal
def test_validate_clip_coverage_detects_a_padded_truncated_window(two_tiles, tmp_path):
    """A clip cut from one tile only carries a solid NoData band where the
    other tile should have been. The geometric containment test catches it
    without having to trust the pixel values."""
    south, north = two_tiles
    aoi = _aoi("hanoi_core")
    window = halo_bbox(aoi)
    out = tmp_path / "padded.tif"
    G._projwin(north.path, out, window)
    with rasterio.open(out) as src:
        band = G._edge_nodata_bands(src.read(1), src.nodata)
    assert band["bottom"] > 0, "gdal pads the out-of-tile strip with NoData"
    with pytest.raises(TileCoverageError, match="not inside the union"):
        validate_clip_coverage(out, window, "EPSG:4326", 0.0, [G._tile_extent(north)])
    # With both extents declared the same file passes the containment test
    # only if its own bounds cover the window -- which a projwin does.
    meta = validate_clip_coverage(out, window, "EPSG:4326", 0.0,
                                  [G._tile_extent(north), G._tile_extent(south)])
    assert meta["edge_full_nodata"]["bottom"] > 0, "the diagnostic still exposes the band"


def test_validate_clip_coverage_rejects_wrong_crs_or_nodata(two_tiles):
    south, _ = two_tiles
    window = (105.1, 18.1, 105.2, 18.2)
    with pytest.raises(TileCoverageError, match="CRS"):
        validate_clip_coverage(south.path, window, "ESRI:54009", 0.0, [G._tile_extent(south)])
    with pytest.raises(TileCoverageError, match="NoData"):
        validate_clip_coverage(south.path, window, "EPSG:4326", 65535.0, [G._tile_extent(south)])


def test_validate_clip_coverage_rejects_a_clip_that_does_not_cover_its_window(two_tiles):
    south, _ = two_tiles
    # Ask the whole-tile file to prove it covers a window larger than itself.
    window = (104.0, 18.1, 105.2, 18.2)
    with pytest.raises(TileCoverageError):
        validate_clip_coverage(south.path, window, "EPSG:4326", 0.0, [G._tile_extent(south)])
