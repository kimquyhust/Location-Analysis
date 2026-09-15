"""Gate 2 MVP: which provisional H3 resolution the MVP uses (r8, r9 or r10).

    python -m src.spatial.run_gate2_mvp                 # all four MVP AOIs
    python -m src.spatial.run_gate2_mvp --aoi hanoi_core  # smoke (cannot decide)

Owner-approved scope reduction, recorded in `docs/gate2_mvp_decision.md`:
H3 is the provisional MVP family; this runner measures the minimum metric
set over the four representative AOIs, applies the pre-registered
too-coarse rule mechanically, and records a provisional selection or an
explicit NO DECISION. The full-experiment runner `run_gate2.py` and its
outputs are untouched; nothing here writes `config/spatial.yaml`.

Every metric function is shared with the full runner (`metrics.py`), so
the MVP numbers are the same measurements on the same code paths -- only
the candidate set, AOI set, and the list of metrics emitted are reduced.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml

try:  # pragma: no cover - depends on which import root is active
    from .aoi import Aoi, aoi_checksum, load_aois, write_aoi_geojson
    from .benchmark import (RunContext, code_version, environment, hash_config, sha256_of,
                            write_run_manifest, write_table)
    from .candidates import H3Grid
    from . import metrics as M
    from .mvp_decision import write_mvp_decision
    from .mvp_plots import write_mvp_figures
    from .run_gate2 import SOURCE_INDEX, SPATIAL_CONFIG, _coverage_rows, _load_acquisition_manifest
except ImportError:  # pragma: no cover
    from spatial.aoi import Aoi, aoi_checksum, load_aois, write_aoi_geojson
    from spatial.benchmark import (RunContext, code_version, environment, hash_config, sha256_of,
                                   write_run_manifest, write_table)
    from spatial.candidates import H3Grid
    from spatial import metrics as M
    from spatial.mvp_decision import write_mvp_decision
    from spatial.mvp_plots import write_mvp_figures
    from spatial.run_gate2 import SOURCE_INDEX, SPATIAL_CONFIG, _coverage_rows, _load_acquisition_manifest

MVP_CONFIG = Path("config/gate2_mvp.yaml")

REQUIRED_OUTPUTS = [
    "aois.geojson", "candidate_inventory.parquet", "candidate_metrics.parquet",
    "benchmark_runs.parquet", "lookup_benchmark.parquet", "source_coverage.parquet",
    "decision.json", "decision_matrix.md", "run_manifest.json",
    "figures/fig_unit_count_storage.png", "figures/fig_sparsity.png",
    "figures/fig_within_cell_loss.png", "figures/fig_runtime_lookup.png",
]


def load_config(path: Path = MVP_CONFIG) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def build_mvp_candidates(config: dict) -> list[H3Grid]:
    """Only the configured H3 resolutions. The family is asserted so a
    config edit cannot quietly reintroduce a deferred family into an MVP
    run that claims to compare resolutions only."""
    family = config["candidates"]["family"]
    if family != "h3":
        raise ValueError(f"the MVP run evaluates the h3 family only; config names {family!r}")
    return [H3Grid(resolution=int(r)) for r in sorted(config["candidates"]["h3_resolutions"])]


def mvp_aois(config: dict, aoi_ids: Optional[list[str]] = None) -> list[Aoi]:
    wanted = list(config["aoi"]["mvp_aoi_ids"])
    if aoi_ids is not None:
        unknown = set(aoi_ids) - set(wanted)
        if unknown:
            raise ValueError(f"{sorted(unknown)} are not MVP AOIs; the MVP set is {wanted}")
        wanted = [a for a in wanted if a in aoi_ids]
    by_id = {a.id: a for a in load_aois()}
    return [by_id[a] for a in wanted]


def _identity(aoi: Aoi, candidate) -> dict:
    return {"aoi_id": aoi.id, "context": aoi.context, "candidate_id": candidate.id,
            "family": candidate.family, "role": candidate.role}


def run_candidate(aoi: Aoi, candidate: H3Grid, data: M.AoiData, config: dict, ctx: RunContext,
                  out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    seed = int(config["run"]["random_seed"])
    ident = _identity(aoi, candidate)

    with ctx.stage(**ident, stage="generation") as s:
        units = candidate.units(aoi.polygon, aoi.metric_crs)
        s.rows = len(units)

    agg = M.aggregate_units(units, data, candidate, config,
                            stage_fn=lambda name: ctx.stage(**ident, stage=name))
    agg._nominal_km2 = candidate.nominal_area_km2

    rows: list[dict] = []
    rows += M.unit_count_and_area_rows(agg, aoi, config)
    rows += M.sparsity_rows(agg, data)
    with ctx.stage(**ident, stage="within_unit_loss") as s:
        loss_rows, _ = M.within_unit_loss_rows(agg, data, config, seed)
        s.rows = len(units)
    rows += loss_rows

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
            **{f"anchor_{k}": v for k, v in agg.anchors_at_rep.items()},
        }).to_parquet(feat_path, index=False)
        s.rows = len(units)
        s.output_bytes = geom_path.stat().st_size + feat_path.stat().st_size

    n = max(1, len(units))
    geom_bytes, feat_bytes = geom_path.stat().st_size, feat_path.stat().st_size
    projected = next(r["value"] for r in rows if r["metric"] == "unit_count_nationwide_projected")
    projected = projected if projected is not None and np.isfinite(projected) else np.nan
    rows += [
        M._row("storage_geometry_bytes", geom_bytes, "bytes", M.FOOTPRINT),
        M._row("storage_feature_bytes", feat_bytes, "bytes", M.FOOTPRINT),
        M._row("storage_bytes_per_unit", (geom_bytes + feat_bytes) / n, "bytes", M.FOOTPRINT),
        M._row("storage_geometry_nationwide_projected_bytes", geom_bytes / n * projected, "bytes", M.FOOTPRINT,
               notes="PROJECTION: this AOI's geometry bytes/unit x projected national unit count"),
        M._row("storage_feature_nationwide_projected_bytes", feat_bytes / n * projected, "bytes", M.FOOTPRINT,
               notes="PROJECTION: this AOI's feature bytes/unit x projected national unit count"),
        M._row("storage_nationwide_projected_bytes", (geom_bytes + feat_bytes) / n * projected, "bytes",
               M.FOOTPRINT, notes="PROJECTION: geometry + features"),
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
        "aoi_overlap_m2": units["aoi_overlap_m2"], "aoi_overlap_fraction": units["aoi_overlap_fraction"],
        "land_fraction": agg.land_fraction, "neighbor_count": agg.neighbor_count,
        "rep_lat": units["rep_lat"], "rep_lon": units["rep_lon"],
        "poi_count": agg.poi_count, "population": agg.population, "road_length_m": agg.road_length_m,
    })
    metrics_df = pd.DataFrame([dict(r, run_id=ctx.run_id, **ident) for r in rows])
    return inventory, metrics_df, lookup_rows


def write_checksums(out_dir: Path, paths: list[Path]) -> Path:
    """`SHA256SUMS` in the `sha256sum -c` format, paths relative to the run
    directory, sorted so the file itself is reproducible."""
    lines = []
    for p in sorted(set(paths), key=lambda p: str(p.relative_to(out_dir))):
        lines.append(f"{sha256_of(p)}  {p.relative_to(out_dir).as_posix()}")
    path = out_dir / "SHA256SUMS"
    path.write_text("\n".join(lines) + "\n")
    return path


def verify_checksums(out_dir: Path) -> list[str]:
    """Names of every listed file whose current checksum differs (or that is
    missing). Empty means the run directory is intact."""
    bad = []
    for line in (out_dir / "SHA256SUMS").read_text().splitlines():
        digest, _, rel = line.partition("  ")
        p = out_dir / rel
        if not p.exists() or sha256_of(p) != digest:
            bad.append(rel)
    return bad


def run(aoi_ids: Optional[list[str]], config: dict, source_index: Path = SOURCE_INDEX,
        config_path: Path = MVP_CONFIG) -> dict:
    index = json.loads(source_index.read_text())
    aois = mvp_aois(config, aoi_ids)
    missing = [a.id for a in aois if a.id not in index["aois"]]
    if missing:
        raise RuntimeError(f"no acquired sources for AOIs {missing}; run src.ingestion.acquire_gate2 first")
    expected_aois = list(config["aoi"]["mvp_aoi_ids"])

    manifest_entries = _load_acquisition_manifest(index)
    candidates = build_mvp_candidates(config)
    ctx = RunContext(
        run_id=pd.Timestamp.now("UTC").strftime("%Y%m%dT%H%M%SZ"),
        config_hash=hash_config(config_path, SPATIAL_CONFIG),
        code_version=code_version(), environment=environment(),
        source_releases={"acquisition_source_index": str(source_index),
                         **{a: index["aois"][a].get("acquisition_run_id", index["run_id"]) for a in expected_aois
                            if a in index["aois"]}},
    )
    out_root = Path(config["run"]["output_root"])
    out_dir = out_root / f"{config['run']['run_dir_prefix']}{ctx.run_id}"
    out_dir.mkdir(parents=True, exist_ok=False)

    aoi_path, aoi_sha = write_aoi_geojson(aois, out_dir / "aois.geojson")
    print(f"run_id={ctx.run_id}  out={out_dir}")
    print(f"candidates: {[c.id for c in candidates]}  aois: {[a.id for a in aois]}")

    inventories, metric_frames, lookup_rows, coverage_rows = [], [], [], []
    for aoi in aois:
        sources = index["aois"][aoi.id]
        if sources["aoi_checksum"] != aoi_checksum(aoi):
            raise RuntimeError(
                f"{aoi.id}: the AOI geometry changed since its sources were acquired "
                f"(checksum {aoi_checksum(aoi)} != acquired {sources['aoi_checksum']})")
        for role in ("land_cover", "built_up", "population"):
            cov = sources[role].get("coverage")
            if not cov or not (cov.get("window_inside_tile_union") and cov.get("window_covered_by_clip")):
                raise RuntimeError(
                    f"{aoi.id}/{role}: the acquired clip carries no coverage proof "
                    f"(window inside tile union + window covered by clip); re-acquire with the "
                    f"multi-tile acquisition before measuring")
        with ctx.stage(aoi_id=aoi.id, candidate_id="", family="", role="", context=aoi.context,
                       stage="load_aoi_sources") as s:
            data = M.load_aoi_data(aoi, sources, config)
            s.rows = len(data.poi) + len(data.roads)
        coverage_rows.extend(_coverage_rows(ctx, aoi, sources, data, manifest_entries))

        for candidate in candidates:
            print(f"  {aoi.id} / {candidate.id} ...", flush=True)
            inv, met, lk = run_candidate(aoi, candidate, data, config, ctx, out_dir)
            inventories.append(inv); metric_frames.append(met); lookup_rows.extend(lk)

    inventory = pd.concat(inventories, ignore_index=True)
    metrics_df = pd.concat(metric_frames, ignore_index=True)
    bench = pd.DataFrame(ctx.rows)
    lookup = pd.DataFrame(lookup_rows)
    coverage = pd.DataFrame(coverage_rows)
    # Carry the acquisition-time coverage proof onto the source rows, so a
    # reader of source_coverage.parquet sees which tiles served each clip.
    coverage["window_inside_tile_union"] = [
        bool(index["aois"][r["aoi_id"]].get(_ROLE_KEY[r["source_role"]], {}).get("coverage", {}).get("window_inside_tile_union", False))
        if r["source_role"] in _ROLE_KEY else None for _, r in coverage.iterrows()]
    coverage["window_covered_by_clip"] = [
        bool(index["aois"][r["aoi_id"]].get(_ROLE_KEY[r["source_role"]], {}).get("coverage", {}).get("window_covered_by_clip", False))
        if r["source_role"] in _ROLE_KEY else None for _, r in coverage.iterrows()]
    coverage["edge_full_nodata"] = [
        json.dumps(index["aois"][r["aoi_id"]].get(_ROLE_KEY[r["source_role"]], {}).get("coverage", {}).get("edge_full_nodata"))
        if r["source_role"] in _ROLE_KEY else None for _, r in coverage.iterrows()]
    coverage["source_tiles"] = [
        json.dumps(index["aois"][r["aoi_id"]].get(_ROLE_KEY[r["source_role"]], {}).get("transform", {}).get("source_tiles"))
        if r["source_role"] in _ROLE_KEY else None for _, r in coverage.iterrows()]

    artifacts = [
        write_table(inventory, out_dir, "candidate_inventory"),
        write_table(metrics_df, out_dir, "candidate_metrics"),
        write_table(bench, out_dir, "benchmark_runs"),
        write_table(lookup, out_dir, "lookup_benchmark"),
        write_table(coverage, out_dir, "source_coverage"),
    ]

    decision = write_mvp_decision(out_dir, metrics_df, bench, lookup, config,
                                  [c.id for c in candidates], expected_aois, ctx.run_id)
    figure_paths = write_mvp_figures(out_dir, metrics_df, bench, lookup, config)

    manifest_path = write_run_manifest(out_dir, ctx, {
        "run_kind": "mvp_resolution_decision",
        "scope_override": "docs/gate2_mvp_decision.md",
        "config_path": str(config_path),
        "aois": [{"aoi_id": a.id, "context": a.context, "metric_crs": a.metric_crs,
                  "checksum": aoi_checksum(a), "bounds_wgs84": list(a.bounds)} for a in aois],
        "aois_expected": expected_aois,
        "aoi_geojson": {"path": str(aoi_path), "sha256": aoi_sha},
        "candidates": [{"candidate_id": c.id, "family": c.family, "role": c.role,
                        "resolution": c.resolution, "nominal_area_km2": c.nominal_area_km2} for c in candidates],
        "artifacts": artifacts,
        "decision": {k: decision[k] for k in ("decision", "selected_candidate", "selected_h3_resolution",
                                              "selection_rule_fired", "decision_status", "verdicts")},
        "figures": [str(p) for p in figure_paths],
        "acquisition_source_index": {"path": str(source_index), "sha256": sha256_of(source_index)},
    })

    checksummed = [out_dir / rel for rel in REQUIRED_OUTPUTS] + list((out_dir / "units").rglob("*.parquet"))
    sums = write_checksums(out_dir, checksummed)
    print(f"\nrun manifest: {manifest_path}\nchecksums: {sums}\n"
          f"decision: {decision['decision']} -> {decision['selected_candidate']} "
          f"(rule {decision['selection_rule_fired']})")
    return {"run_id": ctx.run_id, "out_dir": str(out_dir), "decision": decision, "artifacts": artifacts}


_ROLE_KEY = {"population": "population", "land_cover": "land_cover", "built_up": "built_up"}


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Gate 2 MVP H3-resolution decision.")
    parser.add_argument("--aoi", action="append", default=None,
                        help="MVP AOI id (repeatable). Default: the four MVP AOIs in config/gate2_mvp.yaml. "
                             "A subset is a smoke run and cannot select a resolution.")
    parser.add_argument("--config", type=Path, default=MVP_CONFIG)
    parser.add_argument("--source-index", type=Path, default=SOURCE_INDEX)
    args = parser.parse_args(argv)
    run(args.aoi, load_config(args.config), args.source_index, args.config)


if __name__ == "__main__":
    main()
