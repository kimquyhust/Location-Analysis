# Spatial Unit Decision — Gate 2 Experiment Specification

_Status: decision open. `config/spatial.yaml` remains `method: null` until this experiment is complete. The full independent rationale is in [`gate1_technical_review.md`](gate1_technical_review.md)._

## Decision boundary

Gate 2 compares current administrative units, square grids, and H3. H3 is not assumed to be best. Administrative geometry may participate only if a licensed post-1-July-2025 nationwide commune/ward/special-zone package passes the qualification checks below. Stale districts are not a substitute.

The storage/index unit and feature support are different concepts. A feature may use the unit footprint, a 1 km buffer, or a 3 km buffer regardless of the key type. Every result must name both.

## Candidates

| Family | Variants | Purpose |
|---|---|---|
| Administrative | Current 3,321 commune-level units, conditional | Interpretability, administrative alignment, and area-variability baseline. |
| Square, operational | 250 m, 500 m, 1,000 m | Common engineering sizes. |
| Square, area controls | 125 m, 325 m, 850 m, 2,270 m | Approximate mean-area controls for H3 r10, r9, r8, and r7 to separate shape from scale. |
| H3 v4 | resolutions 7, 8, 9, 10 | r7/r10 are coarse/fine sentinels; r8/r9 are plausible, not preselected. |

H3 v4 average areas for r7–r10 are approximately 5.1613, 0.7373, 0.1053, and 0.01505 km²; average edge lengths are 1.4065, 0.5314, 0.2008, and 0.07586 km. Actual per-cell areas must be computed and reported. Source: [H3 v4 cell statistics](https://h3geo.org/docs/core-library/restable/).

Square grids use a documented, stable national origin. Metric construction/measurement uses a locally suitable projection per AOI; storage geometry remains EPSG:4326. Origin-shift replicates are part of the sensitivity test.

## Administrative-source qualification

Before the admin candidate is enabled, record:

- provider and authoritative lineage;
- effective/source date on or after 1 July 2025;
- expected 3,321 unit count and official unit codes;
- commercial reuse/redistribution terms;
- bulk access URI, format, byte count, and checksum;
- geometry validity, gaps/overlaps, CRS, and coastal/island treatment.

The current geoBoundaries API is not eligible: it reports Vietnam ADM1 as 2008 and ADM2 as 2020. If no source passes, record the candidate as `blocked` and do not claim a completed three-family comparison.

## Test geography

Use the coordinate-centered AOIs in `config/spatial.yaml`; persist exact GeoJSON and checksums. They cover replicated dense urban and tourism contexts plus suburban, rural delta, rural mountain, and industrial settings. Every enabled candidate uses every AOI and identical clipped source snapshots.

## Metrics

1. **Unit count:** full, land-intersecting, and nationwide projected units.
2. **Unit area:** actual area min/p05/median/mean/p95/max, coefficient of variation, and effective land area.
3. **POI sparsity:** mapped-zero proportion by leaf category and total, for footprint and 1 km buffer; source status is separate.
4. **Population sparsity:** zero-count share and p10/median population per unit.
5. **Road sparsity:** zero road-length share and zero-intersection share.
6. **Semantic mixing:** land-cover entropy, dominant-class share, and within-unit built-up variance.
7. **Within-unit location loss:** compute anchor features at centroid plus stratified interior points; compare within-unit range with between-unit IQR.
8. **Neighborhood representation:** neighbor-degree distribution and the area/Jaccard error of grid-ring approximations to 1 km and 3 km circles.
9. **Boundary sensitivity:** square-origin shifts, point jitter, assignment changes, and feature rank stability.
10. **MAUP stability:** adjacent-resolution Spearman rank, median absolute percent change, and top-decile membership stability.
11. **Computation:** wall time and peak RSS by generation, point assignment, road clipping, raster zonal stats, POI buffer aggregation, and neighbor construction.
12. **Storage:** Parquet geometry/features bytes, bytes per unit, and nationwide projections.
13. **Lookup:** correctness on boundary/coastal cases and p50/p95 single/batch latency for 10,000 lat/lon queries; admin reverse lookup is timed separately.

## Required outputs

- `candidate_inventory.parquet`
- `candidate_metrics.parquet`
- `benchmark_runs.parquet`
- `lookup_benchmark.parquet`
- `source_coverage.parquet`
- `decision_matrix.md`
- Faceted maps for unit boundaries, sparsity, semantic mixing, within-unit loss, and grid-origin sensitivity
- Plots for sparsity/mixing/representation error vs area and unit count vs storage/runtime

Each benchmark row includes AOI, candidate, source release, config hash, code commit, hardware/software versions, row counts, wall time, peak RSS, and bytes.

## Acceptance rules

1. **Completeness:** all required candidate × AOI metrics exist. Raster processing coverage is at least 99.9% of expected valid pixels and vector ingest has no technical failures. Mapped absence remains a zero with a source caveat.
2. **Current admin:** the administrative candidate runs only after all qualification checks pass.
3. **Too coarse:** reject a candidate in a context when at least two anchor features have a median within-unit sample-point range greater than 25% of their between-unit IQR. Also flag a candidate whose dominant land-cover share degrades against both adjacent finer scales without material feasibility benefit.
4. **Too fine:** reject a finer candidate if it costs over 2× the next coarser candidate while improving both semantic-mixing and location-loss errors by less than 5%, or when more than 80% of neighbor pairs have indistinguishable anchor vectors within declared tolerance.
5. **Robustness:** a selected candidate may not reverse rank in more than one context under origin shifts, point jitter, or alternate population/built-up source sensitivity.
6. **Feasibility:** evaluate against a hardware/runtime/storage budget recorded before execution. If the owner provides no budget, report the Pareto frontier rather than inventing one best option.
7. **Selection:** choose only among candidates that pass hard gates and are Pareto-nondominated. Ties go to lower nationwide storage/runtime, then simpler deterministic lat/lon lookup. H3 receives no convenience bonus.

## Gate 2 completion

Gate 2 ends with measured results, a documented selected unit (or an explicit no-decision), a source/parameter sensitivity analysis, and an evidence-backed update to `config/spatial.yaml`. It does not end when candidate geometries have merely been generated.
