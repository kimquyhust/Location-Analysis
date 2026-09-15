# Gate 2 MVP decision matrix — provisional H3 resolution

_Run `20260914T102642Z`. Owner-approved scope reduction: H3 is the provisional MVP family; this run decides the resolution only. It is NOT evidence that H3 is universally optimal — see `docs/gate2_mvp_decision.md`._

**Outcome: SELECT `h3_r9` (H3 resolution 9) — status `provisional_mvp`, selection rule 1 fired.**

## Scope

- family: `h3`; candidates: h3_r8, h3_r9, h3_r10
- AOIs: dong_thap_rural, hanoi_core, hoi_an, mu_cang_chai
- candidate x AOI pairs: 12 / 12
- lookup correctness/determinism failures: 0
- deferred (not measured here): square_grid_family, administrative_family, h3_r7, origin_shift_replicates, alternate_population_source_sensitivity, alternate_builtup_source_sensitivity, semantic_mixing, neighborhood_representation, maup_stability, robustness_gate, pareto_selection, nationwide_validation

## Rule

For every resolution x AOI and each anchor (poi_count_1km, population_1km, road_length_1km_m; 1 km support), the median within-cell sample-point range is divided by the between-cell IQR. An anchor triggers when the ratio exceeds 0.25. A resolution is **rejected in a context** when at least 2 anchors trigger; it **passes** only if rejected in no MVP AOI.

Selection order: `h3_r9` → `h3_r10` → `h3_r8` (default, finer fallback, coarser alternative); the coarser alternative additionally needs lower projected nationwide unit count and storage than the default and no greater within-cell loss.

## Anchors triggered per resolution x AOI

| candidate_id | dong_thap_rural | hanoi_core | hoi_an | mu_cang_chai |
|---|---|---|---|---|
| h3_r8 | 2 | 3 | 3 | 2 |
| h3_r9 | 0 | 0 | 0 | 1 |
| h3_r10 | 0 | 0 | 0 | 1 |

## Loss ratios (within-cell median range / between-cell IQR)

| candidate_id | aoi_id | ratio_poi_count_1km | ratio_population_1km | ratio_road_length_1km_m | anchors_triggered | rejected_in_context |
|---|---|---|---|---|---|---|
| h3_r8 | dong_thap_rural | 3.598e-15 | 0.4359 | 0.4822 | 2 | True |
| h3_r9 | dong_thap_rural | 2.183e-15 | 0.1691 | 0.2085 | 0 | False |
| h3_r10 | dong_thap_rural | 1.046e-15 | 0.05 | 0.07782 | 0 | False |
| h3_r8 | hanoi_core | 0.3046 | 0.2758 | 0.4048 | 3 | True |
| h3_r9 | hanoi_core | 0.1515 | 0.1215 | 0.197 | 0 | False |
| h3_r10 | hanoi_core | 0.04904 | 0.04174 | 0.07752 | 0 | False |
| h3_r8 | hoi_an | 0.2667 | 0.4281 | 0.479 | 3 | True |
| h3_r9 | hoi_an | 0.1053 | 0.1874 | 0.2186 | 0 | False |
| h3_r10 | hoi_an | 0.05263 | 0.07466 | 0.07741 | 0 | False |
| h3_r8 | mu_cang_chai | 1.179 | 0.08288 | 0.2539 | 2 | True |
| h3_r9 | mu_cang_chai | 0.9251 | 0.03348 | 0.08946 | 1 | False |
| h3_r10 | mu_cang_chai | 0.4499 | 0.01248 | 0.03101 | 1 | False |

## Verdicts

- `h3_r9`: **PASS** — rejected in no context
- `h3_r10`: **PASS** — rejected in no context
- `h3_r8`: **FAIL** — rejected in ['dong_thap_rural', 'hanoi_core', 'hoi_an', 'mu_cang_chai']

Coarser-alternative check (rule 3, recorded regardless of which rule fired): default/coarser projected unit ratio 6.66, storage ratio 4.68; median loss ratio coarser 0.355 vs default 0.16; cheaper=True, no_greater_loss=False.

## Candidate summary (medians across the four AOIs; nationwide figures are PROJECTIONS)

| candidate_id | units_total_4_aois | cell_area_km2_median | cell_area_km2_p05 | cell_area_km2_p95 | nationwide_units_projected | nationwide_storage_bytes_projected | poi_zero_share_footprint | poi_zero_share_1km | population_zero_share | population_median | road_zero_length_share | road_length_median_m | within_cell_loss_ratio_median | runtime_s_total | peak_rss_bytes | lookup_single_p50_us | lookup_single_p95_us | lookup_failures |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| h3_r8 | 893 | 0.8135 | 0.8128 | 0.8141 | 4.656e+05 | 9.64e+07 | 0.6923 | 0.2333 | 0.07997 | 518.4 | 0.108 | 4051 | 0.3547 | 1.618 | 692453376 | 1.937 | 2.041 | 0 |
| h3_r9 | 5681 | 0.1162 | 0.1161 | 0.1163 | 3.102e+06 | 4.51e+08 | 0.88 | 0.2151 | 0.1415 | 44.22 | 0.2807 | 504.4 | 0.1603 | 2.22 | 698253312 | 1.917 | 2.062 | 0 |
| h3_r10 | 3.829e+04 | 0.0166 | 0.01659 | 0.01661 | 2.088e+07 | 2.656e+09 | 0.9593 | 0.2118 | 0.247 | 3.305 | 0.537 | 25.32 | 0.05131 | 5.48 | 706576384 | 1.958 | 2.104 | 0 |

## What this does and does not settle

- It settles which H3 resolution the MVP atomic-feature layer is keyed to, provisionally.
- It does not compare H3 with square grids or administrative units (deferred), does not validate nationwide (Gate 6), and does not test robustness to alternate sources or perturbations.
- Nationwide unit counts and storage are extrapolations from four AOIs (~ 600 km2) to 331,212 km2.
