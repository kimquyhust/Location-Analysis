"""The Gate 3 output contract, derived from `config/features.yaml`.

`config/features.yaml` names the atomic MVP features, the mandatory
metadata and the mandatory source-status columns. This module turns that
into one ordered column list plus the per-feature status columns Gate 3
adds so that a null is never bare: every feature carries a status column
that says *why* a value is null (`not_found_within_cap`,
`search_truncated_by_extract`, `source_not_acquired`, `source_unavailable`,
`coverage_incomplete`, `denominator_zero`, `denominator_below_minimum`,
`entity_assembly_failed`) or that it is a real measurement (`ok`).

Nothing here computes a feature; `validate_frame` only checks that a frame
satisfies the contract: columns present, statuses from the declared
vocabulary, no bare nulls, values only with `ok`, and -- since 0.3.0 --
the numerical invariants every row must satisfy (ratios and fractions on
[0, 1], integer non-negative counts, non-negative lengths/densities/
distances, major <= total road length, land support <= valid <= cell,
richness <= total, distances within cap and complete-search radius,
source-failure consistency, valid H3 ids at the configured resolution, one
run/config/feature version per frame). A violation of any of these fails
validation; nothing is merely counted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml

DEFAULT_FEATURES_CONFIG = Path("config/features.yaml")

DISTANCE_FEATURES = [
    "distance_nearest_major_road_m",
    "distance_nearest_urban_centre_km",
    "distance_nearest_transit_stop_m",
    "distance_nearest_transport_hub_m",
    "distance_nearest_higher_education_m",
    "distance_nearest_hospital_m",
    "distance_nearest_park_m",
    "distance_nearest_osm_industrial_site_m",
]
# spatial.yaml distance_search_caps_m key per distance feature (km feature cap in m too).
DISTANCE_CAP_KEY = {
    "distance_nearest_major_road_m": "major_road",
    "distance_nearest_urban_centre_km": "urban_centre",
    "distance_nearest_transit_stop_m": "transit_stop",
    "distance_nearest_transport_hub_m": "transport_hub",
    "distance_nearest_higher_education_m": "higher_education",
    "distance_nearest_hospital_m": "hospital",
    "distance_nearest_park_m": "park",
    "distance_nearest_osm_industrial_site_m": "industrial_site",
}
COUNT_FEATURES_1KM = [
    "transit_stop_count_1km", "school_count_1km", "clinic_count_1km", "pharmacy_count_1km",
    "food_drink_count_1km", "retail_count_1km", "marketplace_count_1km", "lodging_count_1km",
    "park_recreation_count_1km", "poi_total_count_1km", "poi_category_richness_1km",
]
COUNT_FEATURES_3KM = [
    "higher_education_count_3km", "hospital_count_3km", "mall_count_3km", "attraction_culture_count_3km",
]
WORLDCOVER_RATIOS = ["tree_cover_ratio", "grass_shrub_ratio", "cropland_ratio", "water_wetland_ratio"]
RATIO_FEATURES = WORLDCOVER_RATIOS + ["built_up_ratio", "osm_industrial_site_area_ratio"]
FRACTION_COLUMNS = ["population_coverage_fraction", "built_up_coverage_fraction", "land_cover_coverage_fraction",
                    "population_nodata_area_fraction", "aoi_overlap_fraction"]
NON_NEGATIVE_FEATURES = ["population_count", "population_density", "road_length_km", "major_road_length_km",
                         "road_density_km_per_km2", "intersection_density_per_km2"] + DISTANCE_FEATURES
# Every OSM-derived feature: null with `source_unavailable` when the OSM source failed.
OSM_DERIVED = (["road_length_km", "major_road_length_km", "road_density_km_per_km2", "intersection_density_per_km2",
                "osm_industrial_site_area_ratio"] + COUNT_FEATURES_1KM + COUNT_FEATURES_3KM
               + [f for f in DISTANCE_FEATURES if f != "distance_nearest_urban_centre_km"])

STATUS_COLUMN_OF: dict[str, str] = {
    "population_count": "population_count_status",
    "population_density": "population_density_status",
    "built_up_ratio": "built_up_ratio_status",
    **{f: "land_cover_ratio_status" for f in WORLDCOVER_RATIOS},
    "road_length_km": "road_features_status",
    "major_road_length_km": "road_features_status",
    "road_density_km_per_km2": "road_density_status",
    "intersection_density_per_km2": "intersection_density_status",
    "osm_industrial_site_area_ratio": "osm_industrial_site_area_ratio_status",
    **{f: f"{f}_status" for f in DISTANCE_FEATURES},
    # 0.3.0: one status per count feature, so an assembly failure in one
    # category nulls that category's features and nothing else.
    **{f: f"{f}_status" for f in COUNT_FEATURES_1KM + COUNT_FEATURES_3KM},
}

# Denominators / coverage / provenance columns Gate 3 adds beyond the
# contract's mandatory lists, so density and ratio values are auditable.
EXTRA_COLUMNS = [
    "aoi_id", "aoi_context", "aoi_overlap_fraction", "spatial_decision_status", "spatial_metric_crs",
    "valid_land_support_area_km2", "land_cover_valid_area_km2", "population_nodata_area_fraction",
    "distance_search_complete_radius_m",
    "poi_source_policy", "road_source_policy", "osm_entity_assembly_failures",
    "admin_province_match_status", "admin_commune_match_status",
]

STATUS_VOCABULARY = {
    "ok", "not_found_within_cap", "search_truncated_by_extract", "source_not_acquired",
    "source_unavailable", "coverage_incomplete", "denominator_zero", "denominator_below_minimum",
    "entity_assembly_failed",
}
ADMIN_STATUS_VOCABULARY = {"ok", "source_not_acquired", "blocked_no_qualified_geometry"}


def load_features_config(path: Path = DEFAULT_FEATURES_CONFIG) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def status_columns() -> list[str]:
    seen: list[str] = []
    for col in STATUS_COLUMN_OF.values():
        if col not in seen:
            seen.append(col)
    return seen


def contract_columns(features_config: dict) -> list[str]:
    """Every column `atomic_features.parquet` must carry, in a stable order:
    metadata, features, source status, per-feature status, extras."""
    cols = list(features_config["required_metadata"])
    cols += list(features_config["mvp_features"])
    cols += list(features_config["required_source_status"])
    cols += [c for c in status_columns() if c not in cols]
    cols += [c for c in EXTRA_COLUMNS if c not in cols]
    return cols


def _finite(series: pd.Series) -> np.ndarray:
    return series.to_numpy(dtype="float64")


def validate_frame(df: pd.DataFrame, features_config: dict, spatial_config: Optional[dict] = None) -> dict:
    """Contract checks on a feature frame. Returns a report; `passed` is
    False if any hard check fails. See the module docstring for the list.
    `spatial_config` (config/spatial.yaml) enables the H3 resolution and
    distance-cap checks; without it those two are reported as skipped."""
    tol = float(features_config.get("semantics", {}).get("ratios", {}).get("unit_interval_tolerance", 1e-9))
    expected = contract_columns(features_config)
    missing = [c for c in expected if c not in df.columns]
    report: dict = {"expected_columns": len(expected), "missing_columns": missing,
                    "rows": int(len(df)), "problems": [], "checks": {}}
    problems = report["problems"]
    if missing:
        problems.append(f"missing columns: {missing}")

    def check(name: str, ok: bool, detail: str = "") -> None:
        report["checks"][name] = bool(ok)
        if not ok:
            problems.append(f"{name}: {detail}" if detail else name)

    if "spatial_unit_id" in df.columns:
        check("spatial_unit_id_non_null", not df["spatial_unit_id"].isna().any(), "null spatial_unit_id")
        check("spatial_unit_id_unique", df["spatial_unit_id"].is_unique, "duplicate spatial_unit_id")

    # --- status vocabulary and zero-vs-missing --------------------------------
    for feature, status_col in STATUS_COLUMN_OF.items():
        if feature not in df.columns or status_col not in df.columns:
            continue
        bad_vocab = set(df[status_col].dropna().unique()) - STATUS_VOCABULARY
        if bad_vocab:
            problems.append(f"{status_col}: values outside vocabulary {sorted(bad_vocab)}")
        if df[status_col].isna().any():
            problems.append(f"{status_col}: null status")
        ok = df[status_col] == "ok"
        value_null = df[feature].isna()
        bare_null = int((value_null & ok).sum())
        value_with_failure = int((~value_null & ~ok).sum())
        if bare_null:
            problems.append(f"{feature}: {bare_null} null values with status ok (bare null)")
        if value_with_failure:
            problems.append(f"{feature}: {value_with_failure} non-null values with a failure status")
        vals = df.loc[~value_null, feature].to_numpy(dtype="float64")
        if len(vals) and not np.isfinite(vals).all():
            problems.append(f"{feature}: non-finite values")

    # --- numerical invariants ----------------------------------------------------
    for col in RATIO_FEATURES + FRACTION_COLUMNS:
        if col in df.columns:
            v = _finite(df[col]); v = v[np.isfinite(v)]
            n_bad = int(((v < -tol) | (v > 1 + tol)).sum())
            check(f"{col}_in_unit_interval", n_bad == 0,
                  f"{n_bad} values outside [0, 1] (tolerance {tol:g}); max {v.max() if len(v) else 'n/a'}, min {v.min() if len(v) else 'n/a'}")
    for col in COUNT_FEATURES_1KM + COUNT_FEATURES_3KM:
        if col in df.columns:
            v = _finite(df[col]); v = v[np.isfinite(v)]
            check(f"{col}_non_negative_integer", bool(((v >= 0) & (v == np.round(v))).all()),
                  "negative or non-integer count")
    for col in NON_NEGATIVE_FEATURES + ["valid_land_support_area_km2", "land_cover_valid_area_km2",
                                        "spatial_unit_area_km2", "distance_search_complete_radius_m"]:
        if col in df.columns:
            v = _finite(df[col]); v = v[np.isfinite(v)]
            check(f"{col}_non_negative", bool((v >= 0).all()), f"min {v.min() if len(v) else 'n/a'}")
    if {"major_road_length_km", "road_length_km"} <= set(df.columns):
        both = df["major_road_length_km"].notna() & df["road_length_km"].notna()
        diff = (df.loc[both, "major_road_length_km"] - df.loc[both, "road_length_km"]).to_numpy(dtype="float64")
        check("major_road_length_le_road_length", bool((diff <= 1e-9).all()), f"max excess {diff.max() if len(diff) else 0}")
    if {"valid_land_support_area_km2", "land_cover_valid_area_km2", "spatial_unit_area_km2"} <= set(df.columns):
        ls, lv, ca = (_finite(df[c]) for c in ("valid_land_support_area_km2", "land_cover_valid_area_km2", "spatial_unit_area_km2"))
        m = np.isfinite(ls) & np.isfinite(lv)
        check("land_support_le_valid_le_cell",
              bool((ls[m] <= lv[m] * (1 + tol) + tol).all() and (lv[m] <= ca[m] * (1 + tol) + tol).all()),
              "land support > valid area or valid area > cell area")
    if {"poi_category_richness_1km", "poi_total_count_1km"} <= set(df.columns):
        both = df["poi_category_richness_1km"].notna() & df["poi_total_count_1km"].notna()
        check("richness_le_total_count",
              bool((df.loc[both, "poi_category_richness_1km"] <= df.loc[both, "poi_total_count_1km"]).all()),
              "richness exceeds total count")
    # distances with status ok are within the cap and within the complete-search radius
    if spatial_config is not None and "distance_search_complete_radius_m" in df.columns:
        caps = spatial_config["distance_search_caps_m"]
        cr = _finite(df["distance_search_complete_radius_m"])
        for f in DISTANCE_FEATURES:
            if f not in df.columns:
                continue
            ok = (df[f"{f}_status"] == "ok").to_numpy()
            if not ok.any():
                report["checks"][f"{f}_ok_within_cap_and_complete_radius"] = True
                continue
            v = _finite(df[f])[ok]
            scale = 1000.0 if f.endswith("_km") else 1.0
            cap = float(caps[DISTANCE_CAP_KEY[f]])
            check(f"{f}_ok_within_cap_and_complete_radius",
                  bool((v * scale <= cap + 1e-6).all() and (v * scale <= cr[ok] + 1e-6).all()),
                  "an ok distance exceeds the cap or the complete-search radius")
    else:
        report["checks"]["distance_caps"] = "skipped (no spatial config)"

    # --- source-failure consistency ------------------------------------------------
    if "osm_ingest_status" in df.columns:
        failed = (df["osm_ingest_status"] != "ok").to_numpy()
        if failed.any():
            bad = []
            for f in OSM_DERIVED:
                if f in df.columns:
                    st = df.loc[failed, STATUS_COLUMN_OF[f]]
                    if not (st == "source_unavailable").all() or df.loc[failed, f].notna().any():
                        bad.append(f)
            if "osm_query_complete" in df.columns and df.loc[failed, "osm_query_complete"].astype(bool).any():
                bad.append("osm_query_complete")
            check("osm_source_failure_propagates", not bad, f"not source_unavailable/null on failed rows: {bad}")
        else:
            report["checks"]["osm_source_failure_propagates"] = True
    if "osm_entity_assembly_failures" in df.columns:
        for aoi, sub in df.groupby("aoi_id") if "aoi_id" in df.columns else [("all", df)]:
            spec = sub["osm_entity_assembly_failures"].iloc[0]
            check(f"assembly_failure_spec_uniform_{aoi}", bool((sub["osm_entity_assembly_failures"] == spec).all()),
                  "assembly-failure record differs within an AOI")

    # --- identifiers and versions ----------------------------------------------------
    if spatial_config is not None and "spatial_unit_id" in df.columns:
        try:
            import h3
            res = int(spatial_config["spatial_unit"]["h3_resolution"])
            ids = df["spatial_unit_id"].astype(str)
            valid = ids.map(h3.is_valid_cell)
            right_res = ids[valid].map(h3.get_resolution) == res
            check("h3_ids_valid_at_config_resolution", bool(valid.all() and right_res.all()),
                  f"{int((~valid).sum())} invalid ids, {int((~right_res).sum())} at another resolution")
            if "spatial_resolution" in df.columns:
                check("spatial_resolution_matches_config", bool((df["spatial_resolution"] == res).all()), "")
        except ImportError:  # pragma: no cover
            report["checks"]["h3_ids_valid_at_config_resolution"] = "skipped (h3 missing)"
    for col in ("run_id", "feature_set_version", "poi_taxonomy_version", "source_manifest_id", "computed_at_utc"):
        if col in df.columns:
            check(f"{col}_uniform", df[col].nunique(dropna=False) == 1 and not df[col].isna().any(),
                  f"{df[col].nunique(dropna=False)} distinct values")
    if "feature_set_version" in df.columns and len(df):
        check("feature_set_version_matches_config",
              str(df["feature_set_version"].iloc[0]) == str(features_config["feature_set_version"]),
              f"{df['feature_set_version'].iloc[0]} != {features_config['feature_set_version']}")

    for col in ("admin_province_match_status", "admin_commune_match_status"):
        if col in df.columns:
            bad = set(df[col].dropna().unique()) - ADMIN_STATUS_VOCABULARY
            if bad or df[col].isna().any():
                problems.append(f"{col}: invalid values {sorted(bad)}")
    if "admin_match_status" in df.columns:
        if df["admin_match_status"].isna().any() or (df["admin_match_status"] == "").any():
            problems.append("admin_match_status: empty")

    report["passed"] = not problems
    return report


def null_and_zero_rates(df: pd.DataFrame, features_config: dict) -> pd.DataFrame:
    """Per feature: null rate, zero rate, status counts -- the table the
    report and feature_manifest use to separate mapped zeros from nulls."""
    rows = []
    for feature in features_config["mvp_features"]:
        status_col = STATUS_COLUMN_OF.get(feature)
        statuses = df[status_col].value_counts().to_dict() if status_col in df.columns else {}
        v = df[feature]
        rows.append({
            "feature": feature, "rows": int(len(v)), "null_count": int(v.isna().sum()),
            "null_rate": float(v.isna().mean()) if len(v) else float("nan"),
            "zero_count": int((v == 0).sum()), "zero_rate": float((v == 0).mean()) if len(v) else float("nan"),
            "status_counts": statuses,
        })
    return pd.DataFrame(rows)
