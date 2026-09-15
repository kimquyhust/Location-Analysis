"""Gate 3 Atomic Feature MVP runner: pinned raw inputs -> H3 units ->
atomic features under the contract -> one immutable four-AOI run.

    python -m src.features.run_gate3_mvp                  # all four MVP AOIs
    python -m src.features.run_gate3_mvp --aoi hanoi_core  # smoke (partial)

Nothing here normalises, scores, or reads customer data. The spatial unit
comes from `config/spatial.yaml` (H3, resolution read from config, status
`provisional_mvp`); the feature contract from `config/features.yaml`; the
run parameters from `config/gate3_mvp.yaml`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
import yaml
from rasterio.transform import rowcol, xy
from shapely.geometry import box

try:  # pragma: no cover - import root differs between CLI and tests
    from ..poi.dedup import deduplicate_osm_pois
    from ..poi.osm_extract import parse_osm_aoi
    from ..spatial.aoi import aoi_checksum, load_aois, write_aoi_geojson
    from ..spatial.benchmark import (RunContext, code_version, environment, hash_config, sha256_of,
                                     utc_now_iso, write_run_manifest)
    from ..spatial.candidates import H3Grid
    from ..spatial.run_gate2_mvp import verify_checksums, write_checksums
    from .compute import AoiInputs, compute_aoi_features
    from .provenance import load_source_index, verify_aoi_sources
    from .raster import open_band, pixel_weights, valid_mask, weighted_sum
    from .schema import contract_columns, load_features_config, null_and_zero_rates, validate_frame
except ImportError:  # pragma: no cover
    from poi.dedup import deduplicate_osm_pois
    from poi.osm_extract import parse_osm_aoi
    from spatial.aoi import aoi_checksum, load_aois, write_aoi_geojson
    from spatial.benchmark import (RunContext, code_version, environment, hash_config, sha256_of,
                                   utc_now_iso, write_run_manifest)
    from spatial.candidates import H3Grid
    from spatial.run_gate2_mvp import verify_checksums, write_checksums
    from features.compute import AoiInputs, compute_aoi_features
    from features.provenance import load_source_index, verify_aoi_sources
    from features.raster import open_band, pixel_weights, valid_mask, weighted_sum
    from features.schema import contract_columns, load_features_config, null_and_zero_rates, validate_frame

GATE3_CONFIG = Path("config/gate3_mvp.yaml")
REQUIRED_OUTPUTS = ["atomic_features.parquet", "spatial_units.parquet", "feature_manifest.json",
                    "source_coverage.parquet", "validation_summary.json", "run_manifest.json",
                    "aois.geojson"]
CONSERVATION_TOLERANCE = 1e-9


def latest_full_run(root: Path = Path("data/gate3"), prefix: str = "run_") -> Optional[Path]:
    """Newest run directory that is a complete, checksummed FULL MVP run
    (`run_kind == atomic_feature_mvp`). Smoke runs written later are
    skipped, so a test or reader never picks a partial artifact by
    accident."""
    if not root.exists():
        return None
    for run in sorted(root.glob(f"{prefix}*"), reverse=True):
        manifest = run / "run_manifest.json"
        if not (run / "SHA256SUMS").exists() or not manifest.exists():
            continue
        try:
            m = json.loads(manifest.read_text())
        except json.JSONDecodeError:
            continue
        if m.get("gate") == 3 and m.get("run_kind") == "atomic_feature_mvp":
            return run
    return None


def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def build_units(aoi, spatial_cfg: dict) -> gpd.GeoDataFrame:
    unit = spatial_cfg["spatial_unit"]
    if unit["method"] != "h3":
        raise ValueError(f"Gate 3 MVP expects spatial_unit.method h3; config says {unit['method']!r}")
    return H3Grid(resolution=int(unit["h3_resolution"])).units(aoi.polygon, aoi.metric_crs)


def load_aoi_inputs(aoi, index: dict, cfg: dict, features_path: Path, taxonomy_path: Path,
                    taxonomy: dict, features_cfg: dict, spatial_cfg: dict, ctx: RunContext) -> tuple[AoiInputs, dict]:
    sources = index["aois"][aoi.id]
    if sources["aoi_checksum"] != aoi_checksum(aoi):
        raise RuntimeError(f"{aoi.id}: AOI geometry changed since acquisition "
                           f"({aoi_checksum(aoi)} != {sources['aoi_checksum']})")
    stats: dict = {}
    with ctx.stage(aoi_id=aoi.id, stage="units") as s:
        units = build_units(aoi, spatial_cfg)
        s.rows = len(units)

    with ctx.stage(aoi_id=aoi.id, stage="osm_parse") as s:
        halo = tuple(sources["halo_bbox_wgs84"])
        extract = parse_osm_aoi(Path(sources["roads_poi"]["path"]),
                                minimum_degree=int(features_cfg["parameters"]["intersections"]["minimum_degree"]),
                                taxonomy_path=taxonomy_path, features_path=features_path, clip_bbox=halo)
        s.rows = len(extract.poi_gdf) + len(extract.road_gdf)
    with ctx.stage(aoi_id=aoi.id, stage="poi_dedup") as s:
        max_d = float(taxonomy["entity_policy"]["cross_geometry_deduplication"]["maximum_representative_point_distance_m"])
        deduped, dropped = deduplicate_osm_pois(extract.poi_gdf, max_distance_m=max_d, metric_crs=aoi.metric_crs)
        s.rows = len(deduped)
    stats.update({
        "osm_raw_poi_records": int(len(extract.poi_gdf)), "osm_canonical_pois": int(len(deduped)),
        "osm_poi_duplicates_dropped": int(len(dropped)), "osm_road_ways": int(len(extract.road_gdf)),
        "osm_intersections": int(len(extract.intersections_gdf)), "osm_area_records": int(len(extract.area_gdf)),
        "osm_poi_geometry_types": extract.stats["poi_geometry_types"],
        "osm_poi_from_relations": extract.stats["poi_from_relations"],
        "osm_area_from_relations": extract.stats["area_from_relations"],
        "osm_relevant_relations": extract.stats["relevant_relations"],
        "osm_relation_member_duplicates_dropped": int(len(extract.member_duplicates)),
        "osm_relation_member_duplicates": list(extract.member_duplicates),
        "osm_open_way_entities": dict(extract.open_way_entity_counts),
        "osm_entity_assembly": extract.assembly,
        "osm_entity_assembly_failures_by_category": dict(extract.assembly_failures_by_category),
    })
    # Source status from the acquisition index: anything but `ok` marks the
    # OSM source unavailable and every OSM-derived feature null.
    osm_ingest_status = str(sources["roads_poi"].get("ingest_status", "ok"))

    halo_metric = gpd.GeoSeries([box(*halo)], crs="EPSG:4326").to_crs(aoi.metric_crs).iloc[0]
    with ctx.stage(aoi_id=aoi.id, stage="raster_open") as s:
        wc = open_band(Path(sources["land_cover"]["path"]))
        wp = open_band(Path(sources["population"]["path"]))
        bu = open_band(Path(sources["built_up"]["path"]))
        s.rows = 3
    inputs = AoiInputs(
        aoi_id=aoi.id, context=aoi.context, metric_crs=aoi.metric_crs, units=units,
        halo_polygon_metric=halo_metric,
        poi_metric=deduped.to_crs(aoi.metric_crs) if len(deduped) else deduped,
        roads_metric=extract.road_gdf.to_crs(aoi.metric_crs) if len(extract.road_gdf) else extract.road_gdf,
        intersections_metric=(extract.intersections_gdf.to_crs(aoi.metric_crs)
                              if len(extract.intersections_gdf) else extract.intersections_gdf),
        area_metric=extract.area_gdf.to_crs(aoi.metric_crs) if len(extract.area_gdf) else extract.area_gdf,
        poi_duplicates_dropped=int(len(dropped)), worldcover=wc, worldpop=wp, builtup=bu,
        osm_ingest_status=osm_ingest_status,
        entity_assembly_failures=dict(extract.assembly_failures_by_category),
    )
    return inputs, stats


def conservation_checks(inputs: AoiInputs, df: pd.DataFrame) -> dict:
    """Independent identities: the sum over cells must equal the
    area-weighted sum over the UNION of the cells, computed in one pass on
    the raster (a different code path from the per-cell loop)."""
    out = {}
    for name, band, col in (("population", inputs.worldpop, "population_count"),
                            ("built_up_m2", inputs.builtup, "_built_up_m2")):
        units_r = inputs.units.to_crs(band.crs)
        union = shapely.union_all(units_r.geometry.to_numpy())
        total_union, _, _ = weighted_sum(band, pixel_weights(union, band.transform, band.shape), valid_mask(band))
        total_cells = float(np.nansum(df[col].to_numpy(dtype="float64")))
        rel = abs(total_cells - total_union) / total_union if total_union else 0.0
        out[name] = {"sum_over_cells": total_cells, "sum_over_union_of_cells": total_union,
                     "relative_error": rel, "passed": rel <= CONSERVATION_TOLERANCE}
    # Ratio identity: the four WorldCover rollups can never exceed the valid area.
    s = (df[["tree_cover_ratio", "grass_shrub_ratio", "cropland_ratio", "water_wetland_ratio"]]
         .sum(axis=1, min_count=1))
    out["worldcover_rollup_sum_max"] = float(np.nanmax(s.to_numpy())) if len(s) else None
    out["worldcover_rollups_within_valid_area"] = bool(np.nanmax(s.to_numpy()) <= 1.0 + 1e-9) if len(s) else True
    # Ratio audit: the UNMASKED numerators (built-up / industrial area over
    # the whole cell, including water) divided by land support. These are
    # the values the 0.2.0 run clipped; here they are reported, and the
    # published ratios use the masked numerators instead.
    for name, col in (("built_up", "_built_up_ratio_unmasked"), ("industrial", "_industrial_ratio_unmasked")):
        raw = df[col].to_numpy(dtype="float64")
        pub = df["built_up_ratio" if name == "built_up" else "osm_industrial_site_area_ratio"].to_numpy(dtype="float64")
        over = np.isfinite(raw) & (raw > 1.0 + 1e-9)
        out[f"{name}_ratio_unmasked_cells_over_1"] = int(over.sum())
        out[f"{name}_ratio_unmasked_max"] = float(np.nanmax(raw)) if np.isfinite(raw).any() else None
        out[f"{name}_ratio_published_max"] = float(np.nanmax(pub)) if np.isfinite(pub).any() else None
        out[f"{name}_ratio_cells_over_1_unmasked_detail"] = [
            {"spatial_unit_id": str(u), "unmasked": float(r), "published": (None if not np.isfinite(q) else float(q))}
            for u, r, q in zip(df.loc[over, "spatial_unit_id"], raw[over], pub[over])]
    out["industrial_numerator_m2"] = {
        "raw_total": float(np.nansum(df["_industrial_area_m2_raw"].to_numpy(dtype="float64"))),
        "on_land_support_total": float(np.nansum(df["_industrial_area_m2_on_land_support"].to_numpy(dtype="float64")))}
    out["built_up_numerator_m2"] = {
        "raster_native_total": float(np.nansum(df["_built_up_m2"].to_numpy(dtype="float64"))),
        "on_land_support_total": float(np.nansum(df["_built_up_m2_on_land_support"].to_numpy(dtype="float64")))}
    # Land support can never exceed cell area.
    ls = df["valid_land_support_area_km2"] / df["spatial_unit_area_km2"]
    out["land_support_fraction_max"] = float(np.nanmax(ls.to_numpy())) if len(ls) else None
    out["land_support_within_cell"] = bool(np.nanmax(ls.to_numpy()) <= 1.0 + 1e-9) if len(ls) else True
    return out


def worldpop_nodata_decomposition(inputs: AoiInputs, features_cfg: dict) -> dict:
    """What lies under WorldPop publisher-NoData pixels inside the halo
    window: WorldCover permanent water, other land classes, or WorldCover
    NoData -- sampled at WorldPop pixel centres. Separates the intentional
    settlement mask (land) from the mastergrid water mask so the
    zero-persons policy (features.yaml semantics.raster.worldpop) is
    auditable per AOI."""
    wp, wc = inputs.worldpop, inputs.worldcover
    wc_cfg = features_cfg["semantics"]["raster"]["worldcover"]
    water = {int(c) for c in wc_cfg["land_support_excludes"]}
    nodata_class = int(wc_cfg["nodata_class"])
    nd = ~valid_mask(wp)
    rows, cols = np.nonzero(nd)
    total = int(nd.sum())
    if total == 0 or wp.crs != wc.crs:
        return {"nodata_pixels": total, "window_pixels": int(wp.array.size), "note": "no NoData or CRS differs"}
    xs, ys = xy(wp.transform, rows, cols, offset="center")
    r, c = rowcol(wc.transform, np.asarray(xs), np.asarray(ys))
    r, c = np.asarray(r), np.asarray(c)
    inside = (r >= 0) & (r < wc.shape[0]) & (c >= 0) & (c < wc.shape[1])
    classes = np.full(len(r), -1, dtype="int64")
    classes[inside] = wc.array[r[inside], c[inside]]
    n_water = int(np.isin(classes, list(water)).sum())
    n_wc_nodata = int((classes == nodata_class).sum())
    n_outside = int((~inside).sum())
    n_land = total - n_water - n_wc_nodata - n_outside
    return {"nodata_pixels": total, "window_pixels": int(wp.array.size),
            "nodata_fraction_of_window": total / wp.array.size,
            "over_worldcover_permanent_water": n_water, "over_worldcover_land_classes": n_land,
            "over_worldcover_nodata": n_wc_nodata, "outside_worldcover_window": n_outside,
            "share_water": n_water / total, "share_land_unsettled_mask": n_land / total,
            "valid_pixel_sum_persons": float(wp.array[~nd].astype("float64").sum()),
            "valid_pixels_equal_to_zero": int((wp.array[~nd] == 0).sum())}


def feature_manifest(df: pd.DataFrame, features_cfg: dict, cfg: dict) -> dict:
    rates = null_and_zero_rates(df, features_cfg)
    entries = []
    for row in rates.itertuples():
        statuses = row.status_counts
        if statuses and set(statuses) == {"source_not_acquired"}:
            disposition = "null_by_contract_source_not_acquired"
        elif row.null_rate == 1.0:
            disposition = "null_all_rows"
        else:
            disposition = "implemented"
        entries.append({"feature": row.feature, "disposition": disposition, "rows": row.rows,
                        "null_count": row.null_count, "null_rate": row.null_rate,
                        "zero_count": row.zero_count, "zero_rate": row.zero_rate,
                        "status_counts": statuses})
    return {
        "feature_set_version": str(features_cfg["feature_set_version"]),
        "poi_taxonomy_version": str(df["poi_taxonomy_version"].iloc[0]) if len(df) else None,
        "feature_semantics": features_cfg["semantics"],
        "poi_source_policy": cfg["sources"]["poi_source_policy"],
        "road_source_policy": cfg["sources"]["road_source_policy"],
        "contract_columns": contract_columns(features_cfg),
        "features": entries,
        "metadata_null_by_contract": {
            "admin_province_code": cfg["sources"]["admin_province"]["status"],
            "admin_commune_code": cfg["sources"]["admin_commune"]["status"],
        },
        "deferred": ["overture_places_commercial_augmentation", "contextual_normalization (Gate 4)",
                     "semantic_scores (Gate 5)", "nationwide_processing (Gate 6)",
                     "urban_centre_distance (UCDB not acquired)",
                     "admin_codes (province not pinned; commune blocked)"],
    }


def per_aoi_summary(df: pd.DataFrame, features_cfg: dict) -> dict:
    out = {}
    for aoi_id, sub in df.groupby("aoi_id"):
        feats = {}
        for f in features_cfg["mvp_features"]:
            v = sub[f].to_numpy(dtype="float64")
            finite = v[np.isfinite(v)]
            feats[f] = {
                "null_rate": float(np.isnan(v).mean()), "zero_rate": float((v == 0).mean()),
                "p05": float(np.percentile(finite, 5)) if len(finite) else None,
                "median": float(np.median(finite)) if len(finite) else None,
                "p95": float(np.percentile(finite, 95)) if len(finite) else None,
            }
        out[aoi_id] = {"cells": int(len(sub)),
                       "cells_fully_inside_aoi": int((sub["aoi_overlap_fraction"] >= 1 - 1e-9).sum()),
                       "features": feats}
    return out


def run(aoi_ids: Optional[list[str]], cfg: dict, config_path: Path = GATE3_CONFIG) -> dict:
    run_cfg = cfg["run"]
    spatial_path, features_path = Path(run_cfg["spatial_config"]), Path(run_cfg["features_config"])
    taxonomy_path = Path(run_cfg["taxonomy_config"])
    spatial_cfg, features_cfg, taxonomy = load_yaml(spatial_path), load_features_config(features_path), load_yaml(taxonomy_path)

    wanted = list(run_cfg["aoi_ids"])
    if aoi_ids is not None:
        unknown = set(aoi_ids) - set(wanted)
        if unknown:
            raise ValueError(f"{sorted(unknown)} are not Gate 3 MVP AOIs; the set is {wanted}")
        wanted = [a for a in wanted if a in aoi_ids]
    by_id = {a.id: a for a in load_aois(spatial_path)}
    aois = [by_id[a] for a in wanted]

    index, manifest_entries = load_source_index(Path(run_cfg["source_index"]))
    ctx = RunContext(
        run_id=pd.Timestamp.now("UTC").strftime("%Y%m%dT%H%M%SZ"),
        config_hash=hash_config(config_path, spatial_path, features_path, taxonomy_path),
        code_version=code_version(), environment=environment(),
        source_releases={"source_index": run_cfg["source_index"],
                         **{a.id: index["aois"][a.id].get("acquisition_run_id") for a in aois if a.id in index["aois"]}},
    )
    out_dir = Path(run_cfg["output_root"]) / f"{run_cfg['run_dir_prefix']}{ctx.run_id}"
    out_dir.mkdir(parents=True, exist_ok=False)
    computed_at = utc_now_iso()
    print(f"run_id={ctx.run_id}  out={out_dir}  aois={[a.id for a in aois]}  "
          f"unit=h3 r{spatial_cfg['spatial_unit']['h3_resolution']} ({spatial_cfg['spatial_unit'].get('decision_status')})")

    frames, coverage_rows, aoi_stats, conservation = [], [], {}, {}
    for aoi in aois:
        print(f"  {aoi.id} ...", flush=True)
        with ctx.stage(aoi_id=aoi.id, stage="provenance_verify") as s:
            rows = verify_aoi_sources(aoi.id, index, manifest_entries)
            s.rows = len(rows)
        inputs, stats = load_aoi_inputs(aoi, index, cfg, features_path, taxonomy_path, taxonomy,
                                        features_cfg, spatial_cfg, ctx)
        with ctx.stage(aoi_id=aoi.id, stage="features") as s:
            df = compute_aoi_features(inputs, cfg, spatial_cfg, features_cfg, taxonomy, ctx.run_id,
                                      index["aois"][aoi.id].get("acquisition_run_id"), computed_at)
            s.rows = len(df)
        with ctx.stage(aoi_id=aoi.id, stage="conservation_checks") as s:
            conservation[aoi.id] = conservation_checks(inputs, df)
            conservation[aoi.id]["worldpop_nodata"] = worldpop_nodata_decomposition(inputs, features_cfg)
            s.rows = len(df)
        frames.append(df)
        aoi_stats[aoi.id] = {**stats, "cells": int(len(df)), "metric_crs": aoi.metric_crs,
                             "aoi_checksum": aoi_checksum(aoi)}
        for r in rows:
            r.update({"run_id": ctx.run_id})
        coverage_rows.extend(rows)
        # Keep the per-AOI geometry for the GeoParquet companion.
        aoi_stats[aoi.id]["_units"] = inputs.units[["unit_id", "geometry", "area_m2", "aoi_overlap_fraction"]].assign(aoi_id=aoi.id)

    features_df = pd.concat(frames, ignore_index=True)
    if not features_df["spatial_unit_id"].is_unique:
        raise RuntimeError("a cell appears in more than one AOI; merge on spatial_unit_id before publishing")
    schema_report = validate_frame(features_df, features_cfg, spatial_cfg)
    # Raw-ratio audit: any UNMASKED ratio above 1 is recorded per cell; the
    # published ratio must still be inside [0, 1] (schema check) because
    # its numerator is masked, never clipped.
    ratio_audit = {
        "cells": {
            k: {"aoi_id": str(a), "built_up_ratio_unmasked": float(b), "built_up_ratio": _f(pb),
                "industrial_ratio_unmasked": _f(i), "osm_industrial_site_area_ratio": _f(pi),
                "industrial_area_m2_raw": _f(ir), "industrial_area_m2_on_land_support": _f(il),
                "valid_land_support_area_km2": _f(ls)}
            for k, a, b, pb, i, pi, ir, il, ls in zip(
                features_df["spatial_unit_id"], features_df["aoi_id"], features_df["_built_up_ratio_unmasked"],
                features_df["built_up_ratio"], features_df["_industrial_ratio_unmasked"],
                features_df["osm_industrial_site_area_ratio"], features_df["_industrial_area_m2_raw"],
                features_df["_industrial_area_m2_on_land_support"], features_df["valid_land_support_area_km2"])
            if (np.isfinite(b) and b > 1 + 1e-9) or (np.isfinite(i) and i > 1 + 1e-9)},
        "published_ratio_range_checks": {k: v for k, v in schema_report["checks"].items() if k.endswith("_in_unit_interval")},
    }

    with ctx.stage(aoi_id="", stage="write_outputs") as s:
        qa_cols = [c for c in features_df.columns if c.startswith("_")]
        public = features_df.drop(columns=qa_cols)
        public.to_parquet(out_dir / "atomic_features.parquet", index=False)
        units_all = pd.concat([v.pop("_units") for v in aoi_stats.values()], ignore_index=True)
        units_gdf = gpd.GeoDataFrame(units_all.rename(columns={"unit_id": "spatial_unit_id"}), geometry="geometry", crs="EPSG:4326")
        units_gdf["spatial_unit_area_km2"] = units_gdf.pop("area_m2") / 1e6
        units_gdf.to_parquet(out_dir / "spatial_units.parquet", index=False)
        coverage = pd.DataFrame(coverage_rows)
        coverage.to_parquet(out_dir / "source_coverage.parquet", index=False)
        write_aoi_geojson(aois, out_dir / "aois.geojson")
        s.rows = len(public)
        s.output_bytes = sum((out_dir / n).stat().st_size for n in ("atomic_features.parquet", "spatial_units.parquet"))

    manifest = feature_manifest(public, features_cfg, cfg)
    (out_dir / "feature_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True, default=_json_default))

    bench = pd.DataFrame(ctx.rows)
    ok_rows = bench[bench["status"] == "ok"]
    validation = {
        "run_id": ctx.run_id, "aois_expected": list(run_cfg["aoi_ids"]), "aois_computed": [a.id for a in aois],
        "full_mvp_run": [a.id for a in aois] == list(run_cfg["aoi_ids"]),
        "rows": int(len(public)), "schema": schema_report,
        "conservation": conservation,
        "conservation_passed": all(v[k]["passed"] for v in conservation.values() for k in ("population", "built_up_m2"))
                               and all(v["worldcover_rollups_within_valid_area"] and v["land_support_within_cell"]
                                       for v in conservation.values()),
        "per_aoi": per_aoi_summary(public, features_cfg),
        "ratio_audit": ratio_audit,
        "entity_assembly": {a: st["osm_entity_assembly"] for a, st in aoi_stats.items()},
        "aoi_stats": {a: {k: v for k, v in st.items() if k != "osm_entity_assembly"} for a, st in aoi_stats.items()},
        "distance_status_counts": {f: public[f"{f}_status"].value_counts().to_dict()
                                   for f in [c[:-7] for c in public.columns if c.startswith("distance_nearest") and c.endswith("_status")]},
        "runtime": {"wall_time_s_total": float(ok_rows["wall_time_s"].sum()),
                    "wall_time_s_by_stage": ok_rows.groupby("stage")["wall_time_s"].sum().to_dict(),
                    "wall_time_s_by_aoi": ok_rows.groupby("aoi_id")["wall_time_s"].sum().to_dict(),
                    "peak_rss_bytes": int(ok_rows["peak_rss_bytes"].max()) if len(ok_rows) else None},
        "storage_bytes": {n: (out_dir / n).stat().st_size for n in ("atomic_features.parquet", "spatial_units.parquet", "source_coverage.parquet")},
    }
    validation["passed"] = bool(schema_report["passed"] and validation["conservation_passed"] and validation["full_mvp_run"])
    (out_dir / "validation_summary.json").write_text(json.dumps(validation, indent=2, sort_keys=True, default=_json_default))
    bench.to_parquet(out_dir / "benchmark_runs.parquet", index=False)

    manifest_path = write_run_manifest(out_dir, ctx, {
        "gate": 3, "run_kind": "atomic_feature_mvp" if validation["full_mvp_run"] else "smoke",
        "config_path": str(config_path), "configs_hashed": [str(config_path), str(spatial_path), str(features_path), str(taxonomy_path)],
        "config_sha256": {str(p): sha256_of(p) for p in (config_path, spatial_path, features_path, taxonomy_path)},
        "spatial_unit": {k: spatial_cfg["spatial_unit"][k] for k in ("method", "h3_resolution", "decision_status", "decision_record")},
        "feature_set_version": str(features_cfg["feature_set_version"]),
        "feature_semantics": features_cfg["semantics"],
        "gate3_config_version": str(cfg.get("version")),
        "poi_taxonomy_version": str(taxonomy["version"]),
        "aois": [{"aoi_id": a.id, "context": a.context, "metric_crs": a.metric_crs, "checksum": aoi_checksum(a),
                  "source_manifest_id": index["aois"][a.id].get("acquisition_run_id"),
                  "acquisition_manifest": index["aois"][a.id].get("manifest_path")} for a in aois],
        "source_index": {"path": run_cfg["source_index"], "sha256": sha256_of(Path(run_cfg["source_index"]))},
        "sources": [{k: r[k] for k in ("aoi_id", "source_role", "source_id", "sha256", "release", "license_id")} for r in coverage_rows],
        "artifacts": {n: {"bytes": (out_dir / n).stat().st_size, "sha256": sha256_of(out_dir / n)}
                      for n in REQUIRED_OUTPUTS if n != "run_manifest.json"},
        "validation_passed": validation["passed"],
        "rows": int(len(public)),
    })
    sums = write_checksums(out_dir, [out_dir / n for n in REQUIRED_OUTPUTS] + [out_dir / "benchmark_runs.parquet"])
    assert verify_checksums(out_dir) == []
    print(f"\nrows={len(public)}  schema_passed={schema_report['passed']}  conservation_passed={validation['conservation_passed']}"
          f"\nmanifest: {manifest_path}\nchecksums: {sums}")
    return {"run_id": ctx.run_id, "out_dir": str(out_dir), "validation": validation}


def _f(v):
    try:
        return None if v is None or not np.isfinite(v) else float(v)
    except TypeError:
        return None


def _json_default(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if not np.isfinite(v) else float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (pd.DataFrame, gpd.GeoDataFrame)):
        return f"<{len(v)} rows>"
    return str(v)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Gate 3 atomic-feature MVP.")
    parser.add_argument("--aoi", action="append", default=None,
                        help="MVP AOI id (repeatable). Default: the four AOIs in config/gate3_mvp.yaml.")
    parser.add_argument("--config", type=Path, default=GATE3_CONFIG)
    args = parser.parse_args(argv)
    run(args.aoi, load_yaml(args.config), args.config)


if __name__ == "__main__":
    main()
