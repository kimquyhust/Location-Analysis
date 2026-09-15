"""Artifact schemas, completeness checks, and the Gate 2 decision rules.

The schema tests run without a Gate 2 run directory; the ones that inspect
real output skip cleanly when no run has been produced yet, so the suite is
meaningful both before and after an experiment runs.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from spatial.benchmark import REQUIRED_SCHEMAS, SchemaError, RunContext, write_table
from spatial.decision import (build_objectives, completeness_gate, pareto_frontier)

GATE2_ROOT = Path("data/gate2")


def _latest_run() -> Path | None:
    runs = sorted(GATE2_ROOT.glob("run_*")) if GATE2_ROOT.exists() else []
    complete = [r for r in runs if (r / "run_manifest.json").exists()]
    return complete[-1] if complete else None


requires_run = pytest.mark.skipif(_latest_run() is None, reason="no completed Gate 2 run present")


# --- schema contract ------------------------------------------------------

def test_every_required_artifact_has_a_registered_schema():
    assert set(REQUIRED_SCHEMAS) == {
        "candidate_inventory", "candidate_metrics", "benchmark_runs",
        "lookup_benchmark", "source_coverage",
    }


def test_write_table_rejects_a_frame_missing_required_columns(tmp_path):
    bad = pd.DataFrame({"run_id": ["r"], "aoi_id": ["a"]})
    with pytest.raises(SchemaError, match="missing required columns"):
        write_table(bad, tmp_path, "candidate_metrics")


def test_write_table_records_bytes_and_checksum(tmp_path):
    cols = {c: ["x"] for c in REQUIRED_SCHEMAS["lookup_benchmark"]}
    record = write_table(pd.DataFrame(cols), tmp_path, "lookup_benchmark")
    assert record["rows"] == 1
    assert record["bytes"] > 0
    assert len(record["sha256"]) == 64
    assert (tmp_path / "lookup_benchmark.parquet").exists()


def test_benchmark_row_carries_the_metadata_every_run_must_state():
    ctx = RunContext(run_id="r1", config_hash="h", code_version="c",
                     environment={"python": "3.12"}, source_releases={"x": "y"})
    with ctx.stage(aoi_id="a", candidate_id="square_500m", stage="generation") as s:
        s.rows = 10
    row = ctx.rows[0]
    for field in ("run_id", "config_hash", "code_version", "wall_time_s", "peak_rss_bytes",
                  "rows", "status", "source_releases", "env_python"):
        assert field in row, field
    assert row["rows"] == 10
    assert row["wall_time_s"] >= 0
    assert row["status"] == "ok"


def test_a_failing_stage_is_recorded_as_failed_and_the_error_propagates():
    ctx = RunContext(run_id="r", config_hash="h", code_version="c", environment={},
                     source_releases={})
    with pytest.raises(ValueError):
        with ctx.stage(aoi_id="a", candidate_id="c", stage="generation"):
            raise ValueError("boom")
    assert ctx.rows[0]["status"] == "failed"
    assert "boom" in ctx.rows[0]["notes"]


# --- decision rules -------------------------------------------------------

def test_completeness_gate_fails_on_a_missing_candidate_aoi_pair():
    metrics = pd.DataFrame({"aoi_id": ["a1"], "candidate_id": ["c1"], "metric": ["x"], "value": [1.0]})
    coverage = pd.DataFrame({"source_role": [], "processing_coverage": [], "ingest_status": []})
    config = yaml.safe_load(open("config/gate2.yaml"))
    result = completeness_gate(metrics, coverage, config, ["c1", "c2"], ["a1"])
    assert not result["passed"]
    assert ("a1", "c2") in result["missing_candidate_aoi_pairs"]


def test_completeness_gate_fails_when_raster_coverage_is_below_the_floor():
    config = yaml.safe_load(open("config/gate2.yaml"))
    metrics = pd.DataFrame({"aoi_id": ["a1"], "candidate_id": ["c1"], "metric": ["x"], "value": [1.0]})
    coverage = pd.DataFrame({"source_role": ["population"], "processing_coverage": [0.90],
                             "ingest_status": ["ok"]})
    result = completeness_gate(metrics, coverage, config, ["c1"], ["a1"])
    assert not result["passed"]
    assert result["raster_rows_below_floor"] == 1


def test_completeness_gate_fails_on_a_vector_ingest_failure():
    config = yaml.safe_load(open("config/gate2.yaml"))
    metrics = pd.DataFrame({"aoi_id": ["a1"], "candidate_id": ["c1"], "metric": ["x"], "value": [1.0]})
    coverage = pd.DataFrame({"source_role": ["poi_roads"], "processing_coverage": [None],
                             "ingest_status": ["failed"]})
    result = completeness_gate(metrics, coverage, config, ["c1"], ["a1"])
    assert not result["passed"]
    assert result["vector_ingest_failures"] == 1


def test_pareto_frontier_marks_a_dominated_candidate():
    frame = pd.DataFrame({
        "candidate_id": ["good", "bad", "tradeoff"],
        "cost": [1.0, 2.0, 5.0],
        "error": [1.0, 2.0, 0.1],
    })
    out = pareto_frontier(frame).set_index("candidate_id")
    assert out.loc["good", "pareto_status"] == "nondominated"
    assert out.loc["bad", "pareto_status"] == "dominated"
    assert out.loc["tradeoff", "pareto_status"] == "nondominated"


def test_pareto_frontier_never_imputes_a_missing_objective():
    frame = pd.DataFrame({"candidate_id": ["a", "b"], "cost": [1.0, np.nan], "error": [1.0, 1.0]})
    out = pareto_frontier(frame).set_index("candidate_id")
    assert out.loc["b", "pareto_status"] == "undetermined"
    assert not out.loc["b", "pareto_nondominated"]


def test_no_feasibility_budget_means_no_decision():
    """Acceptance rule 6: with no owner budget, Gate 2 reports a frontier
    and must not manufacture a single best candidate."""
    config = yaml.safe_load(open("config/gate2.yaml"))
    assert config["feasibility_budget"]["provided"] is False
    for key in ("max_wall_time_s", "max_peak_rss_bytes", "max_nationwide_storage_bytes"):
        assert config["feasibility_budget"][key] is None


def test_spatial_config_method_is_null_or_an_explicitly_provisional_mvp_selection():
    """The full experiment (admin blocked, no budget) cannot set a method.
    The owner-approved MVP override (docs/gate2_mvp_decision.md) can set
    one -- but only as a PROVISIONAL selection that names its decision
    record and keeps nationwide validation and the family comparison
    explicitly pending. A bare `method: h3` with no such labelling would
    present the override as a research result."""
    spatial = yaml.safe_load(open("config/spatial.yaml"))
    gate2 = yaml.safe_load(open("config/gate2.yaml"))
    admin_blocked = not gate2["candidates"]["administrative"]["enabled"]
    no_budget = not gate2["feasibility_budget"]["provided"]
    unit = spatial["spatial_unit"]
    if unit["method"] is None:
        assert unit["h3_resolution"] is None
        assert unit["square_grid_size_m"] is None
        return
    assert admin_blocked or no_budget  # the full experiment did not close
    assert unit["decision_status"] == "provisional_mvp"
    assert unit["nationwide_validation_pending"] is True
    assert unit["full_family_comparison_deferred"] is True
    assert Path(unit["decision_record"]).exists()
    assert unit["method"] == "h3" and isinstance(unit["h3_resolution"], int)
    assert unit["square_grid_size_m"] is None


def test_gate2_config_mirrors_the_spatial_config_acceptance_thresholds():
    spatial = yaml.safe_load(open("config/spatial.yaml"))["gate2_acceptance"]
    gate2 = yaml.safe_load(open("config/gate2.yaml"))["acceptance"]
    for key, value in spatial.items():
        assert gate2[key] == value, f"{key}: {gate2.get(key)} != {value}"


def test_gate2_config_mirrors_the_spatial_config_candidate_matrix():
    spatial = yaml.safe_load(open("config/spatial.yaml"))["gate2_candidates"]
    gate2 = yaml.safe_load(open("config/gate2.yaml"))["candidates"]
    configured = {int(s["size_m"]) for s in gate2["square_m"]}
    expected = set(spatial["square_grid_operational_m"]) | set(spatial["square_grid_h3_area_controls_m"])
    assert configured == expected
    assert gate2["h3_resolutions"] == spatial["h3"]["resolutions"]


# --- real run output ------------------------------------------------------

@requires_run
def test_written_artifacts_satisfy_their_declared_schemas():
    run = _latest_run()
    for name, required in REQUIRED_SCHEMAS.items():
        path = run / f"{name}.parquet"
        assert path.exists(), f"{name}.parquet missing from {run}"
        df = pd.read_parquet(path)
        assert required - set(df.columns) == set(), f"{name} missing {required - set(df.columns)}"
        assert len(df) > 0, f"{name} is empty"


@requires_run
def test_run_manifest_records_identity_and_checksums():
    manifest = json.loads((_latest_run() / "run_manifest.json").read_text())
    for field in ("run_id", "config_hash", "code_version", "environment", "source_releases",
                  "aois", "candidates", "artifacts", "decision", "aoi_geojson"):
        assert field in manifest, field
    assert len(manifest["aoi_geojson"]["sha256"]) == 64
    for art in manifest["artifacts"]:
        assert len(art["sha256"]) == 64 and art["bytes"] > 0


@requires_run
def test_aoi_geometry_checksums_are_recorded_for_every_aoi():
    manifest = json.loads((_latest_run() / "run_manifest.json").read_text())
    for aoi in manifest["aois"]:
        assert len(aoi["checksum"]) == 64
        assert aoi["metric_crs"].startswith("EPSG:")


@requires_run
def test_population_counts_are_conserved_in_the_real_run():
    metrics = pd.read_parquet(_latest_run() / "candidate_metrics.parquet")
    err = metrics[metrics["metric"] == "population_conservation_relative_error"]["value"]
    assert len(err)
    assert err.max() < 1e-9, "reprojection/aggregation did not preserve population counts"


@requires_run
def test_every_metric_row_declares_a_spatial_support():
    metrics = pd.read_parquet(_latest_run() / "candidate_metrics.parquet")
    assert metrics["spatial_support"].notna().all()
    assert set(metrics["spatial_support"].unique()) <= {
        "unit_footprint", "buffer_1km", "buffer_3km", "not_applicable"}


@requires_run
def test_h3_origin_shift_is_recorded_as_not_applicable_not_as_a_pass():
    metrics = pd.read_parquet(_latest_run() / "candidate_metrics.parquet")
    h3_origin = metrics[(metrics["family"] == "h3")
                        & (metrics["metric"] == "origin_shift_copartition_flip_share")]
    assert len(h3_origin)
    assert (h3_origin["source_status"] == "not_applicable").all()
    assert h3_origin["value"].isna().all(), "H3 must not be scored on a test it cannot run"


@requires_run
def test_lookup_is_correct_on_interior_points_for_every_candidate():
    lookup = pd.read_parquet(_latest_run() / "lookup_benchmark.parquet")
    single = lookup[lookup["lookup_mode"] == "single"]
    assert len(single)
    assert (single["correctness_failures"] == 0).all()
    assert (single["errors"] == 0).all(), "lookup must be deterministic"


@requires_run
def test_decision_keeps_method_null_while_blockers_remain():
    decision = json.loads((_latest_run() / "decision.json").read_text())
    if decision["blockers"]:
        assert decision["decision"] == "no_decision"
        assert decision["spatial_unit_method"] is None
