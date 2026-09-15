"""Gate 2 orchestration: one entry point that runs every enabled candidate
over every requested AOI and writes the versioned run directory.

    python -m src.spatial.run_gate2 --aoi hanoi_core          # smoke test
    python -m src.spatial.run_gate2                            # all 8 AOIs

Nothing here decides anything on its own. It measures, writes the artifacts
`docs/spatial_unit_decision.md` requires, applies the pre-registered
acceptance rules, and -- because `PROJECT_BRIEF.md` supplies no feasibility
budget -- reports a Pareto frontier instead of naming a single winner.
`config/spatial.yaml` is never written by this module.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

try:  # pragma: no cover - depends on which import root is active
    from .aoi import Aoi, aoi_checksum, load_aois, write_aoi_geojson
    from .benchmark import (RunContext, code_version, environment, hash_config,
                            sha256_of, write_run_manifest, write_table)
    from .candidates import SquareGrid, adjacent_pairs, build_candidates, origin_shift_replicates
    from . import metrics as M
except ImportError:  # pragma: no cover
    from spatial.aoi import Aoi, aoi_checksum, load_aois, write_aoi_geojson
    from spatial.benchmark import (RunContext, code_version, environment, hash_config,
                                   sha256_of, write_run_manifest, write_table)
    from spatial.candidates import (SquareGrid, adjacent_pairs, build_candidates,
                                    origin_shift_replicates)
    from spatial import metrics as M

GATE2_CONFIG = Path("config/gate2.yaml")
SPATIAL_CONFIG = Path("config/spatial.yaml")
SOURCE_INDEX = Path("data/gate2/aoi_sources/gate2_source_index.json")


def load_config(path: Path = GATE2_CONFIG) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _identity(aoi: Aoi, candidate) -> dict:
    return {"aoi_id": aoi.id, "context": aoi.context, "candidate_id": candidate.id,
            "family": candidate.family, "role": candidate.role}


def run_candidate(aoi: Aoi, candidate, data: M.AoiData, config: dict, ctx: RunContext,
                  out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, list[dict], M.UnitAggregates]:
    seed = int(config["run"]["random_seed"])
    ident = _identity(aoi, candidate)

    with ctx.stage(**ident, stage="generation") as s:
        units = candidate.units(aoi.polygon, aoi.metric_crs)
        s.rows = len(units)

    agg = M.aggregate_units(
        units, data, candidate, config,
        stage_fn=lambda name: ctx.stage(**ident, stage=name),
    )
    agg._nominal_km2 = candidate.nominal_area_km2

    rows: list[dict] = []
    rows += M.unit_count_and_area_rows(agg, aoi, config)
    rows += M.sparsity_rows(agg, data)
    rows += M.semantic_mixing_rows(agg)

    loss_rows, _ = M.within_unit_loss_rows(agg, data, config, seed)
    rows += loss_rows
    rows += M.neighborhood_representation_rows(agg, candidate, config, seed)

    replicates = None
    if isinstance(candidate, SquareGrid):
        replicates = origin_shift_replicates(candidate, config["boundary_sensitivity"]["origin_offset_fractions"])
    rows += M.boundary_sensitivity_rows(agg, data, candidate, config, seed, replicates)

    share, pair_count = M.indistinguishable_neighbor_share(agg, candidate, config)
    rows.append(M._row("indistinguishable_neighbor_pair_share", share, "share", M.BUFFER_1KM,
                       notes=f"{pair_count} adjacent pairs; tolerance "
                             f"{config['acceptance']['indistinguishable_relative_tolerance']}"))

    # --- storage ---------------------------------------------------------
    geom_dir = out_dir / "units" / aoi.id
    geom_dir.mkdir(parents=True, exist_ok=True)
    geom_path = geom_dir / f"{candidate.id}_geometry.parquet"
    feat_path = geom_dir / f"{candidate.id}_features.parquet"
    with ctx.stage(**ident, stage="storage_write") as s:
        units[["unit_id", "candidate_id", "family", "geometry"]].to_parquet(geom_path, index=False)
        pd.DataFrame({
            "unit_id": units["unit_id"], "area_m2": units["area_m2"],
            "aoi_overlap_fraction": units["aoi_overlap_fraction"],
            "land_fraction": agg.land_fraction, "poi_count": agg.poi_count,
            "population": agg.population, "road_length_m": agg.road_length_m,
            "intersection_count": agg.intersection_count,
            "landcover_entropy_bits": agg.landcover_entropy_bits,
            "landcover_dominant_share": agg.landcover_dominant_share,
            "builtup_fraction_mean": agg.builtup_fraction_mean,
            "builtup_fraction_variance": agg.builtup_fraction_variance,
            "neighbor_count": agg.neighbor_count,
            **{f"anchor_{k}": v for k, v in agg.anchors_at_rep.items()},
        }).to_parquet(feat_path, index=False)
        s.rows = len(units)
        s.output_bytes = geom_path.stat().st_size + feat_path.stat().st_size

    n = max(1, len(units))
    geom_bytes, feat_bytes = geom_path.stat().st_size, feat_path.stat().st_size
    land_units = float(np.nansum(np.asarray(agg.land_fraction) > 0))
    eff_land_km2 = float(np.nansum(units["area_m2"].to_numpy() / 1e6 * np.nan_to_num(agg.land_fraction)))
    nat_km2 = float(config["nationwide_projection"]["vietnam_land_area_km2"])
    projected_units = nat_km2 / (eff_land_km2 / land_units) if land_units and eff_land_km2 else np.nan

    rows += [
        M._row("storage_geometry_bytes", geom_bytes, "bytes", M.FOOTPRINT),
        M._row("storage_feature_bytes", feat_bytes, "bytes", M.FOOTPRINT),
        M._row("storage_bytes_per_unit", (geom_bytes + feat_bytes) / n, "bytes", M.FOOTPRINT),
        M._row("storage_nationwide_projected_bytes",
               (geom_bytes + feat_bytes) / n * projected_units, "bytes", M.FOOTPRINT,
               notes="projection from this AOI's bytes/unit and the projected national unit count"),
    ]

    # --- lookup ----------------------------------------------------------
    with ctx.stage(**ident, stage="lookup_benchmark") as s:
        lookup_rows = [dict(r, run_id=ctx.run_id, aoi_id=aoi.id, candidate_id=candidate.id)
                       for r in M.lookup_benchmark_rows(agg, data, candidate, config, seed)]
        s.rows = int(config["lookup"]["queries"])

    inventory = pd.DataFrame({
        "run_id": ctx.run_id, "aoi_id": aoi.id, "context": aoi.context,
        "candidate_id": candidate.id, "family": candidate.family, "role": candidate.role,
        "unit_id": units["unit_id"], "area_m2": units["area_m2"],
        "aoi_overlap_m2": units["aoi_overlap_m2"],
        "aoi_overlap_fraction": units["aoi_overlap_fraction"],
        "land_fraction": agg.land_fraction, "neighbor_count": agg.neighbor_count,
        "rep_lat": units["rep_lat"], "rep_lon": units["rep_lon"],
        # Carried alongside the inventory so the faceted maps plot from one
        # table rather than re-joining the per-candidate feature parquets.
        "poi_count": agg.poi_count, "population": agg.population,
        "road_length_m": agg.road_length_m,
        "landcover_entropy_bits": agg.landcover_entropy_bits,
        "builtup_fraction_mean": agg.builtup_fraction_mean,
    })
    metrics_df = pd.DataFrame([dict(r, run_id=ctx.run_id, **ident) for r in rows])
    return inventory, metrics_df, lookup_rows, agg


def run(aoi_ids: Optional[list[str]], out_root: Path, config: dict,
        source_index: Path = SOURCE_INDEX) -> dict:
    index = json.loads(source_index.read_text())
    aois = [a for a in load_aois() if aoi_ids is None or a.id in aoi_ids]
    missing = [a.id for a in aois if a.id not in index["aois"]]
    if missing:
        raise RuntimeError(f"no acquired sources for AOIs {missing}; run src.ingestion.acquire_gate2 first")

    manifest_entries = _load_acquisition_manifest(index)
    candidates = build_candidates(config)
    ctx = RunContext(
        run_id=pd.Timestamp.now("UTC").strftime("%Y%m%dT%H%M%SZ"),
        config_hash=hash_config(GATE2_CONFIG, SPATIAL_CONFIG),
        code_version=code_version(), environment=environment(),
        source_releases={"acquisition_manifest": index["manifest_path"],
                         "acquisition_run_id": index["run_id"]},
    )
    out_dir = out_root / f"run_{ctx.run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    aoi_path, aoi_sha = write_aoi_geojson(aois, out_dir / "aois.geojson")
    print(f"run_id={ctx.run_id}  out={out_dir}")
    print(f"candidates: {[c.id for c in candidates]}")

    inventories, metric_frames, lookup_rows, coverage_rows = [], [], [], []
    aggs: dict[tuple[str, str], M.UnitAggregates] = {}

    for aoi in aois:
        sources = index["aois"][aoi.id]
        if sources["aoi_checksum"] != aoi_checksum(aoi):
            raise RuntimeError(
                f"{aoi.id}: the AOI geometry changed since its sources were acquired "
                f"(checksum {aoi_checksum(aoi)} != acquired {sources['aoi_checksum']}). "
                f"Re-acquire rather than measuring one AOI against another's data."
            )
        with ctx.stage(aoi_id=aoi.id, candidate_id="", family="", role="", context=aoi.context,
                       stage="load_aoi_sources") as s:
            data = M.load_aoi_data(aoi, sources, config)
            s.rows = len(data.poi) + len(data.roads)
        coverage_rows.extend(_coverage_rows(ctx, aoi, sources, data, manifest_entries))

        for candidate in candidates:
            print(f"  {aoi.id} / {candidate.id} ...", flush=True)
            inv, met, lk, agg = run_candidate(aoi, candidate, data, config, ctx, out_dir)
            inventories.append(inv); metric_frames.append(met); lookup_rows.extend(lk)
            aggs[(aoi.id, candidate.id)] = agg

        for finer, coarser in adjacent_pairs(candidates):
            fa, ca = aggs.get((aoi.id, finer.id)), aggs.get((aoi.id, coarser.id))
            if fa is None or ca is None:
                continue
            with ctx.stage(aoi_id=aoi.id, candidate_id=finer.id, family=finer.family,
                           role=finer.role, context=aoi.context, stage="maup_stability") as s:
                rows = M.maup_rows(fa, ca, finer, coarser, data, config,
                                   int(config["run"]["random_seed"]))
                s.rows = len(rows)
            metric_frames.append(pd.DataFrame([
                dict(r, run_id=ctx.run_id, **_identity(aoi, finer)) for r in rows]))

        # Free the AOI's per-candidate aggregates before loading the next AOI.
        aggs = {k: v for k, v in aggs.items() if k[0] != aoi.id}

    inventory = pd.concat(inventories, ignore_index=True)
    metrics_df = pd.concat(metric_frames, ignore_index=True)
    bench = pd.DataFrame(ctx.rows)
    lookup = pd.DataFrame(lookup_rows)
    coverage = pd.DataFrame(coverage_rows)

    artifacts = [
        write_table(inventory, out_dir, "candidate_inventory"),
        write_table(metrics_df, out_dir, "candidate_metrics"),
        write_table(bench, out_dir, "benchmark_runs"),
        write_table(lookup, out_dir, "lookup_benchmark"),
        write_table(coverage, out_dir, "source_coverage"),
    ]

    try:
        from .decision import write_decision_matrix
        from .plots import write_plots
    except ImportError:  # pragma: no cover
        from spatial.decision import write_decision_matrix
        from spatial.plots import write_plots

    decision = write_decision_matrix(out_dir, metrics_df, bench, lookup, coverage, config,
                                     [c.id for c in candidates], [a.id for a in aois])
    plot_paths = write_plots(out_dir, metrics_df, inventory, config)

    manifest_path = write_run_manifest(out_dir, ctx, {
        "aois": [{"aoi_id": a.id, "context": a.context, "metric_crs": a.metric_crs,
                  "checksum": aoi_checksum(a), "bounds_wgs84": list(a.bounds)} for a in aois],
        "aoi_geojson": {"path": str(aoi_path), "sha256": aoi_sha},
        "candidates": [{"candidate_id": c.id, "family": c.family, "role": c.role,
                        "nominal_area_km2": c.nominal_area_km2} for c in candidates],
        "administrative_candidate": dict(config["candidates"]["administrative"]),
        "feasibility_budget": dict(config["feasibility_budget"]),
        "artifacts": artifacts,
        "decision": decision,
        "plots": [str(p) for p in plot_paths],
        "acquisition_source_index": {"path": str(source_index), "sha256": sha256_of(source_index)},
    })
    print(f"\nrun manifest: {manifest_path}")
    return {"run_id": ctx.run_id, "out_dir": str(out_dir), "decision": decision,
            "artifacts": artifacts}


def _load_acquisition_manifest(index: dict) -> dict[str, dict]:
    """source_id -> manifest entry, from the acquisition run(s) that produced
    these AOI subsets. Release, licence, URI, checksum and CRS all come from
    there rather than being retyped here. An AOI entry may name its own
    manifest (a partial re-acquisition); every referenced manifest is read."""
    cache: dict[str, dict[str, dict]] = {}

    def read(path: str) -> dict[str, dict]:
        if path not in cache:
            payload = json.loads(Path(path).read_text())
            cache[path] = {e["source_id"]: e for e in payload["sources"]}
        return cache[path]

    # Seed the shared/raw-source records from every referenced manifest.
    # Duplicate derived source ids are resolved explicitly below; their ids
    # are stable across re-acquisitions, so first/last-manifest-wins here
    # would silently attach stale provenance to a newly clipped raster.
    out: dict[str, dict] = {}
    top_path = index["manifest_path"]
    out.update(read(top_path))
    for aoi in index.get("aois", {}).values():
        out.update(read(aoi.get("manifest_path", top_path)))

    # The AOI's own manifest is authoritative for each derived source named
    # in that AOI's source-index entry. This matters after a partial
    # re-acquisition: the old and new manifests contain the same source_id
    # but different checksums/transforms (for example, a one-tile clip versus
    # its corrected two-tile mosaic).
    source_keys = ("roads_poi", "population", "land_cover", "built_up")
    for aoi_id, aoi in index.get("aois", {}).items():
        path = aoi.get("manifest_path", top_path)
        entries = read(path)
        for key in source_keys:
            if key not in aoi:
                continue
            source_id = aoi[key]["source_id"]
            if source_id not in entries:
                raise RuntimeError(
                    f"{aoi_id}/{key}: source {source_id!r} is absent from its "
                    f"acquisition manifest {path}"
                )
            out[source_id] = entries[source_id]
    return out


def _coverage_rows(ctx: RunContext, aoi: Aoi, sources: dict, data: M.AoiData,
                   manifest_entries: dict[str, dict]) -> list[dict]:
    """One `source_coverage` row per source role per AOI.

    `ingest_status` and the processing-coverage ratio are what separate a
    genuine mapped zero from an unavailable input: a role that failed to
    load never reaches the metric tables at all, and its failure is visible
    here instead of appearing downstream as sparsity.
    """
    by_role = {c["source_role"]: c for c in data.coverage}
    rows = []
    for role, key in (("poi_roads", "roads_poi"), ("population", "population"),
                      ("land_cover", "land_cover"), ("built_up", "built_up")):
        derived_id = sources[key]["source_id"]
        entry = manifest_entries.get(derived_id, {})
        parent = manifest_entries.get(entry.get("parent_source_id", ""), {})
        cov = by_role.get(role, {})
        expected = cov.get("expected_valid_pixels")
        processed = cov.get("processed_valid_pixels")
        ratio = (processed / expected) if (expected and processed is not None) else None
        rows.append({
            "run_id": ctx.run_id, "aoi_id": aoi.id, "source_role": role,
            "source_id": derived_id,
            "release": entry.get("release") or parent.get("release"),
            "license_id": entry.get("license_id") or parent.get("license_id"),
            "source_uri": parent.get("source_uri") or entry.get("source_uri"),
            "retrieved_at_utc": entry.get("retrieved_at_utc"),
            "sha256": entry.get("sha256") or sources[key].get("sha256"),
            "bytes": entry.get("bytes") or sources[key].get("bytes"),
            "crs": entry.get("crs"),
            "bounds": json.dumps(entry.get("bounds")),
            "expected_assets": json.dumps(entry.get("expected_assets", [derived_id])),
            "present_assets": json.dumps(entry.get("present_assets", [derived_id])),
            "expected_valid_pixels": expected,
            "processed_valid_pixels": processed,
            "processing_coverage": ratio,
            "ingest_status": cov.get("ingest_status", "ok"),
            "notes": "; ".join(filter(None, [
                cov.get("notes", ""),
                f"parent={entry.get('parent_source_id')}",
                f"transform={json.dumps(entry.get('transform'))}" if entry.get("transform") else "",
            ])),
        })
    return rows


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Gate 2 spatial-unit experiment.")
    parser.add_argument("--aoi", action="append", default=None,
                        help="AOI id (repeatable). Default: every AOI in config/spatial.yaml.")
    parser.add_argument("--config", type=Path, default=GATE2_CONFIG)
    parser.add_argument("--source-index", type=Path, default=SOURCE_INDEX)
    args = parser.parse_args(argv)

    config = load_config(args.config)
    run(args.aoi, Path(config["run"]["output_root"]), config, args.source_index)


if __name__ == "__main__":
    main()
