# Gate 2 decision matrix

**Outcome: NO DECISION.** `config/spatial.yaml` `spatial_unit.method` stays `null`.

## Blockers

- no owner feasibility budget (PROJECT_BRIEF.md supplies none)
- administrative candidate blocked — the three-family comparison is incomplete

## Scope actually measured

- AOIs: 8 — hanoi_core, hcmc_core, thu_duc_east, dong_thap_rural, mu_cang_chai, binh_duong_industrial, hoi_an, phu_quoc_coast
- Candidates: 11 — h3_r10, h3_r9, h3_r8, h3_r7, square_125m, square_250m, square_325m, square_500m, square_850m, square_1000m, square_2270m
- Administrative family: **blocked** (enabled=False). See `docs/gate2_admin_qualification.md`.

## Gate 1 — completeness

- required candidate x AOI pairs: 88, present: 88
- raster processing-coverage floor 0.999: 0 source rows and 0 zonal rows below it
- vector ingest failures: 0
- **passed: True**

## Gate 3 — too coarse

A candidate is rejected in a context when at least 2 anchor features have a median within-unit sample range above 0.25 of their between-unit IQR.

**Candidates rejected in no context at all:** h3_r10, h3_r9, square_125m, square_250m, square_325m. A candidate must pass in every context, not on average -- passing on average would hide the contexts it fails in.

| candidate_id | binh_duong_industrial | dong_thap_rural | hanoi_core | hcmc_core | hoi_an | mu_cang_chai | phu_quoc_coast | thu_duc_east |
|---|---|---|---|---|---|---|---|---|
| h3_r10 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| h3_r7 | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 4 |
| h3_r8 | 4 | 3 | 4 | 4 | 4 | 2 | 2 | 4 |
| h3_r9 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| square_1000m | 4 | 3 | 4 | 4 | 4 | 1 | 0 | 3 |
| square_125m | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| square_2270m | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 4 |
| square_250m | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| square_325m | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| square_500m | 0 | 0 | 0 | 0 | 3 | 1 | 0 | 0 |
| square_850m | 4 | 3 | 3 | 2 | 3 | 1 | 0 | 2 |

## Gate 4 — too fine

| candidate_id | next_coarser | runtime_ratio | storage_ratio | mixing_improvement | loss_improvement | indistinguishable_neighbor_share | rejected | reason |
|---|---|---|---|---|---|---|---|---|
| h3_r10 | h3_r9 | 2.303 | 5.514 | 0.1242 | 0.6637 | 0.226 | False | not rejected |
| h3_r9 | h3_r8 | 1.387 | 4.668 | 0.1562 | 0.5529 | 0.03654 | False | not rejected |
| h3_r8 | h3_r7 | 1.141 | 2.379 | 0.1506 | 0.5736 | 0.002101 | False | not rejected |
| square_125m | square_250m | 2.113 | 3.309 | 0.08621 | 0.4668 | 0.219 | False | not rejected |
| square_250m | square_325m | 1.234 | 1.573 | 0.03335 | 0.3521 | 0.06863 | False | not rejected |
| square_325m | square_500m | 1.202 | 2.065 | 0.04704 | 0.1864 | 0.03658 | False | not rejected |
| square_500m | square_850m | 1.054 | 2.138 | 0.1258 | 0.4722 | 0.01294 | False | not rejected |
| square_850m | square_1000m | 1.117 | 1.212 | 0.05349 | 0.2014 | 0.002868 | False | not rejected |
| square_1000m | square_2270m | 1.119 | 1.814 | 0.07101 | 0.5593 | 0.0008333 | False | not rejected |

## Gate 5 — robustness

| candidate_id | median_rank | contexts_with_large_rank_movement | jitter_assignment_change_share | origin_shift_copartition_flip_share | origin_shift_applicable | passed |
|---|---|---|---|---|---|---|
| h3_r10 | 2 | 0 | 0.1167 |  | False | True |
| h3_r7 | 10.5 | 0 | 0.1166 |  | False | True |
| h3_r8 | 9 | 0 | 0.1137 |  | False | True |
| h3_r9 | 6 | 0 | 0.1187 |  | False | True |
| square_1000m | 8 | 0 | 0.1238 | 0.008301 | True | True |
| square_125m | 1 | 0 | 0.126 | 0.0001834 | True | True |
| square_2270m | 10.5 | 0 | 0.1188 | 0.03585 | True | True |
| square_250m | 3 | 0 | 0.1223 | 0.0006001 | True | True |
| square_325m | 4 | 0 | 0.1235 | 0.00105 | True | True |
| square_500m | 5 | 0 | 0.1207 | 0.002434 | True | True |
| square_850m | 7 | 0 | 0.1234 | 0.005967 | True | True |

## Gate 6 — feasibility

- budget provided by the owner: **False**
- `PROJECT_BRIEF.md` records no hardware, runtime, or storage budget, so this gate cannot be evaluated. Per `docs/spatial_unit_decision.md` acceptance rule 6, the Pareto frontier is reported instead of a single best candidate, and none is invented.

## Gate 7 — Pareto selection

Every objective below is oriented so **lower is better**. A candidate is non-dominated when no other candidate is at least as good on every objective and strictly better on one. H3 receives no convenience bonus: hexagonal candidates are scored by the same columns as square ones, and the origin-shift diagnostic H3 structurally cannot run is recorded as `not_applicable`, never as a pass.

| candidate_id | nationwide_storage_bytes | total_runtime_s | peak_rss_bytes | within_unit_loss_ratio | semantic_mixing_error | ring_1km_error | ring_3km_error | poi_zero_share | lookup_p95_latency_us | objectives_complete | pareto_nondominated | pareto_status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| h3_r10 | 2.892e+09 | 11.47 | 653557760 | 0.04933 | 0.07954 | 0.102 | 0.07374 | 0.94 | 0.6484 | True | True | nondominated |
| h3_r7 | 4.721e+07 | 3.148 | 678035456 | 0.7694 | 0.3845 | 0.7056 | 0.3248 | 0.2678 | 0.576 | True | True | nondominated |
| h3_r8 | 1.123e+08 | 3.591 | 637534208 | 0.3281 | 0.2918 | 0.4716 | 0.1051 | 0.5992 | 0.5855 | True | True | nondominated |
| h3_r9 | 5.245e+08 | 4.983 | 642187264 | 0.1467 | 0.1812 | 0.2604 | 0.09235 | 0.8274 | 0.6313 | True | True | nondominated |
| square_1000m | 9.349e+07 | 3.411 | 609927168 | 0.3238 | 0.3376 | 0.662 | 0.2051 | 0.568 | 0.5638 | True | True | nondominated |
| square_125m | 2.606e+09 | 12.59 | 681476096 | 0.03836 | 0.07671 | 0.1595 | 0.1595 | 0.9421 | 0.5919 | True | True | nondominated |
| square_2270m | 5.155e+07 | 3.048 | 617267200 | 0.7347 | 0.3815 | 0.7056 | 0.3991 | 0.2932 | 0.5666 | True | True | nondominated |
| square_250m | 7.875e+08 | 5.959 | 611205120 | 0.07194 | 0.15 | 0.1655 | 0.1655 | 0.8717 | 0.5634 | True | True | nondominated |
| square_325m | 5.005e+08 | 4.829 | 607780864 | 0.111 | 0.1774 | 0.2051 | 0.1595 | 0.8414 | 0.6102 | True | True | nondominated |
| square_500m | 2.424e+08 | 4.018 | 604028928 | 0.1365 | 0.2144 | 0.2669 | 0.1595 | 0.7487 | 0.6229 | True | True | nondominated |
| square_850m | 1.133e+08 | 3.812 | 604028928 | 0.2586 | 0.3022 | 0.5399 | 0.1821 | 0.6228 | 0.6131 | True | True | nondominated |

**Pareto-nondominated across all ten objectives:** h3_r10, h3_r7, h3_r8, h3_r9, square_1000m, square_125m, square_2270m, square_250m, square_325m, square_500m, square_850m

Ten objectives is enough dimensions that almost nothing dominates anything. That is a real property of this measurement, not a selection. The reduced frontier below uses only the three axes the acceptance rules actually turn on — projected nationwide storage, within-unit location loss, and semantic-mixing error — so the trade-off is legible. It is a different view of the same numbers, not a different result.

| candidate_id | nationwide_storage_bytes | within_unit_loss_ratio | semantic_mixing_error | objectives_complete | pareto_nondominated | pareto_status |
|---|---|---|---|---|---|---|
| h3_r10 | 2.892e+09 | 0.04933 | 0.07954 | True | False | dominated |
| h3_r9 | 5.245e+08 | 0.1467 | 0.1812 | True | False | dominated |
| h3_r7 | 4.721e+07 | 0.7694 | 0.3845 | True | True | nondominated |
| h3_r8 | 1.123e+08 | 0.3281 | 0.2918 | True | True | nondominated |
| square_1000m | 9.349e+07 | 0.3238 | 0.3376 | True | True | nondominated |
| square_125m | 2.606e+09 | 0.03836 | 0.07671 | True | True | nondominated |
| square_2270m | 5.155e+07 | 0.7347 | 0.3815 | True | True | nondominated |
| square_250m | 7.875e+08 | 0.07194 | 0.15 | True | True | nondominated |
| square_325m | 5.005e+08 | 0.111 | 0.1774 | True | True | nondominated |
| square_500m | 2.424e+08 | 0.1365 | 0.2144 | True | True | nondominated |
| square_850m | 1.133e+08 | 0.2586 | 0.3022 | True | True | nondominated |

**Core-objective Pareto-nondominated:** h3_r7, h3_r8, square_1000m, square_125m, square_2270m, square_250m, square_325m, square_500m, square_850m

**Undetermined (an objective could not be measured):** none

## What this does and does not settle

The frontier above is a measured trade-off surface across the square and H3 families only. It is not a selection. With the administrative family blocked and no feasibility budget recorded, naming one unit would be a preference presented as a result.
