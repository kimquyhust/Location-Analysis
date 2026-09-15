"""Runs the POI, road, and population audits against the already-acquired
Da Nang-Hoi An AOI data and writes reproducible JSON/CSV summaries under
`data/prototype/danang_hoian_halo/audit/`. Run
`python -m src.ingestion.run_acquisition` first.

Usage: `python -m src.audit.run_all_audits`
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

AOI_DIR = Path("data/prototype/danang_hoian_halo")
OUT_DIR = AOI_DIR / "audit"
ACQUISITION_AOI = (108.07, 15.72, 108.38, 16.18)
EVALUATION_AOI = (108.10, 15.75, 108.35, 16.15)


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, dict):
        return {str(k): v for k, v in o.items()}
    raise TypeError(f"not JSON serializable: {type(o)}")


def run_poi(osm_extract, overture_gdf):
    from ..audit.bbox_utils import clip_to_bbox
    from ..poi.dedup import deduplicate_osm_pois
    from .poi_audit import run_poi_audit

    deduped, dups = deduplicate_osm_pois(osm_extract.poi_gdf)

    # Evaluation-scope duplicate rate (preferred headline number, per
    # review): clip the RAW (pre-dedup) POIs to EVALUATION_AOI first, then
    # rerun dedup on that clipped set -- so both the numerator and
    # denominator share the same scope as every other evaluation-AOI metric,
    # rather than mixing an acquisition-scope dup count with an
    # acquisition-scope pre-dedup count that happen to both be
    # acquisition-wide but aren't labeled as such.
    eval_raw_pois = clip_to_bbox(osm_extract.poi_gdf, EVALUATION_AOI)
    eval_deduped, eval_dups = deduplicate_osm_pois(eval_raw_pois)

    result = run_poi_audit(
        deduped, dups, len(osm_extract.poi_gdf), overture_gdf, EVALUATION_AOI,
        eval_dups, len(eval_raw_pois),
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = {
        "counts_by_group_multi_policy": result.counts_by_group_multi_policy.reset_index().rename(columns={"index": "group"}).to_dict(orient="records"),
        "provider_confidence_summary": result.provider_confidence_summary,
        "contact_info_proxy": result.contact_info_proxy.to_dict(orient="records"),
        "osm_missing_rates": result.osm_missing_rates,
        "overture_missing_rates": result.overture_missing_rates,
        "osm_duplicate_pair_count_acquisition_scope": result.osm_duplicate_pair_count_acquisition_scope,
        "osm_duplicate_rate_acquisition_scope": result.osm_duplicate_rate_acquisition_scope,
        "osm_duplicate_pair_count_evaluation_scope": result.osm_duplicate_pair_count_evaluation_scope,
        "osm_duplicate_rate_evaluation_scope": result.osm_duplicate_rate_evaluation_scope,
        "cross_source_proximity_heuristic_by_category": result.cross_source_proximity_heuristic,
        "notes": result.notes,
        "density_grid_osm_zero_share": float((result.density_grid_osm["count"] == 0).mean()) if len(result.density_grid_osm) else None,
        "density_grid_overture_zero_share": float((result.density_grid_overture["count"] == 0).mean()) if len(result.density_grid_overture) else None,
        "density_grid_cell_count": len(result.density_grid_osm),
        "density_grid_osm_top5": result.density_grid_osm.head(5).to_dict(orient="records"),
        "density_grid_overture_top5": result.density_grid_overture.head(5).to_dict(orient="records"),
        "relevant_relation_omissions": {
            f"{k}": v for k, v in osm_extract.skipped_relevant_relation_counts.items()
        },
    }
    (OUT_DIR / "poi_audit_summary.json").write_text(json.dumps(summary, indent=2, default=_json_default))
    result.review_sample.to_csv(OUT_DIR / "poi_review_sample.csv", index=False)
    result.density_grid_osm.to_csv(OUT_DIR / "poi_density_grid_osm.csv", index=False)
    result.density_grid_overture.to_csv(OUT_DIR / "poi_density_grid_overture.csv", index=False)
    dups.drop(columns="geometry", errors="ignore").to_csv(OUT_DIR / "osm_poi_duplicate_pairs.csv", index=False)
    print("POI audit written.")
    return result


def run_roads(osm_extract, overture_road_extract):
    from .road_audit import run_road_audit

    overture_node_xy_wgs84 = {
        row["id"]: (row.geometry.x, row.geometry.y)
        for _, row in overture_road_extract.connector_gdf.iterrows()
    }
    result = run_road_audit(
        osm_extract.road_gdf, osm_extract.road_graph, osm_extract.road_node_location,
        overture_road_extract.road_gdf, overture_road_extract.road_graph, overture_node_xy_wgs84,
        EVALUATION_AOI, ACQUISITION_AOI,
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = {
        "osm_length_by_class_m": result.osm_length_by_class_m,
        "overture_length_by_class_m": result.overture_length_by_class_m,
        "acquisition_halo_scope": {
            "osm_connectivity": {k: v for k, v in result.osm_connectivity_halo_scope.items() if k != "top_component_lengths_m"},
            "overture_connectivity": {k: v for k, v in result.overture_connectivity_halo_scope.items() if k != "top_component_lengths_m"},
            "osm_top_components_m": result.osm_connectivity_halo_scope["top_component_lengths_m"],
            "overture_top_components_m": result.overture_connectivity_halo_scope["top_component_lengths_m"],
            "osm_intersection_count": result.osm_intersection_count_halo_scope,
            "overture_connector_intersection_count": result.overture_connector_intersection_count_halo_scope,
        },
        "evaluation_scope": {
            "osm_connectivity": {k: v for k, v in result.osm_connectivity_eval_scope.items() if k != "top_component_lengths_m"},
            "overture_connectivity": {k: v for k, v in result.overture_connectivity_eval_scope.items() if k != "top_component_lengths_m"},
            "osm_top_components_m": result.osm_connectivity_eval_scope["top_component_lengths_m"],
            "overture_top_components_m": result.overture_connectivity_eval_scope["top_component_lengths_m"],
            "osm_intersection_count": result.osm_intersection_count_eval_scope,
            "overture_connector_intersection_count": result.overture_connector_intersection_count_eval_scope,
        },
        "matched_length": result.matched_length,
        "unmatched_major_osm_sample": result.unmatched_major_osm_sample,
        "unmatched_major_overture_sample": result.unmatched_major_overture_sample,
        "feature_impact_notes": result.feature_impact_notes,
    }
    (OUT_DIR / "road_audit_summary.json").write_text(json.dumps(summary, indent=2, default=_json_default))
    print("Road audit written.")
    return result


def run_population(osm_extract):
    from .population_audit import (
        compare_worldpop_ghspop_2020,
        conservation_report,
        mapped_water_polygon_stratum,
        summarize_worldpop2025,
    )

    cmp = compare_worldpop_ghspop_2020(
        AOI_DIR / "worldpop-2020-count.tif",
        Path("data/raw/ghsl/pop-e2020-r8-c29/GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0_R8_C29.tif"),
        ACQUISITION_AOI,
    )
    wp2025 = summarize_worldpop2025(AOI_DIR / "worldpop-2025-count.tif", ACQUISITION_AOI)

    conservation = {
        "worldpop_2020": conservation_report(AOI_DIR / "worldpop-2020-count.tif", ACQUISITION_AOI, nodata=-99999.0),
        "worldpop_2025": conservation_report(AOI_DIR / "worldpop-2025-count.tif", ACQUISITION_AOI, nodata=-99999.0),
        "ghspop_2020": conservation_report(
            Path("data/raw/ghsl/pop-e2020-r8-c29/GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0_R8_C29.tif"),
            ACQUISITION_AOI, nodata=-200.0,
        ),
    }

    water_gdf = osm_extract.area_gdf[osm_extract.area_gdf["area_category"] == "water_body"] if len(osm_extract.area_gdf) else None
    water_stratum = mapped_water_polygon_stratum(water_gdf, ACQUISITION_AOI, cmp.worldpop2020.grid, cmp.ghspop2020.grid)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = {
        "worldpop_2020_total": cmp.worldpop2020.total_population,
        "worldpop_2020_nonzero_fraction": cmp.worldpop2020.non_zero_fraction,
        "worldpop_2020_quantiles": cmp.worldpop2020.quantiles,
        "ghspop_2020_total": cmp.ghspop2020.total_population,
        "ghspop_2020_nonzero_fraction": cmp.ghspop2020.non_zero_fraction,
        "ghspop_2020_quantiles": cmp.ghspop2020.quantiles,
        "common_valid_cell_count": cmp.common_valid_cell_count,
        "spearman_rho": cmp.spearman_rho,
        "spearman_p": cmp.spearman_p,
        "abs_diff_mean": cmp.abs_diff_mean,
        "abs_diff_median": cmp.abs_diff_median,
        "rel_diff_median": cmp.rel_diff_median,
        "rel_diff_undefined_fraction": cmp.rel_diff_undefined_fraction,
        "density_proxy_strata": cmp.strata,
        "mapped_water_polygon_stratum": water_stratum,
        "conservation_report": conservation,
        "worldpop_2025_total": wp2025.total_population,
        "worldpop_2025_nonzero_fraction": wp2025.non_zero_fraction,
        "worldpop_2025_vs_2020_growth_fraction": (wp2025.total_population / cmp.worldpop2020.total_population - 1),
        "grid": "1km EPSG:32649, Resampling.sum (area-conserving), acquisition AOI",
    }
    (OUT_DIR / "population_audit_summary.json").write_text(json.dumps(summary, indent=2, default=_json_default))
    print("Population audit written.")
    return cmp, wp2025


def main():
    from ..poi.osm_extract import parse_osm_aoi
    from ..poi.overture_places import load_overture_places
    from ..roads.overture_transportation import load_overture_roads

    osm_extract = parse_osm_aoi(AOI_DIR / "osm-260913.osm.pbf", minimum_degree=3, clip_bbox=ACQUISITION_AOI)
    overture_places = load_overture_places(AOI_DIR / "overture-places.parquet")
    overture_roads = load_overture_roads(
        AOI_DIR / "overture-transportation-segments.parquet",
        AOI_DIR / "overture-transportation-connectors.parquet",
    )

    run_poi(osm_extract, overture_places)
    run_roads(osm_extract, overture_roads)
    run_population(osm_extract)
    print(f"All audit summaries written under {OUT_DIR}")


if __name__ == "__main__":
    main()
