# Claude Cowork — Source Validation and MVP Acquisition Handoff

Handoff date: 2026-09-14

## Read first

Read these files before taking action:

1. `CLAUDE.md`
2. `PROJECT_BRIEF.md`
3. `docs/mvp_data_acquisition_plan.md`
4. `docs/data_sources.md`
5. `docs/feature_dictionary.md`
6. `config/data_sources.yaml`
7. `config/features.yaml`
8. `config/poi_taxonomy.yaml`
9. `config/spatial.yaml`

## Scope of this handoff

Do not repeat the full Gate 1 review. Do not modify `docs/architecture.md`, select a final spatial unit, build the nationwide pipeline, or create semantic area scores.

Your next task is narrowly scoped:

> Acquire reproducible prototype subsets and empirically validate the proposed POI, road, and population source roles for the Da Nang–Hoi An corridor.

No customer trips, customer IDs, pickup/drop-off activity, OD flows, or other behavioral data may be used.

## Working source decision

Treat the following as hypotheses to validate, not permission to merge every source.

### POI

- Candidate primary source for commercial POIs: Overture Places.
- Complement and QA source: OpenStreetMap from the same dated Geofabrik PBF used for roads.
- OSM remains necessary for mapped transit nodes, park/campus polygons, and `landuse=industrial` geometry.
- Use Overture `taxonomy` and `basic_category`; do not build new logic on the deprecated `categories` field.
- Preserve `confidence`, GERS `id`, and `sources` for audit. Overture states that confidence is not calibrated uniformly across providers, so do not invent a universal threshold before examining the AOI distribution.

### Roads

- Primary MVP road graph: OpenStreetMap from the dated Geofabrik Vietnam PBF.
- QA/fallback: Overture Transportation.
- Overture Transportation is primarily derived from OSM and is licensed under ODbL. It is not an independent road observation.
- Never union OSM and Overture road segments directly. Report overlap, incremental coverage, and topology differences; use one canonical graph in any feature run.

### Population

- Primary feature source: WorldPop Global 2 R2025A v1, 2025 constrained population count at approximately 100 m.
- Same-epoch validation pair: WorldPop 2020 versus GHS-POP R2023A epoch 2020.
- Optional projection sensitivity: GHS-POP 2025, clearly labelled as a projection.
- Do not average WorldPop and GHS-POP and do not describe either as ground truth.
- Compare aggregated values, not raw pixels. Their grids and disaggregation methods differ.
- They are not fully independent: WorldPop Global 2 uses GHSL built-settlement inputs, while GHS-POP uses GHSL built-up distribution and volume.

## Verified source facts

### OSM

- Snapshot: `vietnam-260913.osm.pbf`
- URL: `https://download.geofabrik.de/asia/vietnam-260913.osm.pbf`
- Verified size: 328,456,722 bytes
- Licence: ODbL 1.0

### Overture

- Current verified release at handoff: `2026-08-19.0`
- Schema: `v1.18.0`
- Places: `s3://overturemaps-us-west-2/release/2026-08-19.0/theme=places/type=place/*`
- Roads: `s3://overturemaps-us-west-2/release/2026-08-19.0/theme=transportation/type=segment/*`
- Overture only retains public data releases for a limited period. If this release has expired, resolve the latest release through the official STAC catalogue and pin the resolved release in the run manifest. Never leave the run on an implicit `latest` reference.

### WorldPop primary layer

- Product: Global 2 R2025A v1, Vietnam, 2025 constrained population count, 100 m
- URL: `https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2025/VNM/v1/100m/constrained/vnm_pop_2025_CN_100m_R2025A_v1.tif`
- Verified size: 75,215,955 bytes
- Format: GeoTIFF, WGS84, people per pixel
- This is a modelled estimate, not a census raster.

WorldPop's official census-input metadata says the Vietnam model uses the 2019 Census at admin level 2 with 712 units as its second timepoint and is flagged as modelled with the second timepoint only. Therefore, the 2025 raster is not evidence of post-2025 administrative population counts.

### WorldPop same-epoch comparison layer

- Product: same release, Vietnam, 2020 constrained population count, 100 m
- URL: `https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2020/VNM/v1/100m/constrained/vnm_pop_2020_CN_100m_R2025A_v1.tif`
- Verified size: 74,064,549 bytes

### GHSL same-epoch comparison layer

- Product: GHS-POP R2023A, epoch 2020, 100 m, World Mollweide
- Prototype tile: `GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0_R8_C29.zip`
- URL: `https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/GHS_POP_E2020_GLOBE_R2023A_54009_100/V1-0/tiles/GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0_R8_C29.zip`
- Verified size: 39,426,582 bytes
- Licence: CC BY 4.0
- GHS-POP values for 1975–2020 are estimates; 2025 and 2030 are projections.

### Licence caution

- Overture Places uses CDLA Permissive 2.0 or Apache 2.0 by provider. Retain per-record source metadata needed for attribution.
- OSM and Overture Transportation carry ODbL obligations.
- The WorldPop catalogue displays CC BY 4.0 but also states that products derived from OSM or Microsoft data may be ODbL. Archive the exact product terms and mark external redistribution as pending until applicability is confirmed.
- Internal prototype analysis may proceed, but do not publish or redistribute a derived database without resolving these obligations.

## Prototype extent

Use these exact WGS84 extents:

- Evaluation AOI: `(108.10, 15.75, 108.35, 16.15)`
- Acquisition AOI: `(108.07, 15.72, 108.38, 16.18)`

The acquisition AOI includes an approximately 3 km halo. Use EPSG:32649 for metric distance and length calculations.

Do not expand to a nationwide run. After this corridor is complete, recommend—but do not automatically execute—a separate rural or mountain coverage check.

## Work to perform

### 1. Preflight

- Inspect the current repository and preserve all existing user changes.
- Confirm available disk space and required command-line/library dependencies.
- Prefer the existing Python, GeoPandas, Shapely, DuckDB, PyArrow, GeoParquet, GDAL, and Osmium stack.
- Do not introduce Spark, Sedona, PostGIS, Kafka, or cloud infrastructure.
- Before a large download, report its expected size and request any permission required by the environment.

### 2. Reproducible acquisition

Implement the smallest maintainable acquisition entry points needed for this prototype. They must:

- download pinned assets without overwriting a valid existing file;
- record retrieval UTC, exact URL, release, represented date, byte count, SHA-256, licence, CRS, bounds, and local path;
- verify HTTP and local byte counts;
- preserve provider assets unchanged under `data/raw`;
- write AOI subsets separately;
- fail loudly on partial downloads, schema drift, unexpected CRS/NoData, or changed source content;
- avoid embedding machine-specific absolute paths.

Use bbox/filter pushdown for Overture so only the acquisition AOI is transferred. Output Overture subsets as GeoParquet and retain the nested source/taxonomy fields needed for audit.

### 3. POI audit

Map both Overture and OSM records to the canonical feature groups in `config/poi_taxonomy.yaml`, while retaining the original source category and tags.

Report at minimum:

- record count by canonical group and source;
- Overture count by contributing provider and confidence band;
- missing-name and missing-category rates;
- possible duplicate rate using normalized name/category and a documented distance tolerance;
- Overture-to-OSM matched, Overture-only, and OSM-only counts;
- spatial density maps or summary grids sufficient to identify urban-core bias and empty areas;
- a reproducible review sample for schools, hospitals/clinics, pharmacies, food/drink, retail, lodging, attractions, parks, transit, and industrial locations.

Do not silently discard low-confidence records. Present sensitivity results for at least two documented confidence policies and recommend a policy by canonical group.

### 4. Road audit

Build comparable road subsets but do not combine them into one graph.

Report at minimum:

- total length by comparable road class;
- drivable-network connected components and largest-component share;
- intersection/connector counts under each source's topology;
- geometry overlap or matched-length estimate;
- incremental Overture-only and OSM-only length;
- missing or disconnected major-road segments found by visual/sample inspection;
- expected impact on `road_length`, `road_density`, `intersection_density`, and nearest-major-road features.

End with one explicit recommendation: retain OSM as canonical, or replace it with Overture for a stated measurable reason. Do not recommend a direct union.

### 5. Population audit

Acquire and clip WorldPop 2025, WorldPop 2020, and GHS-POP 2020. Preserve the native grids before any comparison.

For the 2020 comparison:

- aggregate both products onto a common 1 km equal-area comparison grid;
- compare total population, non-zero coverage, quantiles, rank correlation, absolute difference, and relative difference with a safe policy for near-zero denominators;
- examine coastal/water cells, dense urban cells, peri-urban development, and sparse areas separately;
- distinguish disagreement in total controls from disagreement in spatial allocation;
- document resampling and conservation checks so population counts are not accidentally averaged.

Use WorldPop 2025 for the proposed current MVP feature only after the 2020 spatial-allocation audit is documented. State clearly that 2025 remains modelled and that neither raster represents daytime population or mobility.

## Required deliverables

Produce:

1. Reproducible acquisition code and focused tests.
2. An immutable source manifest for the prototype run.
3. AOI source subsets in appropriate geospatial formats.
4. `docs/source_validation_report.md` containing:
   - exact releases and retrieval facts;
   - POI, road, and population audit results;
   - plots/tables or reproducible summaries;
   - licence and lineage warnings;
   - failures and unresolved issues;
   - a final GO / CONDITIONAL GO / NO-GO decision for each source role.

Do not modify `docs/architecture.md` during this task. If the evidence implies an architecture change, record it as a recommendation in the validation report only.

## Completion criteria

The handoff is complete only when:

- all executed downloads and transformations are reproducible from code;
- the manifest contains checksums and exact pinned versions;
- tests cover bbox handling, source-schema assumptions, taxonomy mapping, count conservation, and duplicate/missing-data behavior relevant to this task;
- all metrics are based on actual AOI data rather than provider marketing claims;
- every zero is distinguishable from missing/unavailable data;
- source lineage prevents false claims of independent validation;
- the report makes an explicit source-role recommendation and lists the next smallest validation step;
- architecture, semantic scoring, customer-mobility logic, and nationwide processing remain untouched.

At the end, summarize what was downloaded, what was measured, which source roles passed, what remains uncertain, and the exact commands needed to reproduce the run.
