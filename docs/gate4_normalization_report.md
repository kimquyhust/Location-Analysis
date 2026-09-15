# Gate 4 Contextual Normalization — report

_Status: **four-AOI normalization experiment executed; artifact verdict CONDITIONAL GO (§ 13).** Run `run_20260914T175737Z`, directory `data/gate4/run_20260914T175737Z/` (immutable; every output in `SHA256SUMS`), **normalization version 0.1.0** over the reviewed Gate 3 input `run_20260914T171148Z` (feature set 0.3.0, untouched: its `SHA256SUMS` still verifies 8/8). Contract: `config/gate4_mvp.yaml` (1.0.0). Written 2026-09-15 for independent review. No customer/mobility data, no semantic scores, no new source, no change to `config/features.yaml` or `docs/architecture.md`, no commits._

## 1. What normalization is for here, and what it is not

Atomic features (Gate 3) describe a cell in physical units: people, km of road, counts of mapped entities. Contextual normalization re-expresses such a value relative to a reference so that cells can be compared: relative to the shape of its own distribution (`log1p`), relative to a fitted reference cohort (percentiles), or relative to its immediate geographic neighbors (local ratio). The atomic value is always kept; every contextual column names its source feature, formula, reference/cohort id, normalization version and an explicit status, and joins 1:1 to `atomic_features.parquet` on `spatial_unit_id`.

What Gate 4 must not do with the input it has: call a percentile over four hand-picked AOIs a *national* percentile; call a percentile within one AOI a *peer* percentile; derive an urban/rural class from a threshold and call it GHS-SMOD; or turn a null or failure status into a number. The four AOIs are the Gate 2 test geography — one AOI per `aoi_context` — and `aoi_context` is experiment metadata, not a source-defined settlement class (§ 4, § 7).

## 2. Gate 3 input and inherited limitations

| | |
|---|---|
| Input | `data/gate3/run_20260914T171148Z/` — 5,681 H3 r9 rows, 99 public columns, feature set 0.3.0, taxonomy 0.3.0; `atomic_features.parquet` SHA-256 `26d75dd0…`, `feature_manifest.json` `1cd97295…`, `run_manifest.json` `ae37aa53…`, `validation_summary.json` `43dca9e7…` — all four pinned in `config/gate4_mvp.yaml → input.sha256` and re-verified at run start (`verify_gate3_input`), together with the run's own `SHA256SUMS`, `gate = 3`, `run_kind = atomic_feature_mvp`, `validation_passed = true`, 5,681 rows and the four AOI ids. Any mismatch fails before anything is computed (tested with a wrong hash, a wrong run id, the superseded 0.2.0 run directory and a wrong feature-set version). |
| AOIs | `hanoi_core` 356 rows (dense_urban), `hoi_an` 1,317 (tourism), `mu_cang_chai` 2,053 (rural_mountain), `dong_thap_rural` 1,955 (rural_delta); row shares 6.3 / 23.2 / 36.1 / 34.4 %. |
| Inherited, kept verbatim | six features null `entity_assembly_failed` on all 356 Hanoi rows (`park_recreation_count_1km`, `distance_nearest_park_m`, `osm_industrial_site_area_ratio`, `distance_nearest_osm_industrial_site_m`, `poi_total_count_1km`, `poi_category_richness_1km`); `distance_nearest_urban_centre_km` null `source_not_acquired` everywhere; admin codes absent; distance features 41–59 % null `search_truncated_by_extract` (up to 100 % in Mù Cang Chải); denominator statuses (`denominator_zero` 322 rows, `denominator_below_minimum` 24) on the land-support-denominated features; OSM rural coverage an order of magnitude sparser than Hanoi (rural zeros are *mapped* zeros). |
| Not representative | ~600 km² in four contexts; nothing here is a national distribution. |

Every one of these statuses propagates unchanged into every Gate 4 column that reads the feature (validator check `atomic failure status not propagated verbatim`; artifact test), and no Gate 4 column has fewer nulls than its atomic input (`missingness ≥ atomic` check).

## 3. Design: layer, versioning, artifact

- **Own contract and version.** `config/gate4_mvp.yaml` carries `normalization_version: "0.1.0"`, the pinned input, every candidate feature list, formulas, the fit cohorts, tie policy, neighborhood policy, minimum sample/coverage requirements, status propagation and — written *before* any candidate output was inspected — the rule that decides publishable vs diagnostic per candidate. `config/features.yaml` is byte-identical to the Gate 3 pin (`515ac315…`); `contextual_features.enabled` stays `false` and `validate_config` refuses to run if it is flipped without review.
- **Fit / apply are separate steps.** `fit_ecdf` writes one ECDF table per (cohort, feature, weighting) to `cohort_statistics.parquet` (109,052 rows: 5 cohorts × 27 features × 1–2 weightings); `apply_ecdf` reads *only* that table; a cohort absent from it yields `cohort_not_fitted`, never an implicit refit (tested: apply from the parquet on disk equals apply in memory bit-for-bit).
- **Two output tables** with the same 5,681 keys in Gate 3 row order: `contextual_features.parquet` holds only columns whose pre-registered rule was met (**publishable**, 23 value columns + statuses, 60 columns total); `diagnostic_features.parquet` holds everything else (57 value columns + statuses + cohort ids, 130 columns). The validator fails if a column sits in the wrong table for its disposition. Neither table copies the 99 atomic columns; both carry `spatial_unit_id, aoi_id, aoi_context, run_id (Gate 3), feature_set_version, source_manifest_id, normalization_version, normalization_run_id, gate3_run_id, computed_at_utc`.
- **Manifest.** `normalization_manifest.json` pins the Gate 3 run id, the four input hashes, Gate 3's own code version / config hash / config SHA-256s, feature-set and taxonomy versions, the Gate 4 config hash and per-file SHA-256s, the fitted cohort definitions (members, rows, weightings, per-feature fit status / n_obs / n_distinct), every column's spec (source feature, transform, formula, cohort id or cohort-id column, weighting, tie method, unit, disposition, status counts), the peer-percentile block record, the GHS-SMOD `source_not_acquired` record, and why distances are excluded. `run_manifest.json` (gate 4, `run_kind contextual_normalization_mvp`) adds code version `59fe994+dirty`, environment, artifact bytes/hashes. No absolute paths (tested).
- **Modules.** `src/normalization/transforms.py` (pure fit/apply/ratio; no I/O; inputs not mutated — tested), `schema.py` (config validation against the atomic contract; output validation), `run_gate4_mvp.py` (orchestration; `--output-root` for determinism checks). Runtime 4.3 s, peak RSS 0.29 GB; outputs 2.4 MB.

## 4. Distributions of the candidate inputs (why transform at all)

Pooled over the 4 AOIs, non-null values (full per-AOI quantiles, null/zero rates and status counts in `validation_summary.json → distributions`):

| feature | null | zero (of valid) | skew raw → log1p | distinct | note |
|---|---:|---:|---|---:|---|
| population_count | 0 | .23 | 5.06 → 0.40 | 4,348 | zeros are Mù Cang Chải (47 % zero there) |
| population_density | .06 | .19 | 4.76 → −0.20 | 4,333 | |
| road_length_km | 0 | .42 | 2.35 → 1.19 | 3,279 | |
| road_density_km_per_km2 | .06 | .39 | 9.65 → 0.33 | 3,275 | |
| major_road_length_km | 0 | **.86** | 4.72 → 3.47 | 810 | zero-dominated |
| intersection_density_per_km2 | .06 | .64 | 4.37 → 0.96 | 1,945 | |
| poi_total_count_1km | .06 | .62 | 11.04 → 2.19 | 204 | null = Hanoi assembly failure |
| poi_category_richness_1km | .06 | .62 | 2.81 → 1.29 | 20 | |
| food_drink_count_1km | 0 | .79 | 8.37 → 2.58 | 264 | Hanoi median 80, rural 0 |
| retail_count_1km | 0 | .77 | 6.86 → 2.77 | 249 | |
| lodging_count_1km | 0 | .79 | 10.61 → 2.88 | 152 | |
| attraction_culture_count_3km | 0 | .51 | 3.56 → 1.44 | 152 | |
| hospital_count_3km | 0 | .72 | 4.52 → 2.21 | 55 | |
| higher_education_count_3km | 0 | .75 | 5.43 → 2.85 | 42 | |
| transit_stop_count_1km | 0 | .84 | 4.85 → 2.86 | 68 | |
| school_count_1km | 0 | .84 | 4.79 → 3.10 | 29 | |
| marketplace_count_1km | 0 | .87 | 5.10 → 2.98 | 11 | |
| park_recreation_count_1km | .06 | .90 | 6.68 → 3.85 | 25 | |
| pharmacy_count_1km | 0 | **.92** | 5.69 → 4.02 | 31 | 100 % zero in MCC and Đồng Tháp |
| clinic_count_1km | 0 | **.93** | 8.00 → 4.59 | 25 | 100 % zero in MCC |
| mall_count_3km | 0 | **.94** | 6.12 → 4.35 | 14 | non-zero only in Hanoi |
| built_up_ratio | .06 | .40 | 2.35 → 2.09 | 3,227 | ratio; not a log1p candidate |
| tree / grass-shrub / cropland / water-wetland ratio | 0 | .09 / .27 / .43 / .71 | 0.29 / 1.70 / 1.66 / 2.35 | | ratios |
| osm_industrial_site_area_ratio | .12 | **.99** | 22.2 → 20.7 | 28 | 28 non-zero cells in total |

Two facts drive everything below. (i) Every count/density/length feature is strongly right-skewed pooled, but mostly because the AOIs differ by orders of magnitude (Hanoi skew of `food_drink_count_1km` is 2.3, Mù Cang Chải 5.8 with 97 % zeros). (ii) Zero mass is large and *context-dependent*: eleven count features are ≥ 75 % zero pooled and several are 100 % zero in one or two rural AOIs. A monotone transform cannot separate tied zeros; a cohort-based transform assigns all of them one percentile (§ 6).

**Distances are excluded from every transform** (`feature_groups.distances_excluded`; `validation_summary.json → distance_selection_bias`). Their nulls are not random: an `ok` value exists only when the nearest entity lies inside the row's complete-search radius (`ok_values_bounded_by_complete_radius = true` in every AOI/feature with any ok row), so the observed values are right-censored at ≈ 4.3–5.6 km (median complete radius per AOI) and the null rows are precisely the far cells. `distance_nearest_park_m` is ok for 100/88/0/66 % of rows in Hanoi(assembly-failed)/Hội An/MCC/Đồng Tháp; `distance_nearest_hospital_m` ok for 100/67/23/74 %, with the MCC ok-median (5.3 km) already near the censoring radius. A `log1p` or percentile fitted on the ok rows would be fitted on the near half of a censored sample and would read "null" as "far" without saying so. Deferred until the halo/extract strategy changes (Gate 3 condition (c)); nothing in Gate 4 touches them.

## 5. Candidate A — `log1p` (publishable, 21 columns)

**Definition.** `log1p_<feature> = ln(1 + x)`, x the atomic value in its own unit; unit `log(1 + <unit>)`; `0 → 0` exactly; null stays null with the atomic status copied verbatim; a negative finite input fails the run (`TransformInputError`); no imputation, clipping or winsorizing (config `rules`, enforced by `validate_config`). Candidates: the 15 count features and the 6 density/length features; ratios on [0, 1] are refused by `validate_config` (a bounded input gains nothing from `log1p`), distances per § 4.

**Pre-registered publish rule** (`transforms.log1p.publish_rule`): pooled raw skewness ≥ 1.0 and |skew(log1p)| < |skew(raw)|. Result: **all 21 candidates meet it** (table in § 4; `normalization_manifest.json → candidates.log1p`). Statuses: exactly the atomic status counts (e.g. `log1p_poi_total_count_1km`: 5,325 ok, 356 `entity_assembly_failed`; `log1p_population_density`: 5,335 ok, 322 `denominator_zero`, 24 `denominator_below_minimum`).

**Caveat stated, not hidden.** For the zero-dominated counts (`major_road_length_km`, `pharmacy`, `clinic`, `mall`, `park_recreation`, `marketplace`, `school`, `transit_stop`: 84–94 % zero) the rule is met — skew falls — but `log1p` leaves the zero mass where it is; the output is still a zero-inflated variable, only with a compressed positive tail. Consumers should read these columns together with the atomic zero (mapped zero, not proven absence). Whether such a column is *useful* is a downstream question; it is *correct*, reversible (`expm1`), per-row (no cohort dependence, hence stable), and its lineage is complete. Stability: `log1p` is a fixed function; a rerun is bit-identical (§ 11).

## 6. Candidate B — percentiles

Formula (`midrank_ecdf`, config `tie_method`): `F(x) = (W_below(x) + 0.5·W_equal(x)) / W_total` over the fitted cohort's `ok` values, W the row weights (cell: 1; AOI-equal: 1 / rows in the AOI). Deterministic; equal inputs get equal outputs; range (0, 1) for fitted values, [0, 1] inclusive for unseen values beyond the fitted range; `min_ecdf` / `max_ecdf` computed from the same table as tie sensitivities. `minimum_cohort_size: 30` valid rows (else `cohort_too_small`); one distinct value → `cohort_degenerate` (config `constant_cohort_policy: null_with_status`). 27 candidate features (21 above + 6 ratios).

### 6.1 `mvp_pooled_percentile` — diagnostic

Cohort `mvp_pooled::0.1.0::gate3_20260914T171148Z`, all four AOIs, cell-weighted primary. All 27 × 2 fits are `ok`. **It is not a national percentile** (name forbidden by config and validator) and it is not published: (a) the cohort composition is arbitrary — four AOIs chosen for spatial-unit testing, 70 % of rows rural; (b) a cell's value therefore says where it sits among *these* 5,681 cells, which changes whenever an AOI is added. Measured (`validation_summary.json → percentile.sensitivity`):

- **Pooled vs within-AOI.** Per-AOI median of the pooled percentile for `population_density`: Hanoi **0.97**, Hội An 0.71, Đồng Tháp 0.63, Mù Cang Chải 0.20 (within-AOI medians are 0.50 by construction). Mean |pooled − within| per feature 0.04–0.46 (median over features ≈ 0.11); for `mall_count_3km` 0.46 because within-AOI is defined only in Hanoi. The pooled percentile is essentially an AOI indicator plus a within-AOI rank.
- **Cell-weighted vs AOI-equal-weighted.** Because Mù Cang Chải + Đồng Tháp carry 70 % of the cells, cell weighting pushes every urban row up: mean (pooled_cell − pooled_aoi_equal) is +0.08 (Hanoi), +0.13 (Hội An), +0.12 (Đồng Tháp), +0.06 (MCC) for `population_density`; per-feature mean |Δ| 0.03–0.12, max |Δ| up to 0.20 (`attraction_culture_count_3km`). The sign flips for `tree_cover_ratio` (−0.05 to −0.07): weighting decides the answer, and the four-AOI table offers no principled weight.
- **Leave-one-AOI-out (transform stability).** Refitting the pooled cohort without one AOI moves the remaining cells' percentiles by a mean of up to **0.16–0.18** (`population_density`, `built_up_ratio`, MCC held out; max 0.27–0.33) and by 0.03–0.10 for most other features. A reference that shifts by a sixth of its range when one of four members is removed is not a stable reference.
- **Ties / zero mass.** Share of `ok` rows sitting in tie groups: 0.14 (`tree_cover_ratio`) to **1.00** (every count feature: integers). The percentile assigned to a zero under midrank is 0.5 × zero share — e.g. 0.43 for `major_road_length_km`, 0.47 for `clinic_count_1km`, 0.50 for `osm_industrial_site_area_ratio` — and would be 0 under `min_ecdf` or 0.86 / 0.94 / 0.99 under `max_ecdf` (`tie_methods` block). For a feature that is 90 % zero the tie policy, not the data, chooses the value of nine cells in ten.

### 6.2 `within_aoi_percentile` — diagnostic

Cohorts `within_aoi::<aoi_id>::0.1.0::gate3_…`, 4 × 27 fits: 104 `ok`, **11 `cohort_degenerate`** (all-zero AOI/feature pairs: `mall_count_3km` in Hội An, MCC, Đồng Tháp; `pharmacy`, `clinic`, `school`, `transit_stop`, `marketplace`, `higher_education`, `park_recreation`, `osm_industrial_site_area_ratio` in MCC; `pharmacy`, `mall` in Đồng Tháp), **4 `cohort_too_small`** (the Hanoi assembly-failed features, 0 valid rows). Those rows carry the fit status, not a value. Useful as an internal ranking; not comparable across AOIs by construction (every AOI's median is 0.5 whether it is Hanoi or a mountain district), so not publishable as a *contextual* feature.

### 6.3 `peer_percentile` — blocked (`peer_cohort_insufficient`)

Peer group column `aoi_context`; requirement `minimum_aois_per_peer_group: 2` (config; `validate_config` refuses 1). The input has exactly one AOI per context (`aois_per_context` all 1), so a "peer" cohort would be a single AOI: identical to § 6.2 and unable to say anything about the context beyond that one AOI. **No peer cohort was fitted and no `peer_percentile` column exists in either table** (validator and artifact test). Disposition recorded in the manifest with the reason. The smallest input that unblocks it: a second AOI in each context (the four deferred Gate 2 AOIs `hcmc_core`, `thu_duc_east`, `binh_duong_industrial`, `phu_quoc_coast` supply a second `dense_urban` and a second `tourism`; `rural_delta`/`rural_mountain` need new AOIs), *and* a reviewed definition of what a peer group is once a source-defined settlement class exists (§ 8).

## 7. Candidate C — local density ratio (2 publishable, 3 diagnostic)

**Definition** (`transforms.local_ratio`): `local_ratio_k1_<feature> = x / median(x over the 6 H3 k=1 neighbors, centre excluded)`, dimensionless. Policy fixed in config before computing: H3 `grid_disk`, k = 1, centre excluded (a policy including the centre is refused), reference statistic median (mean computed as a sensitivity, not emitted), **every** k-ring neighbor must be present in the table (else `neighborhood_incomplete`), at least 4 of the present neighbors must be `ok` (else `neighborhood_insufficient_valid`), reference 0 → null `neighborhood_reference_zero` (config `denominator_zero_policy: null_with_status`; an `epsilon` policy is refused by `validate_config`). The centre's atomic status is copied when it is not `ok`. Candidates: `population_density`, `road_density_km_per_km2`, `intersection_density_per_km2`, `poi_total_count_1km`, `food_drink_count_1km`.

**Neighborhood completeness.** AOI boundaries are not geographic boundaries, so the ring test is reported for AOI-interior and AOI-edge cells separately: ring complete for **100 % of the 5,017 interior cells** and 13 % of the 664 edge cells in every AOI (pooled 5,103 / 5,681 complete). Every incomplete ring is at the run's own extent, i.e. an artifact of the four-AOI table, not of the place; those 578 rows are null with `neighborhood_incomplete` and the validator rejects any value on an incomplete ring. In a contiguous (nationwide) table only coastline/border cells would be incomplete.

**Pre-registered publish rule** (`minimum_finite_share_of_eligible: 0.5`): among rows whose centre is `ok`, ring complete and ≥ 4 neighbors valid, the ratio must be finite (reference ≠ 0) for at least half. Results:

| feature | eligible | finite | reference 0 | finite share | Hanoi / Hội An / MCC / Đồng Tháp finite share | disposition |
|---|---:|---:|---:|---:|---|---|
| population_density | 4,775 | 4,004 | 771 | **0.84** | 1.00 / 1.00 / 0.59 / 1.00 | publishable |
| road_density_km_per_km2 | 4,775 | 3,407 | 1,368 | **0.71** | 1.00 / 0.97 / 0.38 / 0.90 | publishable |
| poi_total_count_1km | 4,820 | 1,997 | 2,823 | 0.41 | — (assembly failed) / 0.80 / 0.14 / 0.45 | diagnostic |
| intersection_density_per_km2 | 4,775 | 1,876 | 2,899 | 0.39 | 0.97 / 0.90 / 0.15 / 0.28 | diagnostic |
| food_drink_count_1km | 5,103 | 1,134 | 3,969 | 0.22 | 0.98 / 0.58 / 0.03 / 0.07 | diagnostic |

Where the neighborhood is mostly zero (rural counts) the ratio is undefined for most cells, and that is reported as such rather than made finite. Mean-reference sensitivity: finite share 0.94 / 0.80 (published two) vs 0.84 / 0.71 with the median, Spearman ρ between the two references where both are finite 0.92 / 0.95; for the diagnostic three ρ = 0.69–0.95. The median was pre-registered and kept.

**Limitations of the two published columns, stated.** (1) The ratio is unbounded above and has a heavy right tail where the neighborhood median is tiny but non-zero: `population_density` p95 is 1.5 (Hanoi), 3.4 (Hội An), 3.3 (Đồng Tháp) and **18.2 (Mù Cang Chải)**; `road_density` p95 8.3 in MCC. No floor is applied because any floor would be an arbitrary constant; consumers must treat the column as a ratio, not a score. (2) 58 % (MCC) / 38 % finite share means the column is null for most mountain cells with the explicit reason `neighborhood_reference_zero`. (3) The neighborhood is 6 cells of ~0.1 km² each (≈ 0.6 km² reference), a very local reference; k was pre-registered at 1 and no other k was tried. (4) The ratio inherits the Gate 3 denominators (322 + 24 rows null by denominator status) and is null at the run extent. Statuses per AOI are in `validation_summary.json → local_ratio.features.*.per_aoi`.

## 8. Candidate D — `source_defined_ghs_smod_class`: `source_not_acquired`

GHS-SMOD R2023A is not in `data/raw` and was not downloaded in this session. No column exists; the manifest records `status: source_not_acquired, enabled: false, substitute_with_custom_threshold: false`, and `validate_config` refuses a config that enables it or substitutes a population/built-up threshold for it. Without it there is no source-defined settlement class, and therefore no defensible peer-group definition beyond the experiment's `aoi_context` label.

## 9. Output contract (what a consumer gets)

`contextual_features.parquet` — 5,681 rows, 60 columns: 10 key/lineage columns, 4 neighborhood columns (`neighborhood_k_ring`, `neighborhood_neighbor_count`, `neighborhood_neighbors_present`, `neighborhood_complete`), and 23 value columns each with `<column>_status`:

- `log1p_population_count`, `log1p_population_density`, `log1p_road_length_km`, `log1p_road_density_km_per_km2`, `log1p_major_road_length_km`, `log1p_intersection_density_per_km2`, `log1p_transit_stop_count_1km`, `log1p_school_count_1km`, `log1p_higher_education_count_3km`, `log1p_hospital_count_3km`, `log1p_clinic_count_1km`, `log1p_pharmacy_count_1km`, `log1p_food_drink_count_1km`, `log1p_retail_count_1km`, `log1p_marketplace_count_1km`, `log1p_mall_count_3km`, `log1p_lodging_count_1km`, `log1p_attraction_culture_count_3km`, `log1p_park_recreation_count_1km`, `log1p_poi_total_count_1km`, `log1p_poi_category_richness_1km`;
- `local_ratio_k1_population_density`, `local_ratio_k1_road_density_km_per_km2`.

`diagnostic_features.parquet` — 130 columns: the same lineage, `mvp_pooled_cohort_id`, `within_aoi_cohort_id`, 27 × `<feature>_mvp_pooled_percentile`, 27 × `<feature>_within_aoi_percentile`, 3 × `local_ratio_k1_<feature>` (diagnostic ones), each with a status. Not for production use; kept so the sensitivity numbers in § 6–7 are reproducible from the artifact.

Status vocabulary (manifest `status_vocabulary`): the nine Gate 3 statuses passed through verbatim plus `cohort_too_small`, `cohort_degenerate`, `cohort_not_fitted`, `peer_cohort_insufficient`, `neighborhood_incomplete`, `neighborhood_insufficient_valid`, `neighborhood_reference_zero`. A value exists iff the status is `ok`.

## 10. Validation (artifact)

`validation_summary.json → schema` (both tables `passed: true`): unique non-null `spatial_unit_id`; key set, row count and row order identical to Gate 3; all four AOIs present; lineage columns present and uniform; `gate3_run_id`/`normalization_version` equal the config; no bare null and no value with a failure status; finite values; percentiles in [0, 1]; non-negative `log1p` outputs and `log1p(0) = 0` against the atomic table; non-negative ratios and no value on an incomplete ring; statuses from the declared vocabulary; atomic failure statuses propagated verbatim; missingness never below the atomic input; every cohort id referenced by a row present in the manifest; no column matching `customer|trip|pickup|dropoff|od_flow|_score|national_percentile|segment`; publishable and diagnostic columns each in their own table; every value column specified in the manifest. Input verification (§ 2) and config validation (§ 3) run before computation. `SHA256SUMS`: 7 entries, verified at write time and again by the artifact test.

**Independent recomputation outside `src/normalization`** (numpy/pandas/h3 only, in-session): every published `log1p` column equals `np.log1p` of the atomic column bit-for-bit with statuses preserved; the pooled and each within-AOI `population_density` percentile equal a rank-based midrank ECDF to 0.0 / < 1e-12; the 4,004 finite `local_ratio_k1_population_density` values equal `x / median(ok neighbors)` recomputed from `h3.grid_disk` with 0 mismatches, and every null carries the expected status; run-manifest artifact hashes match disk.

## 11. Tests

`tests/test_normalization.py` — 23 tests: `log1p(0) = 0` and ln(1+x) values; null stays null with the atomic status; a value under a failure status or a bare null is a contract error; negative input fails; inputs not mutated; percentiles in [0, 1] and monotone; midrank/min/max tie handling equals the formula, bit-identical on repeat, unseen values in range; constant and too-small cohorts give null + status; failed rows excluded from the fit and their status kept; apply from persisted `cohort_statistics.parquet` equals in-memory apply and a missing cohort is `cohort_not_fitted`; AOI-equal weights sum to 1 per AOI and differ materially from cell weights when one AOI dominates; peer cohort blocked with one AOI per context and unblocked with two; local ratio reference 0 → null + status with no epsilon and a real 0/2 = 0 kept; incomplete ring / insufficient valid neighbors → status, failed centre keeps its atomic status; policy refuses centre inclusion; config valid and pinned; config rejects ratio `log1p`, distance percentile, the name `national_percentile`, peer minimum 1, an epsilon policy, a GHS-SMOD substitute; forbidden columns detected; wrong hash / run id / superseded run / wrong version fail before computing; the real artifact's keys, lineage, checksums, dispositions, manifest and absence of peer/forbidden columns; the real artifact's values against Gate 3 column by column; **a rerun into a temporary directory is identical to the published run outside `normalization_run_id`/`computed_at_utc`**; sensitivities present in the summary.

```
.venv/bin/python -m pytest tests/test_normalization.py -v            # 23 passed
.venv/bin/python -m pytest tests/ -q                                   # 317 passed (294 + 23)
.venv/bin/python -m compileall -q src tests                            # ok
git diff --check                                                       # ok
( cd data/gate3/run_20260914T171148Z && shasum -a 256 -c SHA256SUMS )  # 8 × OK (input unchanged)
( cd data/gate4/run_20260914T175737Z && shasum -a 256 -c SHA256SUMS )  # 7 × OK
```

## 12. Disposition summary

| candidate | columns | disposition | reason |
|---|---|---|---|
| `log1p` counts / densities / lengths | 21 | **publishable** | pre-registered skew rule met by all; per-row, reversible, cohort-free; zero-mass caveat § 5 |
| `local_ratio_k1` population density, road density | 2 | **publishable** (with the § 7 limitations) | ≥ 50 % finite among eligible; geographic reference, no cohort; null with reason at the run extent and where the neighborhood is zero |
| `local_ratio_k1` intersection density, POI total, food & drink | 3 | diagnostic | reference-zero dominates (finite share 0.22–0.41) |
| `mvp_pooled_percentile` | 27 | diagnostic | arbitrary four-AOI cohort; AOI-weighting and leave-one-AOI-out shift values by up to 0.13 / 0.18 mean; not a national percentile |
| `within_aoi_percentile` | 27 | diagnostic | not comparable across AOIs; 15 of 108 fits degenerate/too small |
| `peer_percentile` | 0 | **blocked** | one AOI per context; no column emitted |
| `source_defined_ghs_smod_class` | 0 | **blocked** | `source_not_acquired`; no substitute |
| distance features (all transforms) | 0 | deferred | right-censored by the halo; selection bias documented § 4 |

## 13. Verdict

**CONDITIONAL GO** for normalization version 0.1.0 over the four-AOI input.

Met: a separate, versioned normalization contract with pre-registered publish rules; fit and apply separated with persisted cohort statistics; 23 contextual columns whose formula, source, lineage and status are complete and which were verified independently; every atomic null/status preserved and nothing imputed, clipped or made finite by a constant; the Gate 3 artifact untouched; `feature_set_version` 0.3.0 unchanged; no national, peer or settlement-class claim; no Gate 5 / customer / mobility logic; tests, compile, diff and both checksum sets pass; a rerun is identical.

Why not GO: the transforms that would make cells *comparable across contexts* — peer percentiles and a source-defined settlement class — are blocked by the cohort (one AOI per context) and by a missing source, and the pooled percentile is demonstrably a function of which AOIs happen to be in the table. What is published is the cohort-free part of the layer: per-row `log1p` and a strictly local ratio for two density features. Neither claims nationwide comparability.

Why not NO-GO: the published columns are not only within-AOI/pooled diagnostics; they generalize by construction (no fitted reference), their missingness and lineage are preserved, and the diagnostics are labelled and separated.

Conditions: (a) production enablement (`config/features.yaml → contextual_features.enabled`) only after independent review of this run; (b) the two local-ratio columns carry the § 7 limitations (unbounded tail, null-dominant in sparse mountain cells, null at the run extent) and must be re-evaluated on a contiguous table; (c) the zero-dominated `log1p` columns remain zero-inflated; (d) code uncommitted (`59fe994+dirty`).

## 14. Next smallest data requirement

1. **Acquire and pin GHS-SMOD R2023A** (Degree of Urbanisation, 1 km) for the four halos — one raster, no new pipeline — so that `source_defined_ghs_smod_class` can be emitted as a source-defined class and a peer group can be defined by source, not by the experiment label.
2. **A second AOI per context**: run Gate 3 unchanged on `hcmc_core` (dense_urban) and `phu_quoc_coast` (tourism), which already have Gate 2 acquisitions pending, and pick one additional rural-delta and one rural-mountain AOI. With ≥ 2 AOIs per context the `peer_percentile` block lifts mechanically (`minimum_aois_per_peer_group` is met) and the leave-one-AOI-out statistic in § 6.1 becomes a within-context stability test.
3. Only then revisit the local-ratio k and the distance transforms (the latter also need the relation-completing extract from Gate 3's next step).

**Recommendation for independent review (no change made to `docs/architecture.md`):** § 5 of the architecture lists "national percentile" as a candidate contextual transform. The evidence here suggests replacing that wording with "percentile against a *named, versioned reference cohort* (national only when fitted on a nationwide table)", so that the reference is always part of the column's identity.

## 15. Reproduction

```bash
# input: the reviewed Gate 3 run must verify
( cd data/gate3/run_20260914T171148Z && shasum -a 256 -c SHA256SUMS )
# full run -> data/gate4/run_<UTC>/  (~5 s)
.venv/bin/python -m src.normalization.run_gate4_mvp
# determinism check into a scratch root (no run directory under data/ is written)
.venv/bin/python -m src.normalization.run_gate4_mvp --output-root /tmp/gate4_check
# verify this run
( cd data/gate4/run_20260914T175737Z && shasum -a 256 -c SHA256SUMS )
.venv/bin/python -m pytest tests/test_normalization.py -v
```
