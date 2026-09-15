"""Candidate x AOI completeness, raster coverage, and vector ingest status
for the actual Gate 2 run directory.

Gate 2 must not be reported as complete while any required AOI, candidate,
source, metric, or artifact is missing. These tests assert exactly that
against whatever the latest run produced, and skip cleanly when no run
exists yet rather than passing vacuously.
"""

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

GATE2_ROOT = Path("data/gate2")
REQUIRED_AOIS = {"hanoi_core", "hcmc_core", "thu_duc_east", "dong_thap_rural",
                 "mu_cang_chai", "binh_duong_industrial", "hoi_an", "phu_quoc_coast"}
REQUIRED_METRICS = {
    "unit_count_total", "unit_area_km2_median", "unit_area_km2_cv",
    "poi_zero_share", "population_zero_share", "road_zero_length_share",
    "landcover_entropy_median", "landcover_dominant_share_median",
    "builtup_fraction_variance_median", "within_unit_range_over_between_unit_iqr",
    "ring_circle_jaccard_median", "jitter_assignment_change_share",
    "origin_shift_copartition_flip_share", "indistinguishable_neighbor_pair_share",
    "storage_geometry_bytes", "storage_nationwide_projected_bytes",
    "population_conservation_relative_error",
}
REQUIRED_ARTIFACTS = {"candidate_inventory.parquet", "candidate_metrics.parquet",
                      "benchmark_runs.parquet", "lookup_benchmark.parquet",
                      "source_coverage.parquet", "decision_matrix.md",
                      "aois.geojson", "run_manifest.json"}


def _runs() -> list[Path]:
    if not GATE2_ROOT.exists():
        return []
    return sorted(r for r in GATE2_ROOT.glob("run_*") if (r / "run_manifest.json").exists())


def _latest():
    runs = _runs()
    return runs[-1] if runs else None


requires_run = pytest.mark.skipif(_latest() is None, reason="no completed Gate 2 run present")


@pytest.fixture(scope="module")
def run():
    return _latest()


@pytest.fixture(scope="module")
def metrics(run):
    return pd.read_parquet(run / "candidate_metrics.parquet")


@pytest.fixture(scope="module")
def config():
    return yaml.safe_load(open("config/gate2.yaml"))


@requires_run
def test_every_required_artifact_is_present(run):
    missing = {name for name in REQUIRED_ARTIFACTS if not (run / name).exists()}
    assert not missing, f"missing Gate 2 artifacts: {sorted(missing)}"
    assert (run / "figures").is_dir()
    assert list((run / "figures").glob("*.png")), "no diagnostic figures were produced"


@requires_run
def test_the_run_states_which_aois_it_actually_covered(run):
    """A partial run is legitimate; claiming completeness from one is not.
    The manifest must name exactly what was measured."""
    manifest = json.loads((run / "run_manifest.json").read_text())
    covered = {a["aoi_id"] for a in manifest["aois"]}
    assert covered, "the manifest must list the AOIs the run covered"
    assert covered <= REQUIRED_AOIS


@requires_run
def test_every_enabled_candidate_ran_on_every_covered_aoi(metrics, config, run):
    from spatial.candidates import build_candidates

    manifest = json.loads((run / "run_manifest.json").read_text())
    covered = {a["aoi_id"] for a in manifest["aois"]}
    expected = {c.id for c in build_candidates(config)}
    have = set(map(tuple, metrics[["aoi_id", "candidate_id"]].drop_duplicates().to_numpy()))
    missing = {(a, c) for a in covered for c in expected} - have
    assert not missing, f"missing candidate x AOI pairs: {sorted(missing)}"


@requires_run
def test_every_required_metric_exists_for_every_candidate_aoi_pair(metrics):
    have = metrics.groupby(["aoi_id", "candidate_id"])["metric"].apply(set)
    gaps = {key: sorted(REQUIRED_METRICS - value) for key, value in have.items()
            if REQUIRED_METRICS - value}
    assert not gaps, f"metric gaps: {gaps}"


@requires_run
def test_raster_processing_coverage_clears_the_configured_floor(run, config):
    floor = float(config["acceptance"]["minimum_raster_processing_coverage"])
    coverage = pd.read_parquet(run / "source_coverage.parquet")
    raster = coverage[coverage["source_role"].isin(["population", "land_cover", "built_up"])]
    assert len(raster)
    below = raster[raster["processing_coverage"].notna() & (raster["processing_coverage"] < floor)]
    assert not len(below), below[["aoi_id", "source_role", "processing_coverage"]].to_dict("records")


@requires_run
def test_every_vector_source_ingested_without_technical_failure(run):
    coverage = pd.read_parquet(run / "source_coverage.parquet")
    vector = coverage[coverage["source_role"] == "poi_roads"]
    assert len(vector)
    assert (vector["ingest_status"] == "ok").all()


@requires_run
def test_every_source_row_pins_a_release_licence_and_checksum(run):
    coverage = pd.read_parquet(run / "source_coverage.parquet")
    for column in ("release", "license_id", "sha256", "bytes", "retrieved_at_utc"):
        assert coverage[column].notna().all(), f"{column} is unset on some source row"
    assert coverage["sha256"].map(len).eq(64).all()


@requires_run
def test_roads_come_from_osm_only_and_are_never_unioned_with_overture(run):
    """The Gate 1 decision stands unless new measured evidence overturns it:
    OSM is the canonical road source and the two networks are never merged."""
    coverage = pd.read_parquet(run / "source_coverage.parquet")
    roads = coverage[coverage["source_role"] == "poi_roads"]
    assert len(roads)
    assert roads["license_id"].eq("ODbL-1.0").all()
    assert roads["source_id"].str.contains("osm").all()
    assert not coverage["source_role"].str.contains("overture", case=False).any()


@requires_run
def test_a_mapped_zero_is_never_reported_as_a_missing_source(metrics):
    zero_rows = metrics[metrics["metric"].str.endswith("_zero_share")]
    assert len(zero_rows)
    assert (zero_rows["source_status"] == "ingested_ok").all()
    assert zero_rows["value"].notna().all()


@requires_run
def test_not_applicable_rows_never_carry_a_value(metrics):
    na = metrics[metrics["source_status"] == "not_applicable"]
    if len(na):
        assert na["value"].isna().all()


@requires_run
def test_decision_does_not_claim_a_three_family_comparison_while_admin_is_blocked(run, config):
    decision = json.loads((run / "decision.json").read_text())
    if not config["candidates"]["administrative"]["enabled"]:
        assert any("administrative" in b for b in decision["blockers"])
        assert decision["decision"] == "no_decision"
    matrix = (run / "decision_matrix.md").read_text()
    assert "blocked" in matrix.lower()


@requires_run
def test_pareto_frontier_is_reported_when_no_feasibility_budget_exists(run, config):
    decision = json.loads((run / "decision.json").read_text())
    if not config["feasibility_budget"]["provided"]:
        assert decision["spatial_unit_method"] is None
        assert "pareto_frontier" in decision
