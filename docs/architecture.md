# Architecture — Gate 1 Reviewed

_Preliminary logical architecture. Spatial method remains unresolved until Gate 2. No nationwide benchmark justifies distributed or cloud infrastructure._

## Logical stages

Raw Sources
→ Standardization
→ Spatial Representation
→ Atomic Feature Computation
→ Contextual Features
→ Derived Features
→ Optional Semantic Features
→ Final Location Feature Vector

The stages have separate contracts even when an MVP command executes several together.

### 1. Raw sources

Store immutable as-downloaded artifacts under data/raw or an equivalent content-addressed location. Prefer dated bulk PBF, GeoTIFF/COG, and GeoParquet. Do not use nationwide per-unit APIs.

For each artifact record provider, product/release, represented date, retrieval time, source URI, local path, SHA-256, byte count, license ID, CRS, bounds, and expected/present assets.

### 2. Standardization

Source-specific adapters create analysis-ready staging data:

- OSM: retain source IDs/tags/geometries, repair or quarantine invalid geometries, apply the versioned POI taxonomy, and conflate node/area duplicates into canonical entities.
- Overture: bbox-filter the pinned global release; retain source lineage and do not blindly union it with OSM.
- Population: retain population counts, NoData, grid definition, and valid coverage; use area-conserving aggregation.
- Land cover/built-up: retain original class/value meanings and valid-pixel masks. Do not relabel non-residential as industrial.
- Administration: reject a package that fails current unit-count, vintage, code, geometry, or license checks.

Standardized outputs are GeoParquet/Parquet for vector/table data and source-aligned GeoTIFF/COG for rasters. Record original/target CRS, row counts, geometry repairs/rejections, taxonomy version, and code/config version.

### 3. Spatial representation

Generate/administer the candidate or selected units and store:

- spatial method and method-specific resolution/size;
- H3 library major version, or square-grid origin/projection, or admin geometry vintage;
- actual geodesic area, land-support area, representative point, and neighbors;
- unit-geometry version/checksum.

Gate 2 compares admin, square, and H3 using [the experiment specification](spatial_unit_decision.md). Spatial method in config stays null until results support a choice.

### 4. Atomic features

Compute the raw counts, lengths, distances, and ratios in [the feature dictionary](feature_dictionary.md). All radii, search caps, category mappings, and sources come from versioned config. Store technical observation/coverage separately from the value so a missing source is not encoded as zero.

Output: data/processed/atomic plus feature-level QC.

### 5. Contextual features

Gate 4 only. Candidate transforms include log1p, national percentile, validated peer percentile, source-defined settlement class, and a geographically defined local ratio. Retain raw atomic inputs and transform/cohort versions. Do not compute contextual columns merely because their names exist in config.

### 6. Derived features

Formula-based combinations that remain task-generic may be considered only after atomic inputs pass validation. Each formula records dependencies and a version. Simple category richness is retained in the atomic MVP because it is an unweighted count; entropy/evenness is deferred.

### 7. Optional semantic features

Gate 5 only and disabled. Residential, commercial, education, tourism, and industrial scores require an explicit downstream decision, validation data, documented weights/formula, and sensitivity analysis. They never replace atomic columns.

### 8. Final vector

The final location feature vector is keyed by spatial_unit_id. Each row carries spatial method/resolution, representative coordinate, area, current admin matches when available, run ID, feature-set version, source-manifest ID, and computation timestamp.

Detailed provenance is normalized into manifest tables instead of repeating dozens of strings in each feature row:

| Manifest | Key | Content |
|---|---|---|
| source_manifest | source_manifest_id + source_id | Provider, product/release/date, URI/path, checksum/bytes, license, CRS/bounds, coverage |
| run_manifest | run_id | Code commit, config hashes, software/hardware versions, start/end, inputs, outputs |
| feature_manifest | feature_set_version + feature_name | Formula/version, unit, grain, spatial support, denominator, source dependencies, missing policy |
| spatial_manifest | spatial_version | Method, resolution, origin/CRS/library version, geometry checksum, neighbor rule |

Downstream mobility systems may join this output by coordinate/unit key. They may not feed customer/trip-derived aggregates back into the core vector.

## Reproducibility and validation

Tests are required for:

- CRS and coordinate-order conversion;
- deterministic point-to-unit assignment, including boundaries/coasts;
- square origin and H3 version handling;
- POI tag precedence, node/area conflation, and point/polygon treatment;
- population count conservation and raster partial-pixel aggregation;
- road clipping/topology/intersection rules;
- count, distance, ratio, denominator, and missing-versus-zero behavior;
- manifest completeness and repeat-run determinism.

Coverage reports include expected/present raster assets, valid-pixel fraction, vector ingest status, invalid/rejected records, taxonomy yield, unmatched/multi-match tags, and AOI category counts.

## Tooling

Use Python, GeoPandas, Shapely, DuckDB Spatial, PyArrow, Parquet/GeoParquet, and GeoTIFF/COG. H3 is an optional candidate dependency until Gate 2 selects it.

Spark, Sedona, PostGIS, Kafka, Kubernetes, and cloud orchestration are premature. Gate 6 may revisit tooling only from measured nationwide runtime, memory, and storage evidence.

## Blocking/open decisions

1. Primary user, downstream decision, business success metric, latency/refresh/scale budget, and external distribution model: project owner.
2. Referenced location-feature-engineering skill package: restore or formally retire, then re-check this review.
3. Current post-2025 commune geometry source and license: blocking only for the administrative Gate 2 candidate.
4. Spatial method/resolution: Gate 2.
5. Gate 3 production CRS strategy and road-graph parameters.
6. Gate 4 normalization/cohort definitions.
7. Gate 5 semantic score need and validation methodology.
