"""POI audit: OSM (deduplicated) vs. Overture Places, for the Da Nang-Hoi An
AOI. Produces the metrics required by COWORK_START_PROMPT.md section 3.

Confidence-threshold policy is NOT recommended from retention rate alone
(retention rate only says how many records a threshold removes, not
whether the removed records were actually lower quality). This module
computes three explicit policies (unfiltered, >=0.3, >=0.6) by canonical
group, plus a reproducible contact-info-presence proxy computed on every
record (no manual judgment, fully reproducible at scale) as one input to
that judgment -- the report combines this with a small manual/web-assisted
spot check (outside this module, since it needs live web access) before
making any per-group recommendation.

All "matched"/"cross-source" language here describes a proximity+category
HEURISTIC, never a confirmed entity match -- one OSM entity can be within
tolerance of many Overture records and vice versa (one-to-many), so a
`*_match_ratio` is reported alongside the raw counts to keep that risk
visible rather than implying a 1:1 correspondence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import STRtree

from .bbox_utils import clip_to_bbox as _clip_to_bbox

METRIC_CRS = "EPSG:32649"
# Reuses the SAME tolerance config/poi_taxonomy.yaml already uses for
# same-source (OSM node vs. polygon) dedup, applied here across sources --
# one documented distance tolerance for "same real-world POI" project-wide,
# rather than inventing a second unrelated number.
CROSS_SOURCE_MATCH_DISTANCE_M = 75.0

REVIEW_SAMPLE_CATEGORIES = [
    "school", "hospital", "clinic", "pharmacy", "food_drink", "retail_other",
    "lodging", "attraction_culture", "transport_bus_stop", "manufacturing",
    "park_recreation",
]
REVIEW_SAMPLE_SEED = 20260914
REVIEW_SAMPLE_N_PER_CATEGORY = 5

# Three explicit policies: unfiltered baseline plus two thresholds, per the
# review's requirement not to evaluate only a single >=0.5 cut.
CONFIDENCE_POLICIES = [0.0, 0.3, 0.6]


def _with_point_geometry(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """OSM POIs can be points or polygons (config/poi_taxonomy.yaml
    geometry_policy: polygon count_representation = point_on_surface).
    Overture Places are already points. This returns a copy with `geometry`
    replaced by each row's representative point, for distance-based
    matching/gridding -- never used for the area/distance features
    themselves, only for these audit heuristics."""
    if len(gdf) == 0 or (gdf.geometry.geom_type == "Point").all():
        return gdf
    out = gdf.copy()
    out["geometry"] = out.geometry.representative_point()
    return out


def record_counts_by_group_multi_policy(osm_gdf: gpd.GeoDataFrame, overture_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    osm_counts = osm_gdf["group"].value_counts().rename("osm")
    columns = [osm_counts]
    for threshold in CONFIDENCE_POLICIES:
        subset = overture_gdf[overture_gdf["confidence"] >= threshold]
        col_name = "overture_unfiltered" if threshold == 0.0 else f"overture_conf_ge_{threshold}"
        columns.append(subset["group"].value_counts(dropna=False).rename(col_name))
    df = pd.concat(columns, axis=1).fillna(0).astype(int)
    return df.sort_values("osm", ascending=False)


def contact_info_precision_proxy(overture_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """Reproducible, fully data-derived proxy signal (no manual judgment,
    computed on every record): fraction of records with website / phone /
    social present, by confidence band and canonical group. Reported
    SEPARATELY, not only OR-combined -- `has_phone` (~89%) and
    `has_social` (~99%, dominated by an auto-populated Facebook page link
    on Meta-sourced records) are both close to saturated in this dataset
    and carry almost no discriminating information; `has_website` (~40%
    overall) is the only one of the three with enough spread to be a
    useful signal, and reporting only the OR-combined rate would have
    hidden that entirely (an OR of near-saturated bits is even more
    saturated). This is weak-but-genuine evidence of an established,
    verifiable business -- it does NOT prove correctness, and is combined
    with a manual spot check in docs/source_validation_report.md.
    """
    df = overture_gdf.copy()
    df["confidence_band"] = pd.cut(
        df["confidence"], bins=[-0.01, 0.3, 0.6, 1.0],
        labels=["<0.3", "0.3-0.6", ">=0.6"],
    )
    return (
        df.groupby(["group", "confidence_band"], observed=True, dropna=False)
        .agg(
            n=("has_any_contact_info", "count"),
            has_website_rate=("has_website", "mean"),
            has_phone_rate=("has_phone", "mean"),
            has_social_rate=("has_social", "mean"),
            has_any_contact_info_rate=("has_any_contact_info", "mean"),
        )
        .reset_index()
    )


def provider_confidence_summary(overture_gdf: gpd.GeoDataFrame) -> dict:
    """Multi-provider analysis (ALL contributing sources per record, not
    just the first non-Overture entry), crossed with confidence bands."""
    from ..poi.overture_places import provider_summary

    overall = provider_summary(overture_gdf)

    df = overture_gdf.copy()
    df["confidence_band"] = pd.cut(
        df["confidence"], bins=[-0.01, 0.3, 0.6, 1.0],
        labels=["<0.3", "0.3-0.6", ">=0.6"],
    )
    by_band = {}
    for band, group in df.groupby("confidence_band", observed=True):
        by_band[str(band)] = provider_summary(gpd.GeoDataFrame(group, geometry="geometry", crs=overture_gdf.crs))
    return {"overall": overall, "by_confidence_band": by_band}


def missing_rates(gdf: gpd.GeoDataFrame, name_col: str, category_col: str) -> dict:
    if len(gdf) == 0:
        return {"missing_name_rate": None, "missing_category_rate": None}
    missing_name = gdf[name_col].isna() | (gdf[name_col].astype(str).str.strip() == "")
    missing_category = gdf[category_col].isna()
    return {
        "missing_name_rate": float(missing_name.mean()),
        "missing_category_rate": float(missing_category.mean()),
    }


def cross_source_proximity_heuristic(
    osm_gdf: gpd.GeoDataFrame,
    overture_gdf: gpd.GeoDataFrame,
    distance_m: float = CROSS_SOURCE_MATCH_DISTANCE_M,
) -> dict:
    """For each canonical category, count Overture records within
    `distance_m` of an OSM record of the SAME category ("overture_near_osm"
    -- a proximity+category HEURISTIC, NOT a confirmed 1:1 entity match: one
    OSM entity can be within tolerance of many Overture records, so
    `overture_records_per_osm_entity_near_it` is reported to keep that
    one-to-many risk visible rather than implying unique correspondence),
    Overture records with none ("overture_only"), and the symmetric OSM
    side."""
    osm_m = _with_point_geometry(osm_gdf.to_crs(METRIC_CRS))
    overture_m = overture_gdf.to_crs(METRIC_CRS)

    results = {}
    categories = sorted(set(osm_m["category"].dropna()) | set(overture_m["canonical_category"].dropna()))
    for cat in categories:
        osm_cat = osm_m[osm_m["category"] == cat]
        overture_cat = overture_m[overture_m["canonical_category"] == cat]
        if len(osm_cat) == 0 and len(overture_cat) == 0:
            continue
        if len(osm_cat) == 0:
            results[cat] = {"overture_near_osm": 0, "overture_only": len(overture_cat), "osm_near_overture": 0, "osm_only": 0}
            continue
        if len(overture_cat) == 0:
            results[cat] = {"overture_near_osm": 0, "overture_only": 0, "osm_near_overture": 0, "osm_only": len(osm_cat)}
            continue

        osm_tree = STRtree(osm_cat.geometry.values)
        overture_near_osm = 0
        for geom in overture_cat.geometry.values:
            idx = osm_tree.query(geom, predicate="dwithin", distance=distance_m)
            if len(idx) > 0:
                overture_near_osm += 1

        overture_tree = STRtree(overture_cat.geometry.values)
        osm_near_overture = 0
        for geom in osm_cat.geometry.values:
            idx = overture_tree.query(geom, predicate="dwithin", distance=distance_m)
            if len(idx) > 0:
                osm_near_overture += 1

        results[cat] = {
            "overture_near_osm": overture_near_osm,
            "overture_only": len(overture_cat) - overture_near_osm,
            "osm_near_overture": osm_near_overture,
            "osm_only": len(osm_cat) - osm_near_overture,
            "overture_records_per_osm_entity_near_it": round(overture_near_osm / osm_near_overture, 2) if osm_near_overture else None,
        }
    return results


def density_grid(gdf: gpd.GeoDataFrame, eval_bbox: tuple, cell_size_m: float = 1000.0) -> pd.DataFrame:
    """Full count grid over the evaluation AOI's own extent (NOT just the
    bounding box of the points that happen to exist) -- cells with zero
    points are included explicitly, since "empty areas" is exactly what
    this grid needs to be able to show. A grid built from the point
    cloud's own bounds would make it structurally impossible to ever see a
    zero-count cell.
    """
    import shapely.geometry as sgeom

    west, south, east, north = eval_bbox
    bbox_gdf = gpd.GeoDataFrame(geometry=[sgeom.box(west, south, east, north)], crs="EPSG:4326").to_crs(METRIC_CRS)
    xmin, ymin, xmax, ymax = bbox_gdf.total_bounds
    n_cols = max(1, int(np.ceil((xmax - xmin) / cell_size_m)))
    n_rows = max(1, int(np.ceil((ymax - ymin) / cell_size_m)))
    all_cells = pd.MultiIndex.from_product(
        [range(n_cols), range(n_rows)], names=["cx", "cy"]
    ).to_frame(index=False)

    clipped = _clip_to_bbox(gdf, eval_bbox)
    if len(clipped) == 0:
        point_counts = pd.DataFrame(columns=["cx", "cy", "count"])
    else:
        projected = _with_point_geometry(clipped.to_crs(METRIC_CRS))
        xs = np.floor((projected.geometry.x - xmin) / cell_size_m).astype(int).clip(0, n_cols - 1)
        ys = np.floor((projected.geometry.y - ymin) / cell_size_m).astype(int).clip(0, n_rows - 1)
        point_counts = pd.DataFrame({"cx": xs, "cy": ys}).groupby(["cx", "cy"]).size().reset_index(name="count")

    grid = all_cells.merge(point_counts, on=["cx", "cy"], how="left")
    grid["count"] = grid["count"].fillna(0).astype(int)
    grid["cell_x_m"] = xmin + (grid["cx"] + 0.5) * cell_size_m
    grid["cell_y_m"] = ymin + (grid["cy"] + 0.5) * cell_size_m
    return grid[["cell_x_m", "cell_y_m", "count"]].sort_values("count", ascending=False)


def build_review_sample(
    osm_gdf: gpd.GeoDataFrame,
    overture_gdf: gpd.GeoDataFrame,
    categories: list = REVIEW_SAMPLE_CATEGORIES,
    n_per_category: int = REVIEW_SAMPLE_N_PER_CATEGORY,
    seed: int = REVIEW_SAMPLE_SEED,
) -> pd.DataFrame:
    osm_gdf = _with_point_geometry(osm_gdf)
    rows = []
    for cat in categories:
        osm_cat = osm_gdf[osm_gdf["category"] == cat]
        if len(osm_cat):
            n = min(n_per_category, len(osm_cat))
            sample = osm_cat.sample(n=n, random_state=seed)
            for _, r in sample.iterrows():
                rows.append({
                    "category": cat, "source": "osm", "id": f"{r['osm_type']}/{r['osm_id']}",
                    "name": r.get("name"), "lon": r.geometry.x, "lat": r.geometry.y,
                })
        overture_cat = overture_gdf[overture_gdf["canonical_category"] == cat]
        if len(overture_cat):
            n = min(n_per_category, len(overture_cat))
            sample = overture_cat.sample(n=n, random_state=seed)
            for _, r in sample.iterrows():
                rows.append({
                    "category": cat, "source": "overture", "id": r["id"],
                    "name": r.get("name"), "lon": r.geometry.x, "lat": r.geometry.y,
                    "confidence": r.get("confidence"),
                    "has_any_contact_info": r.get("has_any_contact_info"),
                    "contributing_provider_count": r.get("contributing_provider_count"),
                })
    return pd.DataFrame(rows)


@dataclass
class PoiAuditResult:
    counts_by_group_multi_policy: pd.DataFrame
    provider_confidence_summary: dict
    contact_info_proxy: pd.DataFrame
    osm_missing_rates: dict
    overture_missing_rates: dict
    # Acquisition-scope: dedup run on the full acquisition-AOI POI set (the
    # scope osm_gdf_deduped/osm_dup_pairs above were actually computed at).
    osm_duplicate_pair_count_acquisition_scope: int
    osm_duplicate_rate_acquisition_scope: float
    # Evaluation-scope (preferred headline number, per review): dedup rerun
    # on POIs clipped to EVALUATION_AOI first, so both the numerator (dup
    # pairs found) and denominator (pre-dedup count) share the SAME scope
    # as every other evaluation-AOI metric in this audit.
    osm_duplicate_pair_count_evaluation_scope: int
    osm_duplicate_rate_evaluation_scope: float
    cross_source_proximity_heuristic: dict
    density_grid_osm: pd.DataFrame
    density_grid_overture: pd.DataFrame
    review_sample: pd.DataFrame
    notes: list = field(default_factory=list)


def run_poi_audit(
    osm_gdf_deduped: gpd.GeoDataFrame,
    osm_dup_pairs: gpd.GeoDataFrame,
    osm_gdf_pre_dedup_count: int,
    overture_gdf: gpd.GeoDataFrame,
    eval_bbox: tuple,
    osm_eval_scope_dup_pairs: gpd.GeoDataFrame,
    osm_eval_scope_pre_dedup_count: int,
) -> PoiAuditResult:
    osm_eval = _clip_to_bbox(osm_gdf_deduped, eval_bbox)
    overture_eval = _clip_to_bbox(overture_gdf, eval_bbox)

    counts = record_counts_by_group_multi_policy(osm_eval, overture_eval)
    provider_conf = provider_confidence_summary(overture_eval)
    contact_proxy = contact_info_precision_proxy(overture_eval)
    osm_missing = missing_rates(osm_eval, "name", "category")
    overture_missing = missing_rates(overture_eval, "name", "canonical_category")

    dup_rate_acquisition = len(osm_dup_pairs) / osm_gdf_pre_dedup_count if osm_gdf_pre_dedup_count else None
    dup_rate_eval = (
        len(osm_eval_scope_dup_pairs) / osm_eval_scope_pre_dedup_count if osm_eval_scope_pre_dedup_count else None
    )

    cross_match = cross_source_proximity_heuristic(osm_eval, overture_eval)

    grid_osm = density_grid(osm_eval, eval_bbox)
    grid_overture = density_grid(overture_eval, eval_bbox)

    review = build_review_sample(osm_eval, overture_eval)

    notes = [
        "Confidence-threshold policy is NOT set from retention rate alone -- see "
        "contact_info_proxy and docs/source_validation_report.md's manual spot-check "
        "for the evidence actually used.",
        f"{int(overture_eval['is_multi_provider'].sum())} / {len(overture_eval)} Overture records "
        f"({overture_eval['is_multi_provider'].mean():.1%}) have more than one contributing provider "
        f"in sources[] -- see provider_confidence_summary for the full breakdown.",
    ]

    return PoiAuditResult(
        counts_by_group_multi_policy=counts,
        provider_confidence_summary=provider_conf,
        contact_info_proxy=contact_proxy,
        osm_missing_rates=osm_missing,
        overture_missing_rates=overture_missing,
        osm_duplicate_pair_count_acquisition_scope=len(osm_dup_pairs),
        osm_duplicate_rate_acquisition_scope=dup_rate_acquisition,
        osm_duplicate_pair_count_evaluation_scope=len(osm_eval_scope_dup_pairs),
        osm_duplicate_rate_evaluation_scope=dup_rate_eval,
        cross_source_proximity_heuristic=cross_match,
        density_grid_osm=grid_osm,
        density_grid_overture=grid_overture,
        review_sample=review,
        notes=notes,
    )
