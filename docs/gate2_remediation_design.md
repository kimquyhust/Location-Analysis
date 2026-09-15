# Gate 2 Remediation Design — validation and decision methodology

_Status: **design only, authoritative for the Gate 2 remediation.** Written 2026-09-14 against run `run_20260914T091321Z`, the current working tree (`59fe994+dirty`), and the artifacts on disk. Nothing in this document selects a spatial unit, changes `config/spatial.yaml`, touches `docs/architecture.md`, or starts Gate 3. The pre-registered experiment in [`spatial_unit_decision.md`](spatial_unit_decision.md) is preserved unchanged; everything added here is labelled **remediation** (a correction to measurement or decision logic) or **sensitivity** (an addition that may inform interpretation but never the pre-registered decision rules)._

**Gate 2 state as of this document: `incomplete`.** The run produced substantial, largely reusable evidence, but its validation layer cannot support the completion claims made in `spatial_unit_decision.md` § Measured results. Section 13 sets out exactly which of that run's numbers survive and which are withdrawn.

---

## 0. How to read this document

| Section | What it fixes | Review finding |
|---|---|---|
| 1 | Verified findings, classified | all |
| 2 | Gate 2 state machine | 10 |
| 3 | Metric contract (machine-readable completeness) | 4, 6 |
| 4 | Artifact contract | 4, 9, 10 |
| 5 | Coverage algorithm that can fail | 3 |
| 6 | Robustness algorithm with pseudocode | 1 |
| 7 | Hard-gate and Pareto ordering; what a budget-less run can conclude | 5, 7 |
| 8 | Alternate-source sensitivity plan | 2 |
| 9 | Built-up fine-resolution validity policy | 6 |
| 10 | Visualization contract | 9 |
| 11 | Reproducibility and manifest schema | 10 |
| 12 | Work packages for implementation | — |
| 13 | Invalidation policy for `run_20260914T091321Z` | — |
| 14 | Reviewer acceptance checklist | — |
| 15 | Summary and handoff | — |

Vocabulary used throughout. Every measured quantity carries a **validity** state, never a bare null:

| validity | meaning | value column |
|---|---|---|
| `measured` | computed from a successfully ingested source; a zero here is a real mapped zero | non-null |
| `not_applicable` | structurally cannot exist for this candidate (H3 has no grid origin) | null |
| `not_evaluable` | exists in principle but a declared eligibility rule was not met (too few pixels, degenerate IQR, fewer than three eligible candidates) | null, `validity_reason` set |
| `blocked` | the required input is unavailable (source not acquired, tile missing, ingest failed) | null, `validity_reason` set |

`not_applicable`, `not_evaluable` and `blocked` are **never** a pass. A gate that depends on such a row is itself `not_evaluable` or `blocked`, and the run cannot leave the `incomplete` state on that gate's account.

---

## 1. Verified findings

Every finding in the review brief was checked against the code and the artifacts on disk, not accepted from the brief. Two things were found that the brief did not name (F3a, F3b). Classification: **blocking** = Gate 2 cannot close until fixed; **important** = must be fixed in the remediation run but would not on its own invalidate the measured evidence; **rejected** = the finding as stated is wrong or already satisfied, with the reason.

### 1.1 Blocking

| id | finding | verdict | evidence |
|---|---|---|---|
| **F1** | `robustness_gate()` compares baseline ranks across contexts, not ranks before/after perturbation | **confirmed** | `src/spatial/decision.py:128-158`. The gate ranks candidates by baseline `within_unit_range_over_between_unit_iqr` per AOI, takes the median rank across AOIs, and counts AOIs where a candidate's baseline rank sits more than 2 positions from that median. `jitter_assignment_change_share` and `origin_shift_copartition_flip_share` are carried as columns and never enter `passed`. The "> 2 positions" threshold appears in no pre-registered rule. No perturbed candidate ranking exists anywhere in the artifacts: origin-shift replicates were used only for point co-partition flips and a single-anchor Spearman, and jitter was used only for assignment change. The "PASS for all" in `spatial_unit_decision.md` therefore rests on a statistic that does not test the rule. |
| **F2** | Alternate population / built-up sensitivity was not executed | **confirmed** | No row in `candidate_metrics.parquet` carries any source variant; `source_coverage.parquet` has one population source (`worldpop2025`) and one built-up source (`ghs_built_s` E2020) per AOI. `spatial_unit_decision.md` limitation 9 admits this while its acceptance table records rule 5 as PASS. |
| **F3** | Raster processing coverage is tautological | **confirmed, and worse than stated** | `metrics.py:157-164` sets `expected_valid_pixels = valid_pixels = len(vals)` from one read. `_zonal_builtup` (`metrics.py:443-444`) computes `coverage = expected_valid / expected_valid`. `_zonal_class_stats` (`metrics.py:394-396`) compares `inside.sum()` with `(zones > 0).sum()`, the same array. Land-cover source coverage is `width*height / width*height` (`metrics.py:240-245`). The comment at `metrics.py:437-441` records that an earlier, non-tautological check "tripped exactly once, on mu_cang_chai at h3_r7" and was then redefined rather than investigated. F3a and F3b are what it was detecting. |
| **F3a** (new) | `mu_cang_chai` built-up clip is a truncated window, not "mountain-terrain NoData" | **confirmed by inspection** | `data/gate2/aoi_sources/mu_cang_chai/ghs_built_s.tif`: 292 × 241 pixels, 9,640 NoData pixels, and **all 9,640 are the 40 westernmost columns (x < 9,959,000 m Mollweide) — zero NoData elsewhere in the window**. The requested window (`bbox` in the derived sidecar) spans x = 9,955,082–9,984,184, which straddles GHSL tiles R7_C28 (x < 9,959,000) and R7_C29. `acquire_gate2.py::acquire_all` selects one tile per AOI from the halo **centre** (`ghsl_tile_id(clon, clat)`), so only C29 was clipped although C28 was downloaded (`required_tiles` uses the corners and the manifest lists `ghs_built_s_e2020_r2023a_r7_c28`). `gdal_translate -projwin` filled the out-of-tile strip with NoData. The AOI polygon itself begins 753 m east of the truncation edge, so unit footprints inside the AOI are unaffected, but (i) `h3_r7`'s 1.19 % "NoData in units" is entirely this strip, (ii) the 1 km `builtup_fraction_1km` anchor for west-edge units reads missing pixels as zero built-up (`metrics.py:247-250` divides by the full disk area), and (iii) `spatial_unit_decision.md` states as a source characteristic something that is an acquisition defect. |
| **F3b** (new) | `hanoi_core` land-cover clip is a truncated window | **confirmed by inspection** | `data/gate2/aoi_sources/hanoi_core/worldcover.tif`: 1,420 × 1,511 pixels; the bottom **374 rows (3.4 km, lat < 21.0°) are entirely NoData (class 0) and there is no class-0 pixel above them**. The AOI's south edge is at 21.00075° — 83 m from the N21E105/N18E105 tile line — and the halo extends to 20.969°. N18E105 was downloaded and never clipped in. `_zonal_class_stats` includes class 0 in the class shares, so entropy and dominant share are contaminated for every unit overlapping the strip: 5 of 15 `h3_r7` units (15.5 % of unit area), 4 of 12 `square_2270m`, 7 of 49 `square_1000m`, 8 of 64 `square_850m`. The contamination is monotone in unit size, so it biases the semantic-mixing axis of the Pareto frontier against coarse candidates in one AOI. Reported coverage: 1.000. `tests/test_gate2_aoi.py::test_worldcover_and_ghsl_tile_ids_are_computed_not_hardcoded` even asserts `worldcover_tile_id(20.9689, 105.852) == "N18E105"` with the comment "a halo edge crossing a tile line" — the crossing was known and the clip path ignored it. |
| **F4** | No machine-readable completeness contract; POI leaf categories missing rather than zero | **confirmed** | `completeness_gate()` checks only pair presence. `aggregate_units` emits POI category rows for `sorted(set(cats))` observed in the AOI (`metrics.py:473-477`): `mu_cang_chai` has 9 of 25 dimensions, `dong_thap_rural` 20, `hoi_an` 21 (measured from the parquet). A category absent from an AOI has no row; `zero_share = 1.0` is never written. Per-category zero share exists only on the unit footprint, not on the 1 km support. `jitter_feature_rank_*` does not exist. One-ring neighbourhood area/CV does not exist. No uniqueness key is enforced (none of the 12,686 rows is duplicated today, but nothing would fail if one were). |
| **F7** | Pareto frontier computed over all candidates including hard-gate rejects | **confirmed** | `build_objectives` / `pareto_frontier` in `decision.py:161-217` and `write_decision_matrix` never filter by gate outcome; the "live region" in the decision doc is a manual intersection performed in prose. |
| **F10** | Reproducibility: code and config not preserved | **confirmed** | Manifest `code_version` is `59fe994cacf930df79d9b364fe104f1778d41f47+dirty`; every `src/spatial/*.py` file is untracked, so the commit contains none of the code that ran. The recorded `config_hash dde7c4a1…` was reconstructable only by forensics in this review (it equals `hash_config` over the current untracked `config/gate2.yaml` and `HEAD:config/spatial.yaml`; the working-tree `spatial.yaml` has since changed and now hashes to `6340b956…`). No dependency lock exists (`pyproject.toml` has ranges; no `uv.lock`). Only the five primary Parquet files and `aois.geojson` are checksummed; the 176 per-candidate unit Parquets, 46 figures, `decision.json` and `decision_matrix.md` are not. `run_gate2.run` creates the run directory with `exist_ok=True`, writes the manifest only at the end, has no status field, and a `--aoi hanoi_core` smoke run lands in the same `data/gate2/run_*` namespace, where `tests/test_gate2_completeness.py::_latest()` would pick it up as "the" run and pass (it checks only the AOIs the manifest says it covered). |

### 1.2 Important, non-blocking

| id | finding | verdict | evidence |
|---|---|---|---|
| **F5** | Too-coarse rule branch 2 (dominant land-cover degradation vs both adjacent finer scales without material feasibility benefit) not applied | **confirmed** | `coarse_gate()` reads only `too_coarse_anchor_features_triggered`. Non-blocking because branch 1 is the binding branch for every candidate the run rejected, but branch 2 is pre-registered and must be evaluated and reported before rule 3 can be called applied. |
| **F6** | Within-unit built-up variance undefined for ~53 % of `square_125m` and ~35 % of `h3_r10` units | **confirmed** | `builtup_variance_undefined_share` medians over AOIs: `square_125m` 0.531, `h3_r10` 0.354, all others 0.000. A 125 m cell holds 1.56 GHS-BUILT-S 100 m pixels on average, `h3_r10` 1.72; even `square_250m` holds ~6. Medians of a sample variance from n ≤ 6 are not comparable with medians from n ≥ 100. Non-blocking for the decision because built-up variance is neither a Pareto objective nor a gate input in the current code, but it is a pre-registered metric and its headline value is misleading. |
| **F8** | Square area controls sized against global H3 averages; Vietnamese cells 14.3 % larger | **confirmed** | `unit_area_actual_over_nominal` = 1.1430 for r8–r10, 1.1429 for r7 (CV ≈ 0.0003). Locally matched sides `round(1000·sqrt(nominal_km² × 1.1430))` = 131, 347, 918, 2,429 m — the values in the brief are correct. The pre-registered controls must stay; the local ones are a labelled sensitivity set (§ 7.5). |
| **F9** | `map_unit_boundaries_*` plot unit centres | **confirmed** | `plots.py::_unit_boundary_facets` calls `ax.scatter(rep_lon, rep_lat)`; the suptitle even says "Unit centres". No road-sparsity, semantic-mixing, within-unit-loss, or origin-sensitivity maps exist (figure list in the run manifest: `map_unit_boundaries`, `map_poi_count`, `map_population`, `map_land_fraction` × 8 AOIs, plus 14 plots). `test_every_required_artifact_is_present` asserts only that some `*.png` exists. |
| **F11** (new) | Class-0 (NoData) WorldCover pixels enter entropy/dominant share; missing built-up pixels enter the 1 km anchor as zero | **confirmed** | `metrics.py:374-388` (no exclusion of `WORLDCOVER_NODATA` from the share matrix); `metrics.py:247-250`. Harmless once F3a/F3b are fixed and no genuine NoData exists in a window, but the semantics must be explicit: NoData is excluded from shares and reported as its own row. |
| **F12** (new) | `within_unit_range_over_between_unit_iqr` silently treats a degenerate IQR as "not triggered" | **confirmed in code, not exercised in this run** | `metrics.py:796-803`: `ratio = nan` when `iqr <= 0`, and `triggered = False`. No AOI produced a zero IQR in this run (checked), but the policy must be `not_evaluable` with the anchor excluded from the evaluable count. |

### 1.3 Rejected (as stated) or already satisfied

| id | finding fragment | verdict | reason |
|---|---|---|---|
| F4-c | "Jaccard and area error for 1 km and 3 km representations" missing | **rejected** | `ring_circle_jaccard_median`, `ring_circle_jaccard_p05`, `ring_circle_best_k_median`, `ring_circle_relative_area_error_median` exist for `buffer_1km` and `buffer_3km` on all 88 pairs. They enter the contract in § 3 as already-satisfied requirements. |
| F4-d | "neighborhood degree distribution" missing | **partially rejected** | `neighbor_degree_{min,p05,median,mean,p95,max,cv}` exist on all 88 pairs. The full per-degree share histogram does not; § 3 adds it. |
| F4-h | "lookup and benchmark completeness" missing | **rejected as a data gap, accepted as a contract gap** | `lookup_benchmark.parquet` has 2 rows × 88 pairs with 0 failures; `benchmark_runs.parquet` has 784 rows = 8 `load_aoi_sources` + 88 × 8 stages + 72 `maup_stability`, all `ok`. Nothing checks that expected stage set per pair, so § 3 adds the contract. |
| — | "212 passing tests" implies validation | **rejected as evidence** | The count is real, but the run-dependent tests validate the artifacts against the same tautological quantities (`test_raster_processing_coverage_clears_the_configured_floor` asserts a ratio that is 1.0 by construction) and would pass on a one-AOI smoke run. |
| — | H3 origin sensitivity currently treated as a pass | **rejected** | The run records H3 origin rows as `source_status = not_applicable`, value null, and `robustness_gate` sets `origin_shift_applicable = False`. The treatment is correct in the artifacts; what is wrong is that the gate's `passed` never consulted any perturbation for any candidate (F1). § 6 keeps not-applicable semantics and makes the verdict per perturbation kind. |

### 1.4 Remediation parameters declared before the rerun

These are the only numbers this design introduces. They are declared here, dated, and must be copied verbatim into `config/gate2.yaml: remediation_parameters` with `declared_on: 2026-09-14` before any rerun. They are eligibility and tolerance parameters, not acceptance thresholds; every pre-registered threshold in `spatial_unit_decision.md` is unchanged.

| parameter | value | used by | rationale |
|---|---|---|---|
| `coverage.window_inside_tile_union_required` | `true` | § 5 | a truncated window is a missing input, never a source characteristic |
| `coverage.min_processing_ratio` | `0.999` | § 5 | unchanged pre-registered floor, now applied to independently derived counts |
| `coverage.max_area_bound_relative_error` | `0.02` | § 5 | geometric pixel-count bound tolerance (perimeter effect at 10 m/100 m) |
| `robustness.tie_relative_tolerance` | `0.05` | § 6 | pairs within 5 % are ties; matches `indistinguishable_relative_tolerance` already declared |
| `robustness.min_eligible_candidates` | `3` | § 6 | a ranking over fewer than three candidates has no reversal structure |
| `robustness.max_contexts_with_reversal` | `1` | § 6 | pre-registered rule 5 ("more than one context") |
| `too_coarse.branch2_cost_ratio_max` | `2.0` | § 7.2 | reuses `fine_cost_multiplier_vs_next_coarser`; no new number |
| `too_coarse.branch2_min_relative_improvement` | `0.05` | § 7.2 | reuses `fine_minimum_error_improvement`; no new number |
| `builtup_variance.min_valid_pixels_median` | `9` | § 9 | relative SE of a sample variance ≈ √(2/(n−1)) = 0.5 at n = 9 |
| `context_unit_for_gates` | `aoi_id` | § 6, § 7 | the decision doc already treats each AOI as a context; `tourism` has two AOIs |
| `area_control_local.sides_m` | `[131, 347, 918, 2429]` | § 7.5 | derived from measured actual/nominal 1.1430; sensitivity set, never operational |

---

## 2. Gate 2 state machine

A Gate 2 **measurement run** has exactly one terminal state. **Decision evaluation** is a pure function of a terminal measurement run plus a decision configuration (which may later include an owner budget) and is stored outside the run directory (§ 11.6) so that a budget arriving after the run does not require re-measurement and does not mutate an immutable run.

```
planned ──start──▶ running ──┬──exception──────────────────────────▶ failed
                             ├──contract unmet (§3, §5, §6 inputs)──▶ incomplete
                             ├──contract met, blocker present───────▶ executed_no_decision
                             └──contract met, no blocker, one pick──▶ complete_selected
```

| state | entry condition | mandatory manifest fields | what may be claimed |
|---|---|---|---|
| `planned` | config snapshot and metric contract exist; no run directory | — | nothing |
| `running` | run directory created (`exist_ok=False`), `run_manifest.json` written **at start** with `status: running`, lock file present | `run_id`, `run_kind`, `started_at_utc`, `config_snapshot`, `code_snapshot`, `environment` | nothing |
| `failed` | any uncaught exception, or a `benchmark_runs` row with `status = failed` | `failure_reason`, `failed_at_stage` | nothing; artifacts retained for diagnosis |
| `incomplete` | run finished executing but `completeness_report.json` lists ≥ 1 unmet requirement (missing/duplicate metric key, coverage below floor, truncated window, blocked sensitivity source, robustness `not_evaluable`) | `incomplete_requirements: [ {requirement_id, reason, affected_keys} ]` | measured rows may be cited as **diagnostic evidence** with the run status named; no gate result, no frontier, no "live region" |
| `executed_no_decision` | completeness contract fully met; too-coarse, too-fine and robustness evaluated for every operational candidate with a verdict from {pass, fail, not_applicable-with-applicable-kinds-passed} (no `blocked`/`not_evaluable`); feasibility either applied or `not_evaluable:no_owner_budget`; eligible Pareto set computed; ≥ 1 declared blocker (`administrative_family_blocked`, `no_owner_feasibility_budget`) | `blockers`, `eligible_candidates`, `decision_frontier`, `budget_breakpoints` | everything measured, gate outcomes, the eligible frontier, budget breakpoints; **not** a selection |
| `complete_selected` | as above, no blocker, feasibility budget applied, selection rule yields exactly one candidate | `selected_candidate`, `selection_trace` | a selection; `config/spatial.yaml` may then be updated in a separate, owner-approved commit |

Rules:

1. A terminal state is immutable. Re-evaluating a decision with a new budget produces a new **decision record** (§ 11.6), not a new state on the old run.
2. `run_kind ∈ {smoke, full, sensitivity}`. Only `run_kind = full` with all 8 AOIs and all `operational` + `area_control` candidates can reach `executed_no_decision` or `complete_selected`. A `full` run that covers fewer AOIs or candidates is `incomplete` by construction with reason `scope_short`.
3. The **Gate 2 state** is the state of the most recent valid `full` run as listed in `data/gate2/run_registry.json` (§ 13). Today that is `incomplete` (the only full run is invalidated).
4. `spatial.yaml: gate2_experiment.status` must equal the registry state. Today it says `executed_no_decision`; WP0 changes it to `incomplete` (this is a status correction, not a method choice).

---

## 3. Metric contract

### 3.1 Row schema for `candidate_metrics.parquet` (v2)

| column | type | notes |
|---|---|---|
| `run_id` | str | |
| `run_kind` | str | smoke / full / sensitivity |
| `aoi_id`, `context` | str | |
| `candidate_id`, `family`, `role` | str | role ∈ operational / area_control / area_control_local / origin_replicate |
| `candidate_set` | str | `operational` (operational + pre-registered area controls) or `sensitivity` (local area controls) |
| `perturbation_kind` | str | `baseline` / `origin_shift` / `jitter` / `population_source` / `population_epoch` / `builtup_source` |
| `perturbation_id` | str | `baseline`, `origin_off0.5x0`, `origin_off0x0.5`, `origin_off0.5x0.5`, `jitter_seed20260914`, `pop_ghspop2020`, `pop_worldpop2020`, `bu_worldcover50` |
| `source_variant` | str | `primary` / `worldpop_2020` / `ghspop_2020` / `worldcover_builtup_2021` |
| `metric`, `dimension`, `spatial_support` | str | dimension `""` when the metric has none; support ∈ unit_footprint / buffer_1km / buffer_3km / not_applicable |
| `value` | float64 | null iff `validity != measured` |
| `unit` | str | |
| `validity` | str | measured / not_applicable / not_evaluable / blocked |
| `validity_reason` | str | required when validity ≠ measured; from the declared reason codes (§ 3.4) |
| `source_status` | str | ingested_ok / ingest_failed / not_acquired / truncated |
| `notes` | str | |

**Uniqueness key:** `(run_id, aoi_id, candidate_id, perturbation_id, source_variant, metric, dimension, spatial_support)`. `write_table` rejects a frame with a duplicate key (`SchemaError`), and `completeness_gate` fails on duplicates in a read table.

### 3.2 The contract file

`config/gate2_metric_contract.yaml` (new, versioned, snapshotted into every run). The completeness gate is `expand(contract, candidates, aois, taxonomy) → expected key set`, then set arithmetic against the table. Shape:

```yaml
version: "2.0.0"
dimension_sets:
  poi_categories:
    from: config/poi_taxonomy.yaml
    key: canonical_categories          # the 24 leaves
    plus: [all_categories]             # → 25 dimensions
  anchors:
    from: config/gate2.yaml
    key: anchor_features               # 4 ids
    plus: [all_anchors]                # the median over anchors (§ 6)
  maup_features: [population_density_per_km2, poi_density_per_km2]
  degrees_square: [0,1,2,3,4,5,6,7,8]
  degrees_h3: [0,1,2,3,4,5,6]
candidate_sets:
  operational: {roles: [operational, area_control]}
  sensitivity: {roles: [area_control_local]}
requirements:
  - id: poi_zero_share
    metric: poi_zero_share
    dimensions: $poi_categories
    supports: [unit_footprint, buffer_1km]
    source_role: poi
    applies_to: {families: [square, h3], candidate_sets: [operational, sensitivity]}
    perturbations: [baseline, jitter, origin_shift]
    allowed_validity: [measured]
    absent_category_policy: measured_zero_share_one   # absent leaf ⇒ value 1.0, not a missing row
    acceptance: informational
  - id: origin_shift_copartition_flip_share
    metric: origin_shift_copartition_flip_share
    supports: [unit_footprint]
    applies_to: {families: [square]}
    not_applicable_for: {families: [h3]}               # row required, validity=not_applicable
    perturbations: [baseline]
    allowed_validity: [measured]
  ...
```

Cardinality is derived, never typed by hand: each requirement expands to `|dimensions| × |supports| × |applicable candidates| × |aois| × |perturbation ids for its kinds|` keys. `completeness_report.json` records, per requirement: `expected`, `present`, `missing`, `duplicate`, `wrong_validity`, `blocked`, `not_evaluable_with_reason`.

### 3.3 Contract table

Support codes: F = unit_footprint, B1 = buffer_1km, B3 = buffer_3km. Applicability: **all** = every candidate in `operational` and `sensitivity` sets; **sq** = square family only (H3 row required with `not_applicable`); **pairs** = one row per adjacent same-family pair, attached to the finer candidate, `operational` set only. Perturbation kinds (P): b = baseline, o = origin_shift (squares), j = jitter, p = population_source (+ population_epoch, diagnostic), u = builtup_source. "Required" = allowed validity for completeness. Acceptance behaviour: **info** = reported; **gate** = feeds a hard gate; **obj** = Pareto objective; **cov** = completeness/coverage gate input.

| # | metric | dimensions | support | source role | applies | P | required validity | acceptance |
|---|---|---|---|---|---|---|---|---|
| A1 | `unit_count_total`, `unit_count_land_intersecting`, `unit_count_nationwide_projected`, `effective_land_area_km2` | — | F | geometry (+land_cover for land) | all | b, o | measured | info; unit count is the cost proxy in § 7.2 |
| A2 | `unit_area_km2_{min,p05,median,mean,p95,max,cv}`, `unit_area_nominal_km2`, `unit_area_actual_over_nominal` | — | F | geometry | all | b | measured | info; ordering axis |
| B1 | `poi_zero_share` | 25 (24 leaves + all) | F, B1 | poi | all | b, j, o | measured; **absent leaf ⇒ 1.0** | info; `all_categories`/F is obj and robustness metric |
| B2 | `poi_total` | 25 | F | poi | all | b, j, o | measured (0 allowed) | info |
| B3 | `poi_leaf_universe_size` | — | F | poi | all | b | measured = 24 | cov (guards the universe) |
| C1 | `population_zero_share`, `population_p10`, `population_median` | — | F | population | all | b, o, p | measured | info; zero share is robustness metric |
| C2 | `population_source_total`, `population_assigned_total`, `population_unassigned_total`, `population_in_aoi_total`, `population_outside_unit_coverage_share`, `population_unit_coverage_over_aoi_ratio` | — | F | population | all | b, o, p | measured | info |
| C3 | `population_conservation_relative_error` | — | F | population | all | b, o, p | measured, **< 1e-9** | cov |
| D1 | `road_zero_length_share`, `road_length_total_m`, `road_zero_intersection_share` | — | F | roads | all | b, o | measured | info |
| D2 | `road_length_conservation_relative_error` (new: in-unit + outside-unit vs halo-clipped total) | — | F | roads | all | b, o | measured, < 1e-6 | cov |
| E1 | `landcover_entropy_{q}`, `landcover_dominant_share_{q}` (q = min,p05,median,mean,p95,max,cv) | — | F | land_cover | all | b, o | measured | `dominant_share_median` is gate (§ 7.2), obj, robustness metric |
| E2 | `landcover_nodata_pixel_share_in_units` (new; class 0 excluded from shares) | — | F | land_cover | all | b, o | measured, must equal the publisher-NoData share (§ 5) | cov |
| E3 | `builtup_fraction_mean_{q}` | — | F | built_up | all | b, o, u | measured | info |
| E4 | `builtup_fraction_variance_{q}` | — | F | built_up (100 m) | all | b, o | measured **or** `not_evaluable:builtup_support_below_min` (§ 9) | info only; never obj/gate |
| E5 | `builtup_variance_undefined_share`, `builtup_variance_eligible_unit_share`, `builtup_pixels_per_unit_median` (last two new) | — | F | built_up | all | b, o | measured | info; drives E4 validity |
| E6 | `builtup10m_fraction_mean_{q}`, `builtup10m_fraction_variance_{q}` (new, § 9) | — | F | built_up_alt (WorldCover class 50) | all | b, o | measured | info; supplementary |
| F1 | `within_unit_median_range`, `between_unit_iqr`, `within_unit_range_over_between_unit_iqr` | 5 (4 anchors + `all_anchors` median) | B1 | anchors (poi, population, roads, built_up) | all | b, o, j, p, u | measured or `not_evaluable:degenerate_iqr` | **gate** (rule 3 branch 1), obj, robustness metric |
| F2 | `too_coarse_anchor_features_triggered`, `too_coarse_anchor_features_evaluable` (new) | — | B1 | anchors | all | b, o, j, p, u | measured | gate |
| G1 | `neighbor_degree_{q}` | — | F | geometry | all | b | measured | info |
| G2 | `neighbor_degree_share` (new) | degree k (0–8 sq, 0–6 h3) | F | geometry | all | b | measured (0 allowed; every k row present) | info |
| G3 | `one_ring_area_km2_median`, `one_ring_area_km2_cv`, `one_ring_complete_unit_share` (new) | — | F | geometry | all | b | measured | info |
| G4 | `ring_circle_jaccard_median`, `ring_circle_jaccard_p05`, `ring_circle_best_k_median`, `ring_circle_relative_area_error_median` | — | B1, B3 | geometry | all | b | measured | obj (1 − Jaccard) |
| H1 | `jitter_assignment_change_share`, `jitter_distance_m` | — | F | geometry | all | b | measured | info |
| H2 | `jitter_feature_rank_spearman` (new) | 4 anchors | B1 | anchors | all | b | measured | info; robustness diagnostic |
| H3 | `origin_shift_copartition_flip_share`, `_max`, `origin_shift_assignment_change_share` | — | F | geometry | sq | b | measured (sq) / not_applicable (h3) | info |
| H4 | `origin_shift_feature_rank_spearman` | 4 anchors (was: poi only) | B1 | anchors | sq | b | measured (sq) / not_applicable (h3) | info |
| I1 | `maup_spearman`, `maup_median_abs_percent_change`, `maup_top_decile_jaccard` | feature\|pair | F | population, poi | pairs | b, p (population feature only) | measured | info |
| J1 | `indistinguishable_neighbor_pair_share` | — | B1 | anchors | all | b, p, u | measured | gate (rule 4) |
| K1 | `storage_geometry_bytes`, `storage_feature_bytes`, `storage_bytes_per_unit`, `storage_nationwide_projected_bytes` | — | F | artifacts | all | b | measured | obj, gate (rule 4), § 7.2 |
| L1 | `builtup_source_agreement_spearman`, `population_source_agreement_spearman` (new: per-unit rank agreement primary vs alternate) | — | F | built_up/population | all | b | measured or blocked | info; § 8 |
| M1 | `lookup_benchmark.parquet`: rows for `single` and `batch` per pair; `correctness_failures = 0`, `errors = 0` | — | — | geometry | all | b | present | cov |
| M2 | `benchmark_runs.parquet`: stages {generation, point_assignment, road_clipping, raster_zonal_stats, poi_buffer_aggregation, neighbor_construction, storage_write, lookup_benchmark} per pair, `maup_stability` per pair-of-candidates per AOI, `load_aoi_sources` per AOI × source variant; all `status = ok` | — | — | — | all | b, o, j, p, u | present, ok | cov, obj (runtime) |

Rows under perturbation kinds other than baseline are required only for the metrics whose row lists that kind. The expansion is exact, so a perturbation that was silently skipped shows up as `missing` keys, not as an absent column.

### 3.4 Declared `validity_reason` codes

`degenerate_iqr`, `builtup_support_below_min`, `fewer_than_min_eligible_candidates`, `no_grid_origin` (not_applicable), `source_not_acquired`, `tile_missing`, `window_truncated`, `ingest_failed`, `crs_transform_mismatch`, `scope_short`. Any other string fails validation.

---

## 4. Artifact contract

Run directory `data/gate2/run_<run_id>/` (full and sensitivity runs) or `data/gate2/smoke/run_<run_id>/` (smoke). `run_id = <UTC %Y%m%dT%H%M%SZ>_<6 hex from os.urandom>`.

| path | required | schema / content | checksummed in manifest |
|---|---|---|---|
| `run_manifest.json` | yes | § 11.1 | self (excluding its own hash field) |
| `RUN_LOCK` | while running | pid, hostname, started_at | — |
| `SHA256SUMS` | at finalize | one line per file under the run dir except itself and `run_manifest.json` | yes |
| `config_snapshot/{gate2.yaml,spatial.yaml,poi_taxonomy.yaml,gate2_metric_contract.yaml}` + `sha256sums.txt` | yes | byte-exact copies | yes |
| `code_snapshot/{git_commit.txt,git_status_porcelain.txt,tracked.patch,untracked.tar.gz,code_tree_sha256.txt,file_hashes.json}` | yes | § 11.2 | yes |
| `environment/{pip_freeze.txt,platform.json,native_libs.json,cli_versions.json}` | yes | § 11.3 | yes |
| `aois.geojson` | yes | unchanged | yes |
| `candidate_inventory.parquet` | yes | v1 columns + `candidate_set`, `landcover_dominant_share`, `builtup_pixels`, `landcover_nodata_pixels`, `builtup10m_fraction_mean`, `within_unit_loss_all_anchors` (null for unsampled units), `origin_flip_share_in_unit` (squares; null for H3), `one_ring_complete` | yes |
| `candidate_metrics.parquet` | yes | § 3.1 | yes |
| `benchmark_runs.parquet` | yes | v1 + `perturbation_id`, `source_variant`, `run_kind` | yes |
| `lookup_benchmark.parquet` | yes | v1 | yes |
| `source_coverage.parquet` | yes | § 5.4 | yes |
| `zonal_coverage.parquet` | yes | § 5.5 | yes |
| `completeness_report.json` | yes | per-requirement counts (§ 3.2), overall `passed`, `incomplete_requirements` | yes |
| `hard_gates.parquet` | yes | § 7.6 | yes |
| `robustness_rankings.parquet`, `robustness_reversals.parquet`, `robustness_verdicts.parquet` | yes | § 6.5 | yes |
| `pareto.parquet` | yes | § 7.4 (`frontier_kind ∈ decision_eligible / diagnostic_all / diagnostic_core3`) | yes |
| `budget_breakpoints.parquet` | yes | § 7.3 | yes |
| `matched_area_shape_comparison.parquet` | yes when sensitivity set present | § 7.5 | yes |
| `decision.json`, `decision_matrix.md` | yes | § 7.6, rendered | yes |
| `units/<aoi>/<candidate>_{geometry,features}.parquet` | yes for every candidate × AOI incl. sensitivity set; **not** for origin replicates | v1 + `candidate_set` | **yes** (every file) |
| `figures/*.png`, `figures/figure_manifest.json` | yes | § 10 | **yes** (every file) |
| `perturbations/<perturbation_id>/...` | no | optional intermediate | if present |

A `full` run missing any required path is `incomplete` with reason `artifact_missing:<path>`. `.gitignore` keeps `units/`, `figures/` and `candidate_inventory.parquet` out of git; the manifest and `SHA256SUMS` are tracked so what is left out is verifiable.

---

## 5. Coverage algorithm

The current ratio is 1.0 by construction because expected and processed are the same number read once. The remedy separates three independent derivations and tests their identities. A pixel-dropping fault anywhere in the pipeline breaks at least one identity.

### 5.1 Stage A — acquisition-time expectations (per AOI × raster role × source variant)

Computed in `acquire_gate2.clip_raster` **before** any clip is read, from geometry and the published tiling scheme only:

```
W        = requested window bounds in the source's native CRS (halo bbox transformed, as today)
T_req    = tiles whose published extent intersects W          # from the tiling scheme, not from the centre
T_have   = T_req ∩ tiles present in the manifest with verified checksum
inside   = W ⊆ union(extent(t) for t in T_have)               # geometric containment test
res      = native pixel size (from the parent tile header)
E_window = ceil((W.e − W.w)/res_x) × ceil((W.n − W.s)/res_y)  # expected pixels, geometry-only
```

Then clip via `gdalbuildvrt` over `T_have` (same grid, no resampling — a VRT mosaic of GHSL/WorldCover tiles is exact because tiles share one global grid) followed by `gdal_translate -projwin`. After the clip:

```
C_pixels          = width × height of the produced file
N_publisher       = count(pixel == nodata) in the produced file
E_valid           = C_pixels − N_publisher
edge_rows_full_nd = number of leading/trailing rows entirely NoData; same for columns
```

Sidecar and manifest record all of the above plus `T_req`, `T_have`, `inside`. Acquisition **fails** (manifest `failed`, no source index written) if `inside` is false, if `|C_pixels − E_window| > (width + height)` (one row/column of rounding), or if `edge_rows_full_nd × width + edge_cols_full_nd × height > 0` while `inside` is true and the publisher product has no NoData over the window's land (WorldCover, GHS-BUILT-S) — i.e. a fully-NoData edge band is always investigated, never accepted. WorldPop's constrained NoData over water is publisher NoData: the check for it is that the fully-NoData edge band coincides with WorldCover water (class 80) at ≥ 95 % of its pixels; otherwise `truncation_suspected = true` and the acquisition fails.

Applied to the invalidated run: `mu_cang_chai/ghs_built_s` fails `inside` (T_req = {R7_C28, R7_C29}, clipped from C29 only); `hanoi_core/worldcover` fails `inside` (T_req = {N18E105, N21E105}); `phu_quoc_coast/worldpop2025` passes (16 fully-NoData west columns coincide with WorldCover water at 97 %).

### 5.2 Stage B — run-time processing accounting (per AOI × raster role × source variant)

`_raster_points` becomes an accounting object. Every pixel of the clip is assigned to exactly one bucket:

```
P_nodata   = pixels equal to publisher NoData (or non-finite)
P_valid    = C_pixels − P_nodata
after point reprojection and _accumulate / _assign_points_to_units:
P_in_ref   = valid pixels that landed inside the 100 m reference grid
P_out_ref  = valid pixels outside it (must be 0 for the halo design; reported)
P_in_unit  = valid pixels whose centre fell in some unit (from pop_idx >= 0)
P_no_unit  = valid pixels in no unit
```

Identities tested at the end of `load_aoi_data` and per candidate:

```
I1  P_nodata == N_publisher                (run reads what acquisition validated)
I2  P_valid  == E_valid
I3  P_in_ref + P_out_ref == P_valid        (reference-grid accumulation drops nothing)
I4  P_in_unit + P_no_unit == P_valid       (assignment drops nothing)
I5  sum(values in units) + sum(values in no unit) == sum(values in clip)   (count conservation; 1e-9)
```

`processing_coverage = P_in_ref / E_valid` for source-level rows and must be ≥ 0.999; `dropped_pixels = E_valid − P_in_ref`. Because `E_valid` comes from acquisition (Stage A, a different process and time) and `P_in_ref` from the metric pipeline's own bookkeeping, the ratio is not 1.0 by construction.

### 5.3 Stage C — per-candidate zonal coverage (per AOI × candidate × raster role)

For the rasterize-based zonal path (`_zonal_class_stats`, `_zonal_builtup`), which never goes through points:

```
U        = unary_union of the candidate's unit polygons, in the raster CRS
E_zone   = count of pixel centres with contains_xy(U, x, y)     # shapely vectorised, independent of rasterize
A_bound  = area(U) / pixel_area                                 # geometric bound
Z_label  = count(zones > 0)                                      # what the labelled rasterize produced
Z_stat   = count of pixels that entered a per-unit statistic
```

Tests:

```
Z1  |Z_label − E_zone| / E_zone ≤ 1 − 0.999          (rasterize agrees with independent point-in-polygon)
Z2  |E_zone − A_bound| / A_bound ≤ 0.02               (catches CRS/transform mismatch: a wrong transform is off by far more)
Z3  Z_stat + Z_nodata_in_zone == Z_label              (nothing dropped between labelling and statistics)
Z4  Z_nodata_in_zone / Z_label == landcover_nodata_pixel_share_in_units (E2) and builtup_nodata_share_in_units
```

`zonal_processing_coverage = Z_stat / (E_zone − Z_nodata_in_zone)` ≥ 0.999. For WorldCover at 10 m over a 15 km AOI this is ≤ 6.2 M points against one prepared polygon — seconds.

### 5.4 `source_coverage.parquet` v2 columns

`run_id, aoi_id, source_role, source_variant, source_id, parent_source_ids (json list), release, license_id, source_uri, retrieved_at_utc, sha256, bytes, crs, native_resolution, requested_window_native (json), expected_tiles (json), present_tiles (json), window_inside_tile_union (bool), expected_window_pixels, clip_pixels, publisher_nodata_pixels, expected_valid_pixels, processed_valid_pixels, processed_nodata_pixels, pixels_in_units, pixels_outside_units, dropped_pixels, processing_coverage, edge_full_nodata_rows, edge_full_nodata_cols, truncation_suspected (bool), ingest_status (ok / failed / truncated / tile_missing / crs_mismatch), validity, validity_reason, notes`.

Vector rows (`poi_roads`) use the same table with: `expected_entities` (nodes, ways, relations from `osmium fileinfo -e` recorded at acquisition), `parsed_entities`, `taxonomy_matched`, `taxonomy_unmatched_retained`, `road_length_halo_m` (parser total after clipping to the halo polygon), `road_length_conservation_relative_error`, pixel columns null.

### 5.5 `zonal_coverage.parquet` columns

`run_id, aoi_id, candidate_id, perturbation_id, source_role, source_variant, expected_zone_pixels, area_bound_pixels, labelled_pixels, stat_pixels, nodata_in_zone, zonal_processing_coverage, checks_passed (json of Z1–Z4 booleans), validity`.

### 5.6 Gate semantics

- Completeness fails if any raster row has `window_inside_tile_union = false`, `ingest_status ≠ ok`, `processing_coverage < 0.999`, or any zonal row fails Z1–Z4 or `zonal_processing_coverage < 0.999`.
- A zero from a row with `validity = measured` is a mapped zero and must carry `source_status = ingested_ok`.
- A pixel that is missing because the window was truncated is `blocked:window_truncated`, never a zero. The 1 km anchor `builtup_fraction_1km` and `population_1km` use **valid-pixel area** as the denominator and carry a per-cell `anchor_valid_support_share`; a sample point whose disk has < 99 % valid support is `not_evaluable:anchor_support` for that anchor.
- NoData class 0 in WorldCover is excluded from class shares (E1) and reported (E2).

### 5.7 Tests that must exist (and must be able to fail)

1. `test_coverage_fails_when_assignment_drops_pixels`: monkeypatch `_assign_points_to_units` to drop 1 % of points → I4 fails → `completeness.passed is False`.
2. `test_coverage_fails_when_reference_grid_is_too_small`: pad 0 → I3 fails.
3. `test_coverage_fails_on_truncated_window`: synthetic tile extent smaller than window → `inside = false` → acquisition raises.
4. `test_zonal_coverage_fails_on_transform_mismatch`: shift the raster transform by half a window → Z2 fails.
5. `test_zonal_coverage_counts_agree_on_synthetic_grid`: known 10 × 10 raster, 4 units → E_zone = Z_label = Z_stat = 100.
6. `test_publisher_nodata_edge_band_over_water_is_accepted_and_over_land_is_not`.
7. `test_mapped_zero_rows_carry_measured_validity_and_ingested_ok`.

---

## 6. Robustness algorithm

Pre-registered rule 5: *a selected candidate may not reverse rank in more than one context under origin shifts, point jitter, or alternate population/built-up source sensitivity.*

### 6.1 Definitions

- **Context** = `aoi_id` (8 contexts).
- **Eligible set E** = candidates in the `operational` set that pass completeness, the too-coarse gate in every context, and the too-fine gate (§ 7.1). Rankings are computed over E only. If |E| < 3 → the gate is `not_evaluable:fewer_than_min_eligible_candidates` for every candidate.
- **Ranking metrics R** (lower is better after orientation):

| metric key | orientation | perturbation kinds that can move it |
|---|---|---|
| `within_unit_range_over_between_unit_iqr` / `all_anchors` / B1 | lower | origin_shift, jitter, population_source, builtup_source |
| `within_unit_range_over_between_unit_iqr` / `population_1km` / B1 | lower | population_source |
| `within_unit_range_over_between_unit_iqr` / `builtup_fraction_1km` / B1 | lower | builtup_source |
| `1 − landcover_dominant_share_median` / F | lower | origin_shift |
| `poi_zero_share` / `all_categories` / F | lower | origin_shift, jitter |
| `population_zero_share` / F | lower | origin_shift, population_source |

A (metric, kind) pair not listed is structurally invariant under that kind and is not evaluated (it would trivially pass).

- **Perturbation replicates**: `origin_shift` → 3 replicates (`off0.5x0`, `off0x0.5`, `off0.5x0.5`) for square candidates; `jitter` → 1 replicate (seeded); `population_source` → 1 replicate (`ghspop_2020`, § 8); `builtup_source` → 1 replicate (`worldcover_builtup_2021`, § 8). H3 under `origin_shift` is **not applicable**: the H3 candidate keeps its baseline value in the perturbed ranking (it is a comparator) and receives verdict `not_applicable` for that kind; reversals in that kind are attributed only to square candidates.
- **Baseline ranking** `r0[c, m]`: the baseline values of metric m for every candidate in E in context c.
- **Perturbed ranking** `rp[c, m, k, rep]`: the same, with every candidate to which kind k applies replaced by its value under replicate rep.
- **Tie**: two candidates X, Y are tied on m in a given ranking if `|v_X − v_Y| ≤ tol × max(|v_X|, |v_Y|)`, tol = 0.05. Ties are never reversals.
- **Material reversal** of X against Y in (c, m, k, rep): X strictly better than Y at baseline (not tied) **and** Y strictly better than X under the perturbation (not tied), or the converse. A reversal is attributed to X only if kind k applies to X.
- **Reversal in context** for (X, m, k): a material reversal against ≥ 1 other member of E in ≥ 1 replicate of k.
- **Verdict** for (X, m, k): `fail` if `contexts_with_reversal > 1`; `pass` if evaluated in all 8 contexts and ≤ 1; `not_applicable` (H3, origin); `blocked` if any context's perturbed value for X or for any comparator is `blocked`; `not_evaluable` if any is `not_evaluable`.
- **Candidate verdict**: `fail` if any applicable (m, k) is `fail`; else `blocked`/`not_evaluable` if any applicable (m, k) is; else `pass`, reported together with the list of kinds it was evaluated under and the kinds recorded as not applicable. The rendered text for H3 is always "pass on jitter, population_source, builtup_source; origin_shift not applicable", never "pass".

### 6.2 Pseudocode

```python
def robustness(metrics, E, R, kinds, tol, max_ctx=1):
    rankings, reversals, verdicts = [], [], []
    for m in R:                                  # (metric, dimension, support, orientation)
        for c in contexts:
            v0 = {X: oriented(value(metrics, c, X, m, "baseline", "primary")) for X in E}
            rankings += rows(c, m, "baseline", "baseline", v0)
            for k in kinds_that_move(m):
                for rep in replicates(k):
                    vp = dict(v0)
                    for X in E:
                        if applies(k, X):
                            vp[X] = oriented(value(metrics, c, X, m, rep.perturbation_id, rep.source_variant))
                    rankings += rows(c, m, k, rep, vp)
                    for X in E:
                        if not applies(k, X):
                            continue
                        if any(is_missing(vp[Y]) or is_missing(v0[Y]) for Y in E):
                            mark(X, m, k, c, validity_of_missing(...)); continue
                        for Y in E - {X}:
                            b = sign_with_tol(v0[X], v0[Y], tol)      # -1 X better, 0 tie, +1 Y better
                            p = sign_with_tol(vp[X], vp[Y], tol)
                            material = (b != 0) and (p != 0) and (b != p)
                            reversals += row(c, m, k, rep, X, Y, v0, vp, material)
        for X in E:
            for k in kinds_that_move(m):
                if not applies(k, X):
                    verdicts += row(X, m, k, "not_applicable", reason="no_grid_origin"); continue
                if blocked(X, m, k):    verdicts += row(X, m, k, "blocked", ...);        continue
                if not_eval(X, m, k):   verdicts += row(X, m, k, "not_evaluable", ...);  continue
                n = count(c for c in contexts if any(material(c, m, k, rep, X, Y) for rep, Y))
                verdicts += row(X, m, k, "fail" if n > max_ctx else "pass", contexts_with_reversal=n)
    candidate_verdict = aggregate(verdicts)      # fail > blocked > not_evaluable > pass; NA listed separately
    return rankings, reversals, verdicts, candidate_verdict
```

`sign_with_tol(a, b, tol)` returns 0 when `|a − b| ≤ tol·max(|a|, |b|)`, else the sign of `a − b`. Missing values (`not_evaluable`, `blocked`) propagate as the corresponding verdict; they never count as "no reversal".

### 6.3 What the perturbations actually recompute

| kind | what changes in the pipeline | metrics recomputed (from § 3.3) |
|---|---|---|
| `origin_shift` (squares) | units regenerated at the offset origin; all per-unit aggregation rerun (no storage write, no lookup benchmark, no ring/Jaccard) | A1, B1–B2, C1–C3, D1–D2, E1–E5, F1–F2, J1 |
| `jitter` | POI representative points moved by δ = 0.1·√(mean unit area) in a seeded random direction; interior sample points moved by δ and snapped back inside their unit; POI anchor field rebuilt | B1–B2, F1–F2 (poi and all-anchor rows), H2 |
| `population_source` | population raster replaced by the alternate (§ 8); population anchor field rebuilt | C1–C3, F1–F2 (population and all-anchor rows), I1 (population feature), J1, L1 |
| `population_epoch` (diagnostic) | WorldPop 2025 → WorldPop 2020 | same as above; reported, not a gate input |
| `builtup_source` | built-up field replaced by WorldCover class-50 area at 10 m (§ 8); built-up anchor field rebuilt | E3, E6, F1–F2 (built-up and all-anchor rows), J1, L1 |

### 6.4 Unavailable sensitivity sources

If a required alternate source is not acquired for an AOI (e.g. a GHS-POP tile), every perturbed row for that AOI and kind is written with `validity = blocked`, `validity_reason = source_not_acquired`, the (X, m, kind) verdicts are `blocked`, the candidate verdict is `blocked`, `completeness_report.incomplete_requirements` names the requirement, and the run is `incomplete`. There is no partial pass on the available contexts: the rule counts contexts, and an unobserved context could hold the second reversal.

### 6.5 Tidy outputs

`robustness_rankings.parquet`: `run_id, aoi_id, metric, dimension, spatial_support, perturbation_kind, perturbation_id, source_variant, candidate_id, oriented_value, rank, eligible_set (json sorted list)`.

`robustness_reversals.parquet`: `run_id, aoi_id, metric, dimension, spatial_support, perturbation_kind, perturbation_id, candidate_id, other_candidate_id, baseline_sign, perturbed_sign, baseline_diff_rel, perturbed_diff_rel, material_reversal (bool)`.

`robustness_verdicts.parquet`: `run_id, candidate_id, metric, dimension, spatial_support, perturbation_kind, contexts_evaluated, contexts_with_reversal, replicates, verdict, validity_reason` plus one summary row per candidate with `metric = "__candidate__"`, `verdict`, `kinds_evaluated (json)`, `kinds_not_applicable (json)`.

These three tables, `config_snapshot/gate2.yaml` (tolerance, kinds) and `hard_gates.parquet` (E) reproduce the verdict exactly.

### 6.6 Tests

`test_robustness_detects_a_planted_reversal_in_two_contexts` (synthetic frame: swap two candidates' values under jitter in 2 of 3 contexts → fail; in 1 → pass), `test_tie_within_tolerance_is_never_a_reversal`, `test_h3_origin_kind_is_not_applicable_and_not_a_pass`, `test_blocked_source_yields_blocked_verdict_not_pass`, `test_fewer_than_three_eligible_is_not_evaluable`, `test_reversal_attributed_only_to_perturbed_candidate`.

---

## 7. Hard-gate and Pareto ordering

### 7.1 Order of evaluation

```
0  coverage (§5) and completeness (§3)     → if unmet: state=incomplete; stop (diagnostics may still be rendered, labelled)
1  administrative qualification            → candidate admin: blocked | qualified; grids: not_applicable
2  too coarse (rule 3, both branches)      → reject in context; survivor = rejected in no context
3  too fine (rule 4)                       → among survivors of 2, per family ordering
4  robustness (rule 5, §6)                 → over E = survivors of 2 and 3
5  feasibility (rule 6)                    → budget present: filter; absent: not_evaluable, breakpoints reported
6  Pareto among eligible only              → eligible = survivors of 2, 3, 4 (and 5 when evaluable)
7  selection (rule 7) or explicit no-decision
```

Each step's per-candidate outcome and the eligible set entering the next step are written to `hard_gates.parquet` (§ 7.6). A candidate rejected at step n does not appear in the eligible set of step n+1 and cannot appear on the decision frontier.

### 7.2 Too-coarse rule, branch 2

Pre-registered text: *also flag a candidate whose dominant land-cover share degrades against both adjacent finer scales without material feasibility benefit.*

- **Family ordering** = candidates of the `operational` set in the same family, sorted by measured `unit_area_km2_median` (median over AOIs). Sensitivity candidates (local area controls) are excluded from the ordering.
- **Adjacent finer candidates** of X = the next finer (F1) and the second-next finer (F2) in that ordering. Edge cases: the finest and second-finest candidate of each family have fewer than two finer neighbours → branch 2 is `not_applicable` for them (reported as such; branch 1 still decides).
- **Degradation statistic**, per context c: mixing error `e(Y, c) = 1 − landcover_dominant_share_median(Y, c)`. X *degrades* against Y in c if `e(X, c) > e(Y, c) × (1 + 0.05)` (reuses `fine_minimum_error_improvement`).
- **Material feasibility benefit** of X relative to F1, per context c: `cost_ratio(F1, X, c) = max(unit_count_total(F1,c)/unit_count_total(X,c), storage_nationwide_projected_bytes(F1,c)/storage_nationwide_projected_bytes(X,c))`. X has a material benefit if `cost_ratio > 2.0` (reuses `fine_cost_multiplier_vs_next_coarser`). Runtime ratio is reported but not used at context level (noisy per AOI).
- **Flag** X in context c if it degrades against both F1 and F2 **and** has no material benefit relative to F1.
- **Not evaluable** if any input row is `not_evaluable`/`blocked` for X, F1 or F2 in c.
- **Verdict**: too-coarse rejection in context c = branch 1 triggered **or** branch 2 flagged. Survivor = rejected in no context and evaluable in all. Branch 1 keeps its rule but `too_coarse_anchor_features_triggered ≥ 2` is evaluated against `too_coarse_anchor_features_evaluable`; if fewer than 2 anchors are evaluable in a context (F12), branch 1 is `not_evaluable` there and the candidate cannot be a survivor.

Thresholds are unchanged. Nothing here is tuned to the observed results; the branch is evaluated for the first time in the remediation run.

### 7.3 Feasibility without a budget — what can still be concluded

No budget is invented. `feasibility` verdict = `not_evaluable:no_owner_budget` for every candidate, and the run cannot reach `complete_selected`. What is still produced, from measured values only:

- `budget_breakpoints.parquet`: for each cost objective (`nationwide_storage_bytes`, `total_runtime_s`, `peak_rss_bytes`), the eligible candidates sorted by cost, i.e. the exact budget at which each eligible candidate becomes admissible, and the eligible Pareto set restricted to each prefix. The owner reads off which budget number would decide.
- Ordinal statements that are budget-free: which eligible candidates are Pareto-dominated on the decision objectives; the cost span of the eligible set; the pairwise cost ratios that rule 4 already uses.
- Nothing else. "Live region", "leading candidate" and similar phrases are prohibited in `decision_matrix.md` while the state is `executed_no_decision`.

### 7.4 Frontiers

| `frontier_kind` | candidates | objectives | may support a decision |
|---|---|---|---|
| `decision_eligible` | eligible set from § 7.1 step 6 | the nine objectives implemented in `build_objectives` (nationwide storage, total runtime, peak RSS, within-unit loss, mixing error, ring-1 km error, ring-3 km error, POI zero share, batch lookup p95), with within-unit loss taken from the `all_anchors` row — all `measured`. (The invalidated run's text says "ten objectives"; its table has nine.) | **yes**; an eligible candidate with any `not_evaluable` objective is `undetermined` and cannot be selected |
| `diagnostic_all` | all `operational` candidates incl. gate rejects | same | no — labelled "diagnostic, includes hard-gate rejects" in every rendering |
| `diagnostic_core3` | all | storage, loss, mixing error | no — the three-axis view is kept because the acceptance rules turn on those axes, labelled diagnostic |

Sensitivity candidates never appear on any frontier.

### 7.5 Area-control sensitivity set (F8)

- Candidates `square_131m`, `square_347m`, `square_918m`, `square_2429m`; `role = area_control_local`, `candidate_set = sensitivity`, `controls_for = h3_r10/r9/r8/r7`; sides from `remediation_parameters.area_control_local.sides_m` with the derivation (measured 1.1430) recorded in the config comment.
- Run in the **same measurement run** as the operational set (identical sources, code, seeds), so the comparison is not confounded by run drift, but stored with `candidate_set = sensitivity` and excluded from: family orderings (MAUP pairs, fine-gate adjacency, branch-2 adjacency), the eligible set, every frontier, robustness E, and `decision_matrix.md` gate tables.
- Reported in `matched_area_shape_comparison.parquet`: one row per (H3 resolution, control kind ∈ {global_nominal, local_measured}, AOI, metric) with `area_ratio = area(control)/area(h3)`, for the metrics on which Finding 4 of the invalidated run was stated (nationwide storage, within-unit loss, mixing error, ring Jaccard, lookup latency).
- **They may not affect the final decision.** They exist to say whether the square-vs-H3 statements at matched scale survive removing the 12.5–14.3 % scale offset. Promoting a local control to an operational candidate requires an amendment to `spatial_unit_decision.md` **before** a subsequent full run, recorded as a new pre-registration.

### 7.6 `hard_gates.parquet` and `decision.json`

`hard_gates.parquet`: `run_id, step (0–7), gate, candidate_id, aoi_id (null for candidate-level), verdict (pass/fail/not_applicable/not_evaluable/blocked), reason, inputs (json of the metric keys and values used), eligible_after_step (bool)`.

`decision.json` (schema v2): `run_id, run_kind, state, blockers[], completeness {passed, incomplete_requirements[]}, gates {admin, too_coarse {survivors, rejections[], branch2_flags[]}, too_fine, robustness {per candidate verdict, kinds}, feasibility}, eligible_candidates[], frontiers {decision_eligible[], diagnostic_all[], diagnostic_core3[]}, budget_breakpoints_path, sensitivity {area_control_local: path, source_sensitivity: summary}, selected_candidate (null), spatial_unit_method (null), remediation_parameters (copied)`.

---

## 8. Alternate-source sensitivity plan

Every product below is a **modelled or classified** dataset. None is ground truth; the question answered is whether candidate rankings depend on the choice of product, not which product is right.

### 8.1 Population

| step | primary | alternate | isolates | role in rule 5 |
|---|---|---|---|---|
| epoch | WorldPop Global 2 R2025A v1, 2025, 100 m constrained count (`worldpop_vnm_2025_cn_100m_r2025a_v1`, sha `21f40388…`, pinned) | WorldPop Global 2 R2025A v1, **2020**, 100 m constrained count (`worldpop_vnm_2020_cn_100m_r2025a_v1`, sha `d615df57…`, already on disk from Gate 1) | epoch, same producer and method | diagnostic (`population_epoch`) |
| source | WorldPop 2020 (above) | **GHS-POP R2023A, epoch E2020, 100 m, Mollweide (ESRI:54009)**, tiles `R8_C29` (on disk, sha `d83c34aa…`), `R7_C29` and `R7_C28` (to acquire; same URL pattern as the pinned tile: `…/GHS_POP_GLOBE_R2023A/GHS_POP_E2020_GLOBE_R2023A_54009_100/V1-0/tiles/GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0_R{row}_C{col}.zip`; checksums pinned on first verified download exactly as the WorldCover tiles are) | producer/method at a common epoch | **the `population_source` perturbation** |

Why same-epoch: comparing WorldPop 2025 against GHS-POP 2020 would confound five years of modelled growth with the source difference. The two-step design attributes ranking movement to epoch and to source separately. The Gate 1 audit measured the 2020 pair at Spearman 0.970 with totals within 1.2 %, so a large ranking effect from the source step would be a real finding about resolution-dependence, not noise.

Resolution and CRS: WorldPop is 3 arc-second EPSG:4326 (≈ 87–92 m on a side at 10–22° N); GHS-POP is 100 m × 100 m equal-area. The pixel footprints differ by ≈ 15–20 % in area. Because Gate 2 carries every pixel's count as a point to exactly one destination, the comparison is not affected by regridding (the −2.82 % conservation error in the Gate 1 audit came from `Resampling.sum` regridding, which Gate 2 does not do). To separate source from grid effects, the run also reports `population_source_agreement_spearman` per candidate × AOI (unit-level rank agreement WorldPop 2020 vs GHS-POP 2020) — if agreement is high at coarse units and low at fine units, the source difference is a resolution-dependent allocation difference, and that is the finding.

Requirements: native CRS retained (no reprojection of rasters); halo clip via the § 5.1 path (tile union — MCC needs R7_C28 + R7_C29 for GHS-POP exactly as for GHS-BUILT-S); `population_conservation_relative_error < 1e-9` per variant; NoData −200 for GHS-POP recorded as publisher NoData (it appears over water and outside the land mask; validated against WorldCover water as in § 5.1).

### 8.2 Built-up

| option | product | practical now | verdict |
|---|---|---|---|
| a | **ESA WorldCover 2021 v200, class 50 (built-up), 10 m, EPSG:4326** — same tiles already pinned for land cover | yes, zero network | **selected** as `builtup_source` alternate and as the 10 m supplementary source (§ 9) |
| b | GHS-BUILT-S R2023A E2018 10 m (Sentinel-2 composite) | tiles are large; epoch 2018 | not selected: confounds epoch (2018 vs 2020) **and** resolution (10 m vs 100 m) with source; may be a later resolution-sensitivity run, not required for Gate 2 |
| c | GHS-BUILT-S R2023A E2025 100 m | on the same tiling | not selected: same model, projected epoch — not an independent source |
| d | Building footprints (Overture Buildings / Google Open Buildings v3) | new acquisition, licence review, vector processing | not selected for Gate 2; listed as a Gate 3/4 QA option |

Caveats stated with the result: (a) is a binary classification (share of built-up pixels), not a continuous built-up surface fraction; the two agree in meaning at the 1 km support (share of built area) but not necessarily at the pixel; epoch 2021 vs 2020; different producer lineage (ESA/VITO vs JRC) but overlapping Sentinel inputs. It is independent of every population and POI input, and of the GHS-BUILT-S product it perturbs. It is **not** independent of the land-cover metrics (E1), which is acceptable because no land-cover metric is recomputed under `builtup_source`.

If a reviewer rejects (a) as insufficiently independent, the state is **`blocked:builtup_source_not_independent`** for the `builtup_source` kind, the robustness candidate verdict is `blocked`, and Gate 2 stays `incomplete` until an alternate is acquired. A blocked kind is never rendered as a pass.

### 8.3 Acquisition strategy

- Alternates are acquired by `acquire_gate2` under new roles `population_alt_epoch`, `population_alt_source`, `built_up_alt`, with the same halo, the § 5.1 tile-union clip, sidecars, and manifest entries (`is_derived`, `parent_source_id`, `transform`).
- Network required only for GHS-POP `R7_C29` and `R7_C28` (~40 MB each). Everything else is on disk.
- Format: COG GeoTIFF; CRS: native; no resampling; conservation identities of § 5.2 per variant.

### 8.4 What is recomputed and how rankings are compared

Listed in § 6.3. Rankings are compared by § 6 over E, per (metric, kind). In addition, `decision_matrix.md` shows for each ranking metric the baseline rank and the rank under each source variant side by side, with reversals marked, so the reader sees the movement, not only the verdict.

---

## 9. Built-up fine-resolution validity policy

Facts: GHS-BUILT-S at 100 m gives median in-unit pixel counts of ≈ 1.6 (`square_125m`), 1.7 (`h3_r10`), 6 (`square_250m`), 10–12 (`square_325m`, `h3_r9`), ≥ 25 above. The sample variance from n ≤ 6 pixels has a relative standard error above 0.6 and its distribution is right-skewed, so a median over thousands of such units is biased low relative to a median over units with n ≥ 100. Comparing those medians is comparing estimators, not built-up heterogeneity.

Options considered: (1) a 10 m source; (2) minimum valid-pixel eligibility; (3) common-support comparison (restrict every candidate to units with n ≥ k — the fine candidates' surviving units are the ones straddling pixel boundaries, a biased subset); (4) declare not evaluable at fine resolutions; (5) leave as is.

**Decision — (2) + (1), with (4) as the resulting state for fine candidates on the primary source:**

- The pre-registered 100 m metric `builtup_fraction_variance_{q}` (E4) is kept with its definition. It is `measured` for a candidate × AOI only if `builtup_pixels_per_unit_median ≥ 9`; otherwise every E4 row is `not_evaluable:builtup_support_below_min` and E5 reports the support. Expected outcome: `square_125m`, `h3_r10`, `square_250m` not evaluable on the primary source; all others measured.
- The supplementary 10 m metric (E6) from WorldCover class 50 is `measured` for every candidate (≥ 150 pixels even at 125 m) and is the metric the headline table shows for within-unit built-up heterogeneity, with E4 alongside where evaluable.
- Completeness: E4 rows with `not_evaluable:builtup_support_below_min` satisfy the contract (the reason code is declared for that requirement). E6 rows must be `measured`.
- Pareto and hard gates: neither E4 nor E6 is an objective or gate input (this is the current state and it is made explicit in the contract). If a future revision wants built-up heterogeneity as an objective, it must use a metric that is `measured` for every eligible candidate on common support — E6 qualifies; E4 does not.
- The `builtup_fraction_1km` anchor (B1 support, ≈ 314 pixels) is unaffected by this policy.

---

## 10. Visualization contract

All maps: polygon rendering (`GeoSeries.boundary.plot` or a `PolyCollection`), identical extent per figure = AOI bounds in the AOI metric CRS expanded by 5 %, AOI outline drawn in every facet, one facet per candidate of the `operational` set in the fixed order `[square_125m, h3_r10, square_250m, square_325m, h3_r9, square_500m, square_850m, h3_r8, square_1000m, square_2270m, h3_r7]` (by measured area), shared colour limits across facets and, for share-valued metrics, fixed `[0, 1]` across AOIs. Title states metric, spatial support, source variant, and perturbation. A colour bar per figure. Origin-sensitivity figures render an explicit "not applicable — no grid origin" panel for H3 facets.

### 10.1 Per-AOI maps (8 kinds × 8 AOIs = 64 files)

| filename | rendering | column / metric | support |
|---|---|---|---|
| `map_unit_boundaries_{aoi}.png` | polygon **boundaries**, no fill | geometry | F |
| `map_poi_sparsity_{aoi}.png` | fill by `poi_count`, zero-POI units in a distinct categorical colour | B1 row-derived inventory column | F |
| `map_population_sparsity_{aoi}.png` | fill by `population`, zero units distinct | population (primary) | F |
| `map_road_sparsity_{aoi}.png` | fill by `road_length_m`, zero units distinct | roads | F |
| `map_landcover_entropy_{aoi}.png` | fill by `landcover_entropy_bits` | land cover | F |
| `map_landcover_dominant_share_{aoi}.png` | fill by `landcover_dominant_share` | land cover | F |
| `map_within_unit_loss_{aoi}.png` | fill by `within_unit_loss_all_anchors` for sampled units; unsampled units hatched grey | anchors | B1 |
| `map_origin_sensitivity_{aoi}.png` | squares: fill by `origin_flip_share_in_unit`; H3: "not applicable" panel | geometry | F |

### 10.2 Aggregate plots (fixed list, 18 files)

`plot_poi_sparsity_vs_area.png` (two panels: F and B1), `plot_population_sparsity_vs_area.png`, `plot_road_sparsity_vs_area.png`, `plot_semantic_mixing_vs_area.png`, `plot_dominant_landcover_vs_area.png`, `plot_builtup_variance_vs_area.png` (100 m with not-evaluable candidates as hollow markers, and 10 m as a second panel), `plot_within_unit_loss_vs_area.png`, `plot_neighborhood_error_1km_vs_area.png`, `plot_neighborhood_error_3km_vs_area.png`, `plot_one_ring_area_vs_area.png`, `plot_unit_count_vs_storage.png`, `plot_unit_count_vs_runtime.png`, `plot_boundary_origin_sensitivity.png`, `plot_maup_adjacent_resolution_stability.png`, `plot_robustness_reversals.png` (heatmap candidate × (kind, metric) of contexts-with-reversal; NA cells marked), `plot_source_sensitivity.png` (baseline vs each variant per candidate on the ranking metrics), `plot_matched_area_shape_comparison.png` (H3 vs global control vs local control), `plot_pareto_eligible.png` (pairwise projections of the decision frontier; diagnostic frontier greyed and labelled).

Sensitivity candidates appear in `plot_matched_area_shape_comparison.png` only.

### 10.3 `figures/figure_manifest.json`

One entry per file: `filename, figure_kind, aoi_id (or null), candidates (list), metric, dimension, spatial_support, source_variant, perturbation_id, geometry_rendered (polygon_boundary / polygon_fill / marker / none), n_panels, extent_bounds_metric, extent_crs, colour_scale {vmin, vmax, cmap, shared_across_panels: true}, width_px, height_px, bytes, sha256, generator (function name)`. The run manifest checksums this file and every PNG.

### 10.4 Tests

1. `test_figure_manifest_matches_contract`: expected filename set (64 + 18) equals manifest set equals files on disk; sha256 matches.
2. `test_unit_boundary_maps_render_polygons_not_points`: on a synthetic 2-candidate run the axes of each facet contain a `LineCollection`/`PolyCollection` whose path vertex count ≥ 4 × unit count and no `PathCollection` (scatter); manifest `geometry_rendered == polygon_boundary`.
3. `test_facets_share_extent_and_colour_limits`: `ax.get_xlim()/get_ylim()` identical across facets; `vmin/vmax` identical across facets; share metrics use `[0, 1]`.
4. `test_origin_sensitivity_figure_marks_h3_not_applicable`: H3 panels carry the NA annotation and no fill.
5. `test_every_map_kind_exists_for_every_aoi` and `test_figure_count_is_exact`.
6. `test_sensitivity_candidates_appear_only_in_matched_area_plot`.

---

## 11. Reproducibility and manifest schema

### 11.1 `run_manifest.json` v2

```json
{
  "manifest_version": "2.0.0",
  "gate": 2,
  "run_id": "…", "run_kind": "full|smoke|sensitivity",
  "status": "running|complete|failed|incomplete",      // execution status
  "gate_state": "incomplete|executed_no_decision|complete_selected|failed", // §2, set at finalize
  "failure_reason": null, "failed_at_stage": null,
  "incomplete_requirements": [],
  "scope": {"aois": [...], "candidates_operational": [...], "candidates_sensitivity": [...], "perturbation_kinds": [...]},
  "started_at_utc": "…", "finished_at_utc": "…", "hostname": "…", "pid": 0,
  "config_snapshot": {"dir": "config_snapshot", "files": {"gate2.yaml": "<sha256>", …}, "config_hash": "<sha256 over snapshot>"},
  "code_snapshot": {"git_commit": "…", "git_dirty": true, "tracked_patch_sha256": "…", "untracked_archive_sha256": "…", "code_tree_sha256": "…", "files": "code_snapshot/file_hashes.json"},
  "environment": {"python": "…", "platform": "…", "pip_freeze_sha256": "…", "gdal": "…", "proj": "…", "geos": "…", "osmium_cli": "…", "gdal_translate_cli": "…", "cpu_count_logical": 8, "total_ram_bytes": 0},
  "sources": {"acquisition_manifest": {"path": "…", "sha256": "…"}, "source_index": {"path": "…", "sha256": "…"}, "derived_assets_verified_at_start": true},
  "remediation_parameters": {…},
  "artifacts": [{"path": "…", "bytes": 0, "sha256": "…", "rows": 0}],   // every parquet incl. units/, every figure, decision files, contract files
  "sha256sums_file": "SHA256SUMS",
  "decision": {…}                                     // §7.6
}
```

### 11.2 Code snapshot

`code_snapshot/` holds `git_commit.txt`, `git_status_porcelain.txt`, `tracked.patch` (`git diff --binary HEAD -- src tests config scripts pyproject.toml`), `untracked.tar.gz` (untracked, non-ignored files under the same paths), `file_hashes.json` (path → sha256 for every non-ignored file under those paths) and `code_tree_sha256.txt` (sha256 over the sorted `path\0hash\n` lines). `verify_run` recomputes `code_tree_sha256` from the current tree and reports match/mismatch. The runner refuses `run_kind = full` on a dirty tree unless `--allow-dirty` is passed; with the flag, the snapshot is mandatory and `git_dirty: true` is recorded. The recommendation to the implementer: commit before the remediation run so `git_dirty` is false.

### 11.3 Environment

`environment/pip_freeze.txt` (from `python -m pip freeze` in the active interpreter), `platform.json` (python, platform, machine), `native_libs.json` (`rasterio.__gdal_version__`, `pyproj.proj_version_str`, `shapely.geos_version_string`, `h3.__version__`), `cli_versions.json` (`osmium --version`, `gdal_translate --version`, `gdalbuildvrt --version`). Add `uv.lock` to the repository and record its sha256; the run fails if `uv.lock` is absent for `run_kind = full`.

### 11.4 Immutability and overwrite prevention

- Run directory created with `exist_ok=False`; a collision raises.
- `RUN_LOCK` written at start; a second runner on the same directory raises.
- Derived clips in `data/gate2/aoi_sources/` are re-hashed at run start and compared with the source index; mismatch → `failed:source_index_mismatch`.
- At finalize: `SHA256SUMS`, manifest, then `chmod -R a-w` on the run directory. `verify_run --run <dir>` re-hashes everything and checks the manifest; it is what `tests/test_gate2_*` call.
- Configs are never read from `config/` after the snapshot is taken; the runner and the decision evaluator read `config_snapshot/`.

### 11.5 Smoke vs full

`--run-kind` is required (no default). Smoke runs write to `data/gate2/smoke/`, may cover a subset, and are never listed in `run_registry.json` as candidates for the Gate 2 state. Test helpers (`_latest()` in `tests/test_gate2_completeness.py`, `_latest_run()` in `tests/test_gate2_artifacts.py`) are replaced by one helper that returns the registry's latest **valid full** run and skips with the reason otherwise.

### 11.6 Decision records and registry

`data/gate2/run_registry.json`: list of `{run_id, run_kind, path, gate_state, valid (bool), invalidation_reasons[], superseded_by, registered_at}`. `data/gate2/decisions/<run_id>/decision_<ts>.json` for any re-evaluation with a later decision configuration (e.g. a budget); each references the measurement run's `run_id` and `SHA256SUMS` hash.

---

## 12. Implementation work packages

Sized for a Sonnet-class implementer. "Rerun" = requires regenerating measured data; "Network" = requires downloads. Baseline measurement of 88 pairs took ~4 minutes on the recorded hardware; the remediation run with perturbations and the sensitivity set is estimated at 30–45 minutes.

| WP | scope | files expected to change | depends on | tests (focused) | rerun | network |
|---|---|---|---|---|---|---|
| **WP0** | Invalidate the current run and correct the state | new `data/gate2/run_registry.json`; `config/spatial.yaml` (`gate2_experiment.status: incomplete`, add `remediation_design`, `invalidated_runs` — **no change to `spatial_unit.method`**); `docs/spatial_unit_decision.md` (status line + a "withdrawn / retained" banner over § Measured results per § 13) | — | `test_spatial_config_method_stays_null…` still passes; new `test_registry_marks_run_invalid` | no | no |
| **WP1** | Metric row schema v2, validity states, contract file, completeness gate | `src/spatial/metrics.py` (`_row` → validity, reason codes), `src/spatial/benchmark.py` (`REQUIRED_SCHEMAS`, uniqueness check in `write_table`), new `config/gate2_metric_contract.yaml`, new `src/spatial/contract.py` (`expand`, `check`), `src/spatial/decision.py::completeness_gate` | WP0 | contract expansion cardinality on synthetic candidates/AOIs; duplicate key rejection; absent POI leaf → row with 1.0; `not_applicable` accepted only where declared; unknown reason code rejected | no | no |
| **WP2** | Coverage that can fail (§ 5) | `src/ingestion/acquire_gate2.py` (tile union, `gdalbuildvrt`, Stage A sidecar fields, edge-band check), `src/spatial/metrics.py` (`_raster_points` accounting, `_zonal_*` E_zone/A_bound, class-0 exclusion, anchor valid-support denominator), `src/spatial/run_gate2.py::_coverage_rows`, new `zonal_coverage` schema | WP1 | § 5.7 items 1–7 | **yes** — re-clip at least `hanoi_core` land cover and `mu_cang_chai` built-up (tiles on disk); recommended: re-derive all clips through the new path | no |
| **WP3** | Metric gaps (§ 3.3 new rows) | `src/spatial/metrics.py` (per-leaf 1 km fields, degree histogram, one-ring area, jitter feature-rank, built-up eligibility + WorldCover class-50 10 m metrics, road conservation, degenerate-IQR handling) | WP1 | per-leaf universe from taxonomy; degree histogram sums to 1; one-ring area = 9× / 7× cell on synthetic grids; degenerate IQR → not_evaluable and excluded from the evaluable count; built-up eligibility threshold | yes | no |
| **WP4** | Perturbation framework + robustness (§ 6) | `src/spatial/run_gate2.py` (perturbation loop, replicate identity columns), `src/spatial/metrics.py` (jitter of POI/interior points; source-variant `AoiData`), new `src/spatial/robustness.py`, `src/spatial/decision.py` (remove old `robustness_gate`) | WP1, WP3 | § 6.6 | yes | no |
| **WP5** | Alternate sources (§ 8) | `src/ingestion/acquire_gate2.py` (roles `population_alt_epoch`, `population_alt_source`, `built_up_alt`; GHS-POP tile acquisition; WorldCover class-50 derivation as a documented transform), `src/ingestion/run_acquisition.py::PINNED_ASSETS` (GHS-POP R7_C29, R7_C28 after first verified download) | WP2 | manifest entries for every variant; conservation per variant; blocked state when a tile is absent | yes | **yes** (2 GHS-POP tiles) |
| **WP6** | Gate ordering, branch 2, eligible Pareto, breakpoints, decision schema, state machine (§ 2, § 7) | `src/spatial/decision.py` (rewrite ordering; `coarse_gate` branch 2; `pareto_frontier` over eligible; `budget_breakpoints`; `decision.json` v2; `_render_markdown`), new `src/spatial/state.py` | WP4 | branch-2 flag on synthetic monotone case; edge candidates not_applicable; a gate reject never reaches a frontier; breakpoints table; state transitions incl. `scope_short` | yes (to produce), no (to test) | no |
| **WP7** | Area-control local sensitivity set (§ 7.5) | `config/gate2.yaml` (`candidates.square_m` entries with `role: area_control_local`, `remediation_parameters`), `src/spatial/candidates.py` (`candidate_set`), `src/spatial/run_gate2.py`, `src/spatial/decision.py` (exclusion), new `matched_area_shape_comparison` writer | WP6 | sensitivity candidates excluded from orderings, E, frontiers; present in the comparison table | yes | no |
| **WP8** | Visualization contract (§ 10) | `src/spatial/plots.py` (rewrite), `src/spatial/run_gate2.py` (inventory columns), figure manifest writer | WP3, WP4, WP7 | § 10.4 | regenerable from a run's parquet + `units/` without re-measuring | no |
| **WP9** | Reproducibility (§ 11) | `src/spatial/benchmark.py` (`RunContext` v2, snapshots, `SHA256SUMS`, lock, chmod), `src/spatial/run_gate2.py` (`--run-kind`, `exist_ok=False`, start-of-run manifest, registry), new `src/spatial/verify_run.py`, `pyproject.toml` (+ `uv.lock`), `.gitignore` (registry tracked; `SHA256SUMS` tracked) | WP0 | collision raises; dirty-tree refusal; `verify_run` detects a modified figure/parquet; smoke runs excluded from the registry; helper picks latest valid full run | no | no |
| **WP10** | Full remediation run and documentation | run `acquire_gate2` (WP5), then `run_gate2 --run-kind full`; update `docs/spatial_unit_decision.md` § Measured results (new run, withdrawn statements replaced), `data/gate2/run_registry.json`, `config/spatial.yaml: gate2_experiment` (status from the run; **method stays null**) | all | § 14 checklist executed and recorded | yes | yes (via WP5) |

Dependency order: WP0 → WP9 → WP1 → WP2 → WP3 → WP4 → WP5 (may start after WP2, in parallel with WP3/WP4) → WP6 → WP7 → WP8 → WP10.

Steps that need **no network and no data regeneration**: WP0, WP1, WP6 (logic + synthetic tests), WP9, WP8's tests. Steps that need a **rerun but no network**: WP2, WP3, WP4, WP7, WP8 (rendering). **Network**: WP5 only (two GHS-POP tiles). A **full rerun** is required once, at WP10, after all code changes; intermediate reruns are smoke runs (`--run-kind smoke --aoi hanoi_core --aoi mu_cang_chai`, which exercise both truncation cases).

---

## 13. Run invalidation policy for `data/gate2/run_20260914T091321Z`

1. **Keep, do not edit, do not delete.** The directory is evidence. Its manifest is not rewritten; its `decision.json` is not touched.
2. **Register as invalid.** `data/gate2/run_registry.json` gets `{run_id: "20260914T091321Z", run_kind: "full" (retro-labelled), gate_state_claimed: "executed_no_decision", gate_state: "incomplete", valid: false, invalidation_reasons: [F1, F2, F3, F3a, F3b, F4, F7, F10], superseded_by: null}`.
3. **Withdrawn statements** in `docs/spatial_unit_decision.md` § Measured results (WP0 adds a banner and strikes them; the text stays legible):
   - "Every metric and acceptance rule … was implemented and measured … no metric is missing" (F4);
   - the completeness table rows "Raster processing coverage 1.000" and "Zonal processing coverage 1.000" (F3);
   - "GHS-BUILT-S is NoData over up to 1.19 % of in-unit pixels in Mù Cang Chải's mountain terrain … a source characteristic" (F3a — it is a truncated window);
   - acceptance rule 1 PASS, rule 5 "PASS for all", rule 3 "Applied" (branch 2 was not), rule 7's frontier over all candidates (F7);
   - the "live region" sentence and `spatial.yaml: live_candidate_region` (a frontier over an unfiltered, incompletely validated table);
   - all Hanoi semantic-mixing values for `square_850m`, `square_1000m`, `square_2270m`, `h3_r8`, `h3_r7` (F3b contamination), and Finding 4's mixing-error column, which uses Hanoi in its medians.
4. **Retained as diagnostic evidence**, cited with the run id and the word "invalidated run": Finding 1 (H3 actual/nominal 1.1430 — geometry only), Finding 3's POI sparsity table (POI counts do not depend on any raster), Finding 4's ring-Jaccard and lookup-latency columns (geometry only), Finding 5's MAUP table (WorldPop and POI, unaffected), the too-coarse branch-1 counts outside `mu_cang_chai` (the built-up anchor there is affected only on the west fringe), and the admin-qualification verdict (independent artifact).
5. **Numbers that must be re-measured before being cited again**: everything listed in item 3, plus every built-up variance figure (§ 9 policy) and every per-category POI zero share (universe fix).
6. The remediation run's registry entry sets `superseded_by` on this run. Until then, the Gate 2 state is `incomplete`.

---

## 14. Acceptance checklist for an independent reviewer

Each item names the artifact or command that settles it. A "no" on any blocking item keeps Gate 2 at `incomplete`.

**Registry and state**
- [ ] `data/gate2/run_registry.json` lists `run_20260914T091321Z` as `valid: false` with the reasons above, and exactly one later `run_kind: full`, `valid: true` run. (blocking)
- [ ] `config/spatial.yaml: gate2_experiment.status` equals that run's `gate_state`; `spatial_unit.method` is `null` unless the state is `complete_selected` and an owner-approved commit set it. (blocking)
- [ ] `python -m src.spatial.verify_run --run <dir>` exits 0: every file's sha256 matches `SHA256SUMS`, the manifest, and `code_tree_sha256` matches the checked-out commit named in `code_snapshot/git_commit.txt` with `git_dirty: false`. (blocking)

**Coverage**
- [ ] `source_coverage.parquet`: every raster row has `window_inside_tile_union = true`, `truncation_suspected = false`, `processing_coverage ≥ 0.999`, and `expected_valid_pixels` comes from the acquisition sidecar (compare with `data/gate2/aoi_sources/<aoi>/<file>.derived.json`). (blocking)
- [ ] For `mu_cang_chai/ghs_built_s.tif` and `hanoi_core/worldcover.tif`, `expected_tiles` lists two tiles and the clip has no fully-NoData edge band. (blocking)
- [ ] `zonal_coverage.parquet`: Z1–Z4 pass for all candidate × AOI × source rows. (blocking)
- [ ] Running the test suite with the fault-injection tests of § 5.7 present: they fail when the injected fault is active and pass otherwise (inspect the tests, do not take the count). (blocking)

**Completeness**
- [ ] `completeness_report.json: passed = true`, `incomplete_requirements = []`; per-requirement `expected == present`, `duplicate = 0`. (blocking)
- [ ] `candidate_metrics.parquet`: 25 `poi_zero_share` dimensions × 2 supports for every candidate × AOI; `mu_cang_chai` shows `value = 1.0, validity = measured` for the 16 leaves absent there. (blocking)
- [ ] No row has `value` null with `validity = measured`, and no row has `validity ≠ measured` with a non-null value. (blocking)

**Robustness**
- [ ] `robustness_verdicts.parquet` has a row for every (eligible candidate, metric, kind) in § 6.1; H3 × `origin_shift` rows are `not_applicable`; no `blocked` or `not_evaluable` rows in a run claiming `executed_no_decision`. (blocking)
- [ ] Recompute one candidate's `contexts_with_reversal` by hand from `robustness_reversals.parquet` and confirm it matches. (blocking)
- [ ] `decision_matrix.md` renders H3 robustness as "pass on … ; origin_shift not applicable". (blocking)

**Sensitivity**
- [ ] The acquisition manifest has entries for WorldPop 2020, GHS-POP E2020 tiles `R8_C29`, `R7_C29`, `R7_C28`, and the WorldCover class-50 derivations, each with sha256 and parent lineage. (blocking)
- [ ] `population_conservation_relative_error < 1e-9` for every source variant. (blocking)
- [ ] Rankings under `population_epoch` are reported and labelled diagnostic, not used in the verdict. (important)

**Gates and frontier**
- [ ] `hard_gates.parquet` shows the step order of § 7.1; every candidate on `frontier_kind = decision_eligible` has `eligible_after_step = true` at steps 2, 3, 4. (blocking)
- [ ] Too-coarse branch 2 has a verdict per candidate × context, with `not_applicable` for the two finest per family. (blocking)
- [ ] `budget_breakpoints.parquet` exists; `decision_matrix.md` contains no "live region"/"leading" language while `gate_state = executed_no_decision`. (blocking)
- [ ] `square_131m/347m/918m/2429m` have `candidate_set = sensitivity`, appear in `matched_area_shape_comparison.parquet`, and appear in no frontier, no gate table, no robustness table. (blocking)

**Built-up policy**
- [ ] E4 rows for `square_125m`, `h3_r10`, `square_250m` are `not_evaluable:builtup_support_below_min`; E6 rows are `measured` for all. (important)

**Figures**
- [ ] `figures/` contains exactly 64 maps + 18 plots listed in `figure_manifest.json`; open `map_unit_boundaries_hanoi_core.png` and confirm polygon outlines with identical extent in all 11 facets. (blocking)

**Documentation**
- [ ] `docs/spatial_unit_decision.md` § Measured results refers to the new run, carries the withdrawn/retained banner for the old run, and the pre-registered specification above it is byte-identical to the version in this design's git parent. (blocking)
- [ ] `docs/architecture.md` sha256 unchanged (`bd9b5ab7…`). (blocking)

---

## 15. Summary

**Were the review findings confirmed?** Yes — all ten, with two aggravating discoveries. F1 (robustness gate does not test perturbations), F2 (no alternate-source sensitivity), F3 (tautological coverage), F4 (no metric contract; absent POI leaves missing rather than zero), F7 (frontier over gate rejects) and F10 (code/config not preserved) are blocking. F5, F6, F8, F9 are confirmed and important. Three sub-claims were rejected as stated (ring Jaccard/area error, neighbour-degree quantiles, and lookup/benchmark rows all exist) and become contract entries instead. The two new findings, F3a and F3b, are concrete: the `mu_cang_chai` built-up window and the `hanoi_core` land-cover window are truncated at tile boundaries, both were reported at coverage 1.000, and one was narrated in the decision document as a property of the source.

**What must be fixed before Gate 2 can close.** The measurement layer: tile-union clipping and a coverage contract that can fail (§ 5); the metric contract with validity states and the POI leaf universe (§ 3); the perturbation framework and the robustness algorithm (§ 6); alternate population and built-up sources (§ 8); the gate ordering with too-coarse branch 2 and an eligible-only frontier (§ 7); reproducibility snapshots and immutable runs (§ 11); real unit-boundary and diagnostic maps (§ 10). Then one full remediation run, and the state machine decides whether the result is `executed_no_decision` (expected — the administrative family is still blocked and no budget exists) or `incomplete`.

**Corrections that require new data.** Only WP5: two GHS-POP R2023A E2020 tiles (`R7_C29`, `R7_C28`). WorldPop 2020, all WorldCover tiles, and all GHS-BUILT-S tiles needed (including the C28 and N18E105 tiles that were downloaded and never used) are already on disk.

**Corrections that require a full rerun.** All measured outputs: WP2 (re-clipped inputs), WP3 (new metrics), WP4 (perturbations), WP5 (source variants), WP7 (sensitivity candidates), WP8 (figures) are produced by the single full run in WP10. WP0, WP1, WP6 and WP9 are logic and bookkeeping and are verified on synthetic data before the run.

**Handoff instructions for Sonnet.**
1. Read this document in full, then `docs/spatial_unit_decision.md` (do not edit its pre-registered sections), `config/gate2.yaml`, `src/spatial/{metrics,decision,run_gate2,benchmark,plots,candidates}.py`, `src/ingestion/acquire_gate2.py`.
2. Execute WP0 first and commit it. Do not change `spatial_unit.method`. Copy § 1.4 verbatim into `config/gate2.yaml: remediation_parameters` with `declared_on: 2026-09-14`.
3. Execute WP9, then WP1, each with its tests green on synthetic data, each as its own commit. Refuse to proceed to a measurement WP on a dirty tree.
4. Execute WP2 and verify on a smoke run (`--run-kind smoke --aoi hanoi_core --aoi mu_cang_chai`) that both formerly truncated clips now have `window_inside_tile_union = true` and no edge band; confirm the fault-injection tests fail when the fault is active.
5. Execute WP3, WP4, WP5 (network: two tiles), WP6, WP7, WP8 in that order, smoke-running after WP4 and WP7.
6. Commit, then run WP10: `python -m src.ingestion.acquire_gate2` → `python -m src.spatial.run_gate2 --run-kind full` → `python -m src.spatial.verify_run --run <dir>` → `python -m pytest tests/ -v`.
7. Update the registry, `config/spatial.yaml: gate2_experiment` (status only), and `docs/spatial_unit_decision.md` § Measured results. Fill in the § 14 checklist with artifact paths and hand the run id back for independent review.
8. Stop there. Do not select a spatial unit, do not write a feasibility budget, do not start Gate 3.
