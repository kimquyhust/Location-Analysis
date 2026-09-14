# Gate 1 Technical Review

_Independent review completed against the repository state and provider documentation available at review time. This is the controlling Gate 1 review artifact; unresolved business requirements remain subject to project-owner confirmation._

## A. Gate 1 verdict

**PASS WITH REQUIRED FIXES**

The work has a sound scope boundary, does not use customer mobility inputs, keeps H3 undecided, and avoids premature distributed infrastructure. It is not ready to execute Gate 2 from the original configs, however. The original data-source audit contains material currency/resolution errors, the administrative candidate is not backed by verified post-2025 commune geometry, the spatial experiment omits several required metrics and decision rules, the feature MVP treats source non-observation as a true zero, and the POI taxonomy is a list of labels rather than reproducible source mappings.

The technical fixes in this review and the accompanying config/doc updates make Gate 2 methodologically executable. Two owner-controlled items remain: complete `PROJECT_BRIEF.md`, and restore or formally retire the referenced but absent `.claude/skills/location-feature-engineering/` package.

## Review limitations

- `PROJECT_BRIEF.md` contains headings only, so the real primary user, decision cadence, latency, hardware budget, and commercial distribution model cannot be validated.
- The requested project skill and all of its references are absent. The review therefore used `CLAUDE.md`, the repository artifacts, and primary provider documentation.
- “Global coverage” means that a provider advertises a global product; it does not prove complete or accurate Vietnam records. Gate 2 must measure Vietnam/AOI record coverage.
- License observations are engineering screening, not legal advice. ODbL publication obligations require counsel/product-owner review before external distribution.

## B. Critical issues

1. **The current administrative-unit candidate is not reproducible.** Vietnam has operated 34 provincial units and no district-level administrations since 1 July 2025. The geoBoundaries API currently reports Vietnam ADM1 as 2008 (64 units) and ADM2 as 2020 (708 districts), so it is structurally stale. A post-reform commune/ward geometry source with usable commercial terms has not been verified.
2. **The source audit conflates products and resolutions.** The cited WorldPop page is a 2020, 1 km density raster; current WorldPop Global 2 supplies Vietnam population _counts_ at approximately 100 m. GHS-BUILT-S R2023A is distributed as generalized 100 m/1 km grids; the 10 m product is the separate 2018 GHS-BUILT-S E2018 product. These differences change feature calculations.
3. **The H3 edge lengths are from H3 v3, while the project declares H3 v4.** Areas are essentially unchanged, but v4’s documented average edges for resolutions 7–10 are about 1.406, 0.531, 0.201, and 0.0759 km. Version-specific metrics must be stored.
4. **Zero and missing/non-observed are conflated.** An empty, successfully read source slice may yield zero; a failed download, missing tile, unmapped OSM entity, or unmapped tag cannot. Technical coverage flags and observation status are required. OSM zero still means “zero mapped records,” never proven real-world absence.
5. **Several features are not computable as defined.** WorldCover has no industrial class; GHSL non-residential built-up is not equivalent to industrial land. Polygon POIs cannot generally be reduced to centroids, which may lie outside the polygon. `poi_diversity` and custom `urban_rural_class` have no final formula.
6. **The POI taxonomy is not an extraction specification.** Terms such as `shop`, `landmark`, `factory`, `sports`, and `logistics` do not identify source keys/values, and overlapping rollups allow double-counting.
7. **The Gate 2 design cannot yet make an objective choice.** It lacks population and road sparsity, area variation, neighborhood-representation error, lookup latency, explicit storage outputs, matched-area shape comparisons, and pre-registered decision rules.
8. **The problem definition is technically coherent but not product-grounded.** The user and actual pain points are inferred, and “commodity tooling” and “~25–40 features” are deliverable constraints rather than evidence that a user problem is solved.

## C. Required fixes before Gate 2

### MUST FIX

- Obtain and record a licensed post-1-July-2025 commune/ward geometry source, including provider, source date, unit count, checksum, CRS, access terms, and authoritative code mapping. If this cannot be done, mark the administrative candidate `blocked` and do not claim a complete three-way comparison.
- Pin exact source products/releases rather than provider families: WorldPop Global 2 population count, a specific GHSL product/resolution/epoch, a specific land-cover release, a dated OSM PBF, and a dated boundary package.
- Use the revised Gate 2 candidate matrix, metrics, output contract, and acceptance rules in this artifact and `docs/spatial_unit_decision.md`.
- Run the source-observation model: source/tile presence and ingest success are separate from a measured zero; publish coverage indicators with the feature layer.
- Use reproducible POI tag rules and entity deduplication; use `point_on_surface` only for count representation and the original polygon geometry for distance/area calculations.
- Keep semantic scores disabled. Do not implement custom `urban_rural_class`, `poi_diversity`, peer percentiles, or local ratios during Gate 2.

### SHOULD FIX

- Have the project owner complete the user, decisions, latency/scale constraints, distribution model, and testable success criteria in `PROJECT_BRIEF.md` before committing the Gate 3 MVP.
- Run Overture Places/Buildings/Transportation as an independent or partially independent AOI audit, not as an automatic union with OSM. Record overlap, unique entities, and category precision before adoption.
- Pre-register the Gate 2 hardware profile and runtime/storage budgets. The relative acceptance rules below remain valid without an arbitrary laptop specification.
- Decide how ODbL-derived columns will be isolated, attributed, and distributed before external product delivery.

### NICE TO HAVE

- Add two repeated AOIs per context to reduce city-specific conclusions.
- Add boundary jitter/origin-shift replicates for square grids and H3 class-II/class-III adjacency diagnostics.
- Preserve old administrative codes in a crosswalk for historical joins, without using stale geometries as the current spatial key.

## 1. Scope-consistency review

All five Gate 1 documents and four configs respect the hard boundary. Core inputs are POI, population, roads/transport, land/built environment, administrative context, and accessibility. Customer IDs, trip IDs, pickup/dropoff counts, OD flows, customer behavior, and segmentation occur only in explanations of excluded or downstream work. No leakage was found.

One wording refinement is important: a downstream mobility model may join to the location vector, but no aggregate learned from that downstream data may be promoted back into the core layer under a neutral name such as “activity,” “centrality,” or “importance.”

## 2. Problem-framing review

| Test | Finding | Disposition |
|---|---|---|
| Problem clearly defined | The technical object—a reusable, supply-side location vector—is clear. The decision problem it serves is not. | Required owner input |
| User identified | “Many downstream products” is not a user. Data scientists, analysts, planners, and online lookup services have different needs. | Required owner input |
| Pain points are real product/data problems | Leakage and absence of features in unserved areas are credible. Update pain, inconsistent geographic joins, reproducibility, and coverage are asserted rather than evidenced. | Validate with users |
| Insight follows pain points | Separating place attributes from demand signals follows logically from leakage/reuse concerns. | Supported |
| Direction follows insight | Build an upstream, versioned geographic layer and let downstream systems join to it. | Supported |
| Does not presume H3 | Spatial method remains `null`; comparison is explicit. | Supported |
| MVP measurable | Feature count is measurable; utility is not. | Modify |
| Success testable | Original criteria test conformance, not usefulness. | Modify |

### Working user hypothesis—not an approved requirement

The likely primary user is a data scientist or geospatial analyst who needs a reproducible feature row for an arbitrary Vietnam latitude/longitude and a stable table for batch joins. This hypothesis must be accepted or replaced by the owner.

### Testable technical success for Gate 2/3

- A lat/lon inside the supported Vietnam land mask maps deterministically to exactly one current spatial-unit key; boundary cases have a documented tie rule.
- Re-running against pinned source artifacts and config/feature versions yields identical feature values within declared floating-point tolerance.
- Every output row carries spatial method/resolution, geometry version, feature-set version, source manifest ID, and computation timestamp.
- For every source family, technical non-coverage/failure is distinguishable from a successful zero observation.
- All MVP feature definitions have explicit units, spatial supports, geometry treatment, denominators, and missing policies.
- The Gate 2 choice passes the coarse/fine and feasibility rules below across every representative context.

Business success—adoption, lift in downstream tasks, SLA, refresh cadence, or commercial distribution—cannot be specified until the owner supplies requirements. Customer data may be used later to evaluate a downstream consumer, but never to construct the core features.

## 3. Data-source audit

### Provider-level findings

| Dataset | Verified facts | Vietnam coverage and scale | License/commercial use | Access/format/update | Review decision |
|---|---|---|---|---|---|
| OpenStreetMap via Geofabrik | The Vietnam extract is a complete, unfiltered OSM PBF; Geofabrik rebuilds extracts daily. The reviewed page listed roughly 313 MB PBF. | Country extract exists; presence is nationwide, completeness is not. POI/building/transit mapping bias must be measured. | ODbL 1.0 permits commercial use with attribution and share-alike conditions for publicly used derivative databases. | Bulk HTTPS; PBF preferred. Shapefile/GPKG exports are filtered. Daily plus diffs. | **Preferred POI/roads/transit-node prototype source.** |
| BBBike OSM exports | More than 200 predefined city/region extracts, custom AOIs, and several formats; country/region outputs may update daily/weekly. Custom service documents size limits. | Useful for AOI convenience, not an independent Vietnam source; same OSM lineage. | ODbL. | PBF, GeoJSON, GeoParquet, GPKG, SHP and others. | Not a nationwide fallback; use only for reproducibility checks/AOI convenience. |
| Overture Places | Provider advertises global places, monthly releases, point representations, and permissive per-source licensing; Places contains no OSM data. | Vietnam records are expected under global coverage but counts/category precision were not measured in Gate 1. | CDLA-Permissive 2.0 / Apache 2.0 by source. | Global GeoParquet on S3/Azure; DuckDB/CLI subset by bbox; monthly. | **Independent POI fallback/QA**, conditional on AOI audit. |
| Overture Transportation | Global segments/connectors, primarily OSM and enhanced by TomTom/other sources. | Global product includes Vietnam in scope; incremental Vietnam benefit over OSM is unmeasured. | ODbL. | GeoParquet, cloud bulk/bbox access, monthly. | **Road fallback/QA**, not independent of OSM. |
| Overture Buildings | Global conflation of OSM, ML, and other sources; provider warns ML precision issues are most pronounced in the Global South. | Vietnam in global scope; local completeness/precision unmeasured. | ODbL. | GeoParquet, cloud access, monthly. | Building-count fallback only after AOI validation; not required for atomic MVP. |
| WorldPop Global 2 R2025A v1 | Vietnam constrained population **counts** at about 100 m; annual years 2015–2030; reviewed Vietnam total-count file about 72 MB. Product is modeled/dasymetric and its page labels this release alpha. | Explicit Vietnam download. Nationwide scalable as one GeoTIFF. | Vietnam catalog page states CC BY 4.0 and commercial reuse with attribution. | GeoTIFF, catalog/direct file, STAC/API. Use bulk GeoTIFF, not per-unit API calls. | **Preferred population source.** Pin year/release and aggregate counts before deriving density. |
| GHSL GHS-POP R2023A | Global population count/density, 1975–2030 in five-year steps; 100 m/1 km (or 3/30 arc-second) outputs. | Global, including Vietnam. | European Commission reuse authorized with acknowledgment. | Tiled/global GeoTIFF via download wizard. | **Population fallback/QA.** |
| GHSL GHS-BUILT-S R2023A | Multitemporal built-up surface and residential/non-residential component at generalized 100 m and 1 km. The separate GHS-BUILT-S E2018 product is 10 m. | Global, including Vietnam. | Open/free; acknowledgment required. | GeoTIFF download wizard, versioned releases. | **Preferred built-up source:** 100 m R2023A for time-aligned MVP; optionally test E2018 10 m. Do not call NRES “industrial.” |
| ESA WorldCover 2021 v200 | Global 10 m, 11 classes, COG, WGS84. 2020 and 2021 maps use different algorithms, so map-to-map change is not pure land-cover change. | Global, including Vietnam. Vietnam intersects multiple tiles; measure exact bytes at pull. | CC BY 4.0, commercial use allowed with attribution. | Bulk COG via AWS/downloader/Zenodo; static 2021 release. | **Preferred prototype land-cover source** because it is stable and documented. |
| Copernicus LCFM LCM 2020 v1 | Operational successor line; currently available global 10 m 2020 baseline, with later annual products planned/rolling out. | Global, including Vietnam. | Product metadata states CC BY 4.0. | COG/GeoTIFF through CDSE S3/OData/browser; use bulk S3/manifest. | **Land-cover fallback/future primary** after release maturity and local comparison. |
| OCHA COD-AB 2025 | A 2025 ADM1 package with 34 provinces is reported in downstream catalogs, but its package metadata/commune geometry and terms were not fully machine-verifiable in this audit. | ADM1 appears available. A nationwide post-reform 3,321-commune polygon package is not confirmed. | Must be checked in the downloaded package; do not infer from other CODs. | Prefer bulk SHP/GeoJSON package over feature-service calls. | Candidate for current province metadata only after package verification. |
| geoBoundaries current API | API reports Vietnam ADM1 year 2008 with 64 units and ADM2 year 2020 with 708 districts. | Nationwide but stale relative to the 2025 system; no current commune layer in the API result. | API reports Public Domain for its ADM1 record and CC BY 3.0 IGO for ADM2 lineage. | Static ZIP/GeoJSON API links. | **Reject for current administrative geometry.** May be historical QA only. |
| GADM 4.1 | Nationwide administrative geometry. | Stale relative to reform unless proven otherwise. | Official license forbids redistribution/commercial use without prior permission. | GPKG/SHP downloads. | Reject for commercial MVP unless written permission is obtained. |
| Hanoi/TUMI bus dataset | A city-specific feed/listing was cited, but current update frequency and commercial terms were not verified. | Hanoi only; no nationwide GTFS coverage was established. | Unverified. | Dataset download/GTFS claim requires package inspection. | Defer; never use as the nationwide transit source. |

Primary evidence: [Geofabrik Vietnam and file metadata](https://download.geofabrik.de/asia/vietnam.html), [Geofabrik extract process](https://download.geofabrik.de/technical.html), [OSM license](https://www.openstreetmap.org/copyright), [BBBike exports](https://download.bbbike.org/osm/), [Overture access](https://docs.overturemaps.org/getting-data/cloud-sources/), [Overture Places](https://docs.overturemaps.org/guides/places/), [Overture Transportation](https://docs.overturemaps.org/guides/transportation/), [Overture Buildings](https://docs.overturemaps.org/guides/buildings/), [WorldPop Vietnam Global 2 count](https://hub.worldpop.org/geodata/summary?id=75408), [GHSL catalog](https://human-settlement.emergency.copernicus.eu/datasets.php), [ESA WorldCover access/license](https://esa-worldcover.org/en/data-access), [Copernicus LCFM 10 m product](https://land.copernicus.eu/en/products/global-dynamic-land-cover/land-cover-2020-raster-10-m-global-annual), [geoBoundaries Vietnam API](https://www.geoboundaries.org/api/current/gbOpen/VNM/ALL/), and [GADM license](https://gadm.org/license.html).

Vietnam’s 34-province/two-tier system is confirmed by the [Government of Vietnam information channel](https://en.baochinhphu.vn/historic-milestone-in-modern-viet-nam-111250701123506887.htm). The government also describes an official map of 34 provinces and 3,321 commune-level units, while noting continued local boundary correction; a web map is not automatically a licensed bulk dataset ([official notice](https://baochinhphu.vn/tra-cuu-dia-gioi-sau-sap-nhap-qua-ban-do-dien-tu-102250708175104468.htm)).

### Preferred and fallback by category

| Category | Preferred MVP source | Fallback | Reason |
|---|---|---|---|
| POI | Dated Geofabrik Vietnam OSM PBF | Overture Places | OSM is tag-rich and easy to reproduce; Overture is a useful independent, permissively licensed QA/fallback once Vietnam category precision is measured. |
| Roads | Same dated Geofabrik PBF | Overture Transportation | One bulk source avoids duplicate pipelines. Overture is normalized but largely shares OSM lineage, so it is fallback/QA rather than independent truth. |
| Population | WorldPop Global 2 R2025A v1, selected year, 100 m constrained count | GHS-POP R2023A 100 m | Both are nationwide modeled products; WorldPop has a current Vietnam package, while GHSL provides a consistent independent implementation for sensitivity checks. |
| Land cover | ESA WorldCover 2021 v200 | Copernicus LCFM LCM 2020 v1 | WorldCover is stable, well documented, and one year newer; LCFM is the operational successor but currently provides an older baseline. Neither is land-use zoning. |
| Built-up | GHS-BUILT-S R2023A 100 m, chosen epoch | GHS-BUILT-S E2018 10 m or Overture Buildings for QA | R2023A supports multitemporal consistency. The 10 m snapshot checks local detail; building footprints answer a different question. |
| Administrative context | Verified OCHA 2025 ADM1 package plus official NSO codes | Overture Divisions after vintage/unit-count check | Province metadata is feasible; current commune geometry remains a blocking acquisition. geoBoundaries/GADM are not acceptable current defaults. |
| Administrative spatial-unit candidate | **No qualified source yet** | Overture/OSM only if all 3,321 current units, codes, geometry, vintage, and terms pass validation | It is better to declare a blocked candidate than compare stale districts to grids. |
| Transit nodes | OSM tags in the Geofabrik PBF | Overture Places/Transportation after AOI audit | Nationwide schedules/GTFS were not established. Node proximity can be MVP with explicit mapped-data caveats; service frequency cannot. |

Avoid Overpass and per-polygon population APIs for production extraction. Use bulk PBF/GeoTIFF/GeoParquet and clip once. Do not union OSM, HOTOSM, and Overture blindly: HOTOSM is OSM lineage, while Overture themes have mixed lineage and require entity conflation.

## 4. Spatial-unit methodology review and Gate 2 specification

### Candidate matrix

| Family | Variants | Role |
|---|---|---|
| Current administrative | Post-2025 commune/ward/special-zone polygons only, conditional on source qualification | Tests interpretability and administrative alignment; expected high area variability. |
| Square grid | 250 m, 500 m, 1,000 m | Operationally common sizes. Use a locally appropriate metric CRS per AOI and a documented national grid origin. |
| Square matched-area controls | 125 m, 325 m, 850 m, 2,270 m | Approximately match H3 r10, r9, r8, and r7 mean areas, isolating grid shape from scale. |
| H3 v4 | resolutions 7, 8, 9, 10 | r7/r10 are coarse/fine sentinels; r8/r9 are likely practical candidates, not presumed winners. |

H3 v4 documents average areas of 5.1613, 0.7373, 0.1053, and 0.01505 km² and average edge lengths of 1.4065, 0.5314, 0.2008, and 0.07586 km for r7–r10. Actual cell areas must be computed, because H3 area varies spatially. See the [H3 v4 statistics table](https://h3geo.org/docs/core-library/restable/).

### Representative AOIs

Use fixed coordinate-centered windows so administrative name changes do not move the sample. Preserve the exact GeoJSON and checksum in the run manifest.

| Context | AOI | Minimum window | Purpose |
|---|---|---:|---|
| Dense urban | Hoàn Kiếm core (about 21.028°N, 105.852°E) | 6 × 6 km | Fine block structure and dense POIs. |
| Dense urban replicate | Central HCMC (about 10.776°N, 106.700°E) | 6 × 6 km | Different urban morphology and source-mapping regime. |
| Suburban/peri-urban | Eastern Thủ Đức (about 10.85°N, 106.78°E) | 12 × 12 km | Rapid density gradient and mixed development. |
| Rural delta | Đồng Tháp/Cao Lãnh hinterland (about 10.46°N, 105.64°E) | 15 × 15 km | Linear settlement, waterways, agriculture. |
| Rural mountain | Mù Cang Chải area (about 21.77°N, 104.13°E) | 15 × 15 km | Sparse roads/POIs and difficult terrain. |
| Industrial | Bình Dương industrial corridor (about 11.13°N, 106.62°E) | 12 × 12 km | Large industrial polygons and worker settlements. |
| Tourism | Hội An coast/core (about 15.88°N, 108.33°E) | 12 × 12 km | Attractions/lodging plus coastline edge effects. |
| Tourism replicate | Phú Quốc settled coast (about 10.22°N, 103.96°E) | 12 × 12 km | Island/coastal topology and dispersed tourism. |

### Metrics

Compute for every candidate × AOI, with identical clipped source snapshots:

1. Unit count: full cells, land-intersecting cells, and projected nationwide land-intersecting cells.
2. Unit area: mean, median, p05, p95, min, max, coefficient of variation, and effective land area.
3. POI sparsity: zero-mapped proportion per leaf category and total, both footprint-based and 1 km buffer-based; report source-observation flags separately.
4. Population sparsity: zero-count proportion and p10/median population per unit.
5. Road sparsity: zero road-length proportion and intersection zero rate.
6. Semantic mixing: land-cover entropy, dominant-class share, and within-unit variance of built-up fraction; report by context.
7. Within-unit location loss: calculate anchor features at centroid plus four/five stratified interior points; compare within-unit range with the between-unit IQR. This directly exposes units that make materially different coordinates look identical.
8. Neighborhood representation: adjacency-degree distribution; area/CV of one-ring neighborhoods; Jaccard overlap and area error when grid/H3 rings approximate 1 km and 3 km circles.
9. Boundary/origin sensitivity: repeat square grids at four half-cell offsets and jitter test points by 10% of cell width; report assignment and rank stability.
10. MAUP stability: Spearman rank, median absolute percent change, and top-decile membership stability between adjacent resolutions.
11. Computation: wall time and peak RSS for generation, point assignment, line clipping, raster zonal stats, 1 km POI aggregation, and neighbor construction.
12. Storage: geometry and feature Parquet bytes, bytes/unit, and projected nationwide bytes.
13. Lookup simplicity/performance: correctness at boundaries/coasts and p50/p95 latency for 10,000 single and batch lat/lon lookups, including admin reverse lookup as a separate step.

### Required outputs

- `candidate_inventory.parquet`: candidate, AOI, unit ID, area, land fraction, neighbor count.
- `candidate_metrics.parquet`: one tidy row per candidate × AOI × metric × feature/category.
- `benchmark_runs.parquet`: hardware/software versions, stage, rows, wall time, peak RSS, bytes.
- `lookup_benchmark.parquet`: candidate, lookup mode, latency quantiles, errors/tie cases.
- `source_coverage.parquet`: source, release, AOI, expected tiles, present tiles, valid pixels/features, ingest status.
- `decision_matrix.md`: hard-gate result, normalized diagnostic values, Pareto status, selected candidate, sensitivity notes.
- Maps: identical-extent faceted unit boundaries; POI/population/road sparsity; land-cover mixing; within-unit sample-point range; boundary-offset sensitivity.
- Plots: unit count vs storage/time; sparsity vs area; mixing vs area; neighborhood approximation error vs area; adjacent-resolution stability.

### Acceptance criteria

These are selection rules, not invented claims that one resolution is universally correct:

1. **Completeness gate:** all required AOIs, candidates, sources, metrics, and manifests complete. Raster processing coverage must be at least 99.9% of expected valid pixels; vector ingest failures must be zero. Mapped-data absence remains a zero plus source caveat, not a coverage failure.
2. **Administrative gate:** the admin candidate participates only if its package has the current expected unit count, codes, geometry validity, vintage, commercial terms, and checksum. Otherwise it is explicitly `blocked`, not silently substituted with districts.
3. **Too-coarse gate:** reject a candidate in a context if, for at least two anchor features, its median within-unit sample-point range exceeds 25% of that feature’s between-unit IQR. Also reject if median dominant land-cover share is lower than both adjacent finer candidates without a compensating feasibility benefit.
4. **Too-fine gate:** reject a finer candidate if it costs more than 2× units/storage/runtime of the next coarser candidate while improving both semantic-mixing error and within-unit location-loss by less than 5%, or if over 80% of adjacent-unit pairs have indistinguishable anchor vectors within declared numeric tolerance.
5. **Robustness gate:** no selected candidate may reverse its candidate ranking in more than one context under square-origin shifts, boundary jitter, or alternate population/built-up source sensitivity.
6. **Feasibility gate:** the selected candidate must fit a hardware/runtime/storage budget recorded before execution. If the owner supplies no budget, report the Pareto frontier and do not manufacture a single “best” candidate.
7. **Selection rule:** among candidates passing all hard gates, select a Pareto-nondominated option. If multiple remain, prefer lower nationwide storage/runtime, then simpler deterministic lat/lon lookup. H3 receives no convenience bonus.

## 5. Feature dictionary audit

Classification covers every feature in the original 34-feature MVP plus both contextual definitions.

| Original feature | Decision | Required change/reason |
|---|---|---|
| `urban_rural_class` | MODIFY | Do not default missing inputs to rural or invent thresholds. Use source-defined GHS-SMOD as contextual metadata, or defer custom classes to Gate 4 validation. |
| `distance_to_city_center_km` | MODIFY | Replace unsourced curated centers with a versioned GHS Urban Centre/approved city-center dataset; rename `distance_nearest_urban_centre_km`. |
| `population_density` | KEEP | Derive as aggregated population count / geodesic land-support area; add `population_count`. |
| `built_up_ratio` | KEEP | Pin exact GHSL product, epoch, and denominator; R2023A 100 m is not a 10 m raster. |
| `building_density` | DEFER | OSM footprint completeness is strongly spatially biased; test Overture/GHSL before using this as MVP signal. |
| `green_space_ratio` | MODIFY | “Green” is semantically mixed. Publish explicit `tree_cover_ratio`, `grass_shrub_ratio`, `cropland_ratio`, and `water_wetland_ratio` from a pinned legend. |
| `road_density` | KEEP | Define included/excluded highway classes and denominator as valid land area. Also retain `road_length_km`. |
| `intersection_density` | MODIFY | Define graph cleaning, grade separation, divided-road collapse, degree threshold, and valid land denominator. |
| `distance_nearest_main_road_m` | MODIFY | Rename `major_road`; define road classes and compute distance from unit representative point to line geometry in a metric CRS. |
| `bus_stop_count_500m` | MODIFY | Use deduplicated `transit_stop_count_1km`; the lone 500 m radius has no evidence yet and OSM platform/stop-position duplicates must be conflated. |
| `distance_nearest_bus_stop_m` | MODIFY | Use deduplicated transit-stop entities and expose mapped-source limitations. |
| `distance_nearest_bus_station_m` | MODIFY | Broaden/rename to versioned major transport hubs; do not mix parking into transit. |
| `school_count_1km` | KEEP | Keep schools separate from early childhood and higher education; count canonical entities, not raw OSM elements. |
| `university_count_1km` | REMOVE | Unjustified duplicate radius; retain one regional higher-education count plus nearest distance. |
| `university_count_3km` | MODIFY | Rename `higher_education_count_3km`; explicit university/college mapping. |
| `distance_nearest_university_m` | MODIFY | Rename to higher education and measure to original geometry. |
| `hospital_count_1km` | MODIFY | Use one empirically testable scope (provisionally 3 km) and keep hospitals distinct from clinics. |
| `clinic_count_1km` | KEEP | Explicit OSM healthcare/amenity tag mapping and mapped-zero caveat. |
| `distance_nearest_hospital_m` | KEEP | Measure to geometry; null plus search-status when no observed feature within configured maximum. |
| `pharmacy_count_1km` | KEEP | Useful but expected mapping bias must be quantified. |
| `restaurant_count_1km` | MODIFY | Rename `food_drink_count_1km`; exact restaurant/cafe/fast-food/bar/pub rollup. |
| `retail_count_1km` | MODIFY | Make disjoint from mall and marketplace; never match generic `shop` as one raw category. |
| `mall_count_3km` | KEEP | Exact `shop=mall` mapping, canonical entity count. |
| `market_count_1km` | MODIFY | Use `amenity=marketplace`; rename `marketplace_count_1km`. |
| `bank_count_1km` | DEFER | Branch/ATM conflation and rural mapping bias add little to the atomic prototype. |
| `factory_count_3km` | DEFER | “Factory/warehouse/logistics POI” is not a reliable single entity class. Prefer observed industrial-site polygon context first. |
| `industrial_land_ratio` | MODIFY | WorldCover/GHSL cannot supply this class. Rename `osm_industrial_site_area_ratio` and derive only from `landuse=industrial`, with explicit source-qualified name. |
| `distance_nearest_industrial_zone_km` | MODIFY | Distance to polygon geometry, not polygon centroid; use meters consistently. |
| `hotel_count_1km` | MODIFY | Rename `lodging_count_1km`; include explicit accommodation types without attractions. |
| `tourist_attraction_count_3km` | MODIFY | Rename `attraction_culture_count_3km`; define tourism/museum/gallery/historic mappings and deduplication. |
| `park_count_1km` | MODIFY | Use canonical park/recreation entities; do not count a polygon centroid that may fall outside the AOI. |
| `distance_nearest_park_m` | MODIFY | Distance to original park geometry. |
| `poi_density` | MODIFY | A 1 km circular buffer has a constant nominal area, making count and density redundant away from clipped support. Publish `poi_total_count_1km`; if density is retained, store valid-land support area and exact denominator. |
| `poi_diversity` | DEFER | Formula, category level, small-count behavior, and coverage sensitivity are unresolved. A simple category richness feature may be tested first. |
| `poi_density_peer_percentile` | DEFER | Gate 4; cohort definition and stability must be validated. Never encode undefined cohorts as zero. |
| `local_poi_density_ratio` | DEFER | Gate 4; original formula is peer-relative, not local. Define a geographic neighborhood separately from a peer cohort. |

### Recommended atomic MVP

The revised dictionary contains **35 atomic features**, plus identifiers, spatial metadata, provenance, and coverage fields that are not model features:

- Population (2): population count and density.
- Built/land cover (5): built-up, tree cover, grass/shrub, cropland, water/wetland ratios.
- Road/accessibility (5): total road length, all-road density, major-road length, intersection density, nearest-major-road distance.
- Urban/access context (1): nearest approved urban-centre distance.
- Transport nodes (3): stop count, nearest stop distance, nearest major transport-hub distance.
- POI services (15): school; higher education count/distance; hospital, clinic, pharmacy, nearest hospital; food/drink, retail, marketplace, mall; lodging; attraction/culture; park/recreation count/distance.
- Industrial observed context (2): OSM industrial-site area ratio and distance.
- Cross-POI atomic aggregates (2): total count and category richness at one documented radius.

No semantic scores belong in the MVP. Custom urban/rural classification, log/percentile transforms, peer/local normalization, entropy-based diversity, and weighted residential/commercial/education/tourism/industrial scores remain later-gate candidates.

## 6. Urban/rural normalization review

The architecture separates atomic and contextual layers, which is correct, but the original feature config prematurely names two contextual outputs and a custom urban/rural class. The MVP should expose raw absolute quantities and densities first. Gate 2/3 should preserve enough support metadata to test normalization later.

| Signal type | MVP/Gate | Recommendation |
|---|---|---|
| Absolute quantity | Gate 3 MVP | Keep counts/lengths/areas where meaningful. |
| Density | Gate 3 MVP | Keep only with explicit valid denominator and support area. |
| `log1p` | Gate 4 test | Test for heavy-tailed nonnegative counts/densities; it is a transform, not a universal replacement for raw values. |
| National percentile | Gate 4 test | Useful for ranking but loses magnitude and changes with national refreshes. Store raw plus transform version. |
| Peer percentile | Gate 4 test | Only after peer cohorts are stable, sufficiently large, source-independent, and not circularly defined by the same target feature. |
| Local density ratio | Gate 4 test | Define a geographic neighborhood (distance or graph rings), robust denominator (median/trimmed mean), edge handling, and zero policy. Do not call a peer-cohort ratio “local.” |

For Gate 2, calculate these transformations only as diagnostics for resolution stability; do not publish them as core features. Complex normalization is not justified until OSM completeness and urban/rural source bias are measured.

## 7. POI taxonomy review

The canonical taxonomy is implemented in `config/poi_taxonomy.yaml`. Its governing rules are:

- Canonical entities are deduplicated before aggregation. A school polygon and a school node referring to the same entity count once when conflation evidence exists.
- Point and polygon sources are retained. Counts use a stable representative point (`point_on_surface` for polygons); distances use original geometries; areal features use polygon intersection area.
- Rollups are disjoint at the leaf-category level. `retail_other` excludes supermarket, convenience, mall, and marketplace; transport parking is not transit.
- School, early childhood, and higher education are distinct.
- Mall, supermarket, convenience, marketplace, and other retail are distinct.
- Industrial sites (`landuse=industrial`) are areas; manufacturing works/warehouses are observed entities, not interchangeable with industrial land.
- Lodging and attractions/culture are distinct.
- Transport stops, stations, rail, airports, ports/ferry terminals, and parking are distinct.
- Unknown/unmapped tags are retained in an audit table rather than silently forced into `other`.

OSM-representation risk remains high for informal food/retail, pharmacies/clinics, small rural facilities, transit stops outside major cities, factories inside compounds, and homestays. Taxonomy correctness does not cure source completeness; report mapping coverage by AOI and category.

## 8. Architecture review

Required logical flow:

`Raw sources → Standardization → Spatial representation → Atomic features → Contextual features → Derived features → Optional semantic features → Final vector`

The original design combined raw ingestion and standardization and combined derived/semantic stages. The revised architecture separates their contracts. For every run, preserve:

- immutable raw URI/local path, retrieval timestamp, provider release/as-of timestamp, checksum, byte count, license ID, and extraction bounds;
- standardization code/config version, original/target CRS, geometry-repair counts, row counts, tag-mapping version, and rejected records;
- spatial method, resolution/size/admin vintage, grid origin, unit geometry version, actual area, representative point, and neighbor method;
- feature-set version, formula version, source dependencies, spatial support/denominator, computation timestamp, and run ID;
- per-source technical coverage and data-quality caveats, separate from feature zeros.

One run manifest plus normalized source/feature manifests is preferable to dozens of provenance columns repeated in every row. The final table should carry `run_id`, `feature_set_version`, and spatial keys; consumers can join detailed provenance from manifest tables.

Python, GeoPandas/Shapely, DuckDB Spatial, PyArrow, GeoTIFF/GeoParquet, and optionally H3 are proportionate. Spark, PostGIS, Kubernetes, Kafka, cloud orchestration, and distributed processing remain unjustified until Gate 6 measurements demonstrate a need.

## 9. Semantic-score challenge

`residential_score`, `commercial_score`, `education_score`, `tourism_score`, and `industrial_score` must remain **Gate 5 optional work**, not MVP. Weighted formulas encode use-case preferences, hide source bias, and are difficult to validate without an explicit downstream decision and labeled evaluation. Even Gate 5 should first expose formula/version/weights and compare stability across urban/rural contexts; core atomic features must remain available independently.

## D. Feature MVP recommendation

Adopt the 35-feature atomic set listed above. Keep metadata/coverage fields separate from model features. Defer custom classes, normalizations, diversity entropy, and every semantic score. The configuration and feature dictionary now reflect this recommendation.

## E. Data-source recommendation

First prototype: one dated Geofabrik PBF for POI/roads/transit nodes; WorldPop Global 2 R2025A v1 100 m constrained count for a pinned year; GHS-BUILT-S R2023A 100 m for a pinned epoch; ESA WorldCover 2021 v200; verified current province metadata; and a still-to-be-qualified post-2025 commune geometry package solely for the administrative candidate. Use Overture and alternate GHSL/Copernicus sources for AOI sensitivity/coverage audits before adding them to the production stack.

## F. Gate 2 experiment specification

The candidate matrix, AOIs, metrics, outputs, plots/maps, and acceptance criteria in Section 4 are the Gate 2 specification. Gate 2 ends with a results artifact and evidence-backed config update; it does not end merely because code generated H3 cells.

## G. Files modified by this review

- `docs/gate1_technical_review.md`: complete independent review and controlling Gate 2 recommendation.
- `docs/problem_definition.md`: owner-validation and testable technical-success corrections.
- `docs/data_sources.md`: audited corrections and preferred/fallback stack.
- `docs/spatial_unit_decision.md`: concrete candidate/metric/output/acceptance specification.
- `docs/feature_dictionary.md`: revised atomic MVP and explicit coverage/denominator policies.
- `docs/architecture.md`: separated standardization/derived stages and added manifest/coverage contracts.
- `config/spatial.yaml`: candidate matrix, AOIs, and metric/acceptance configuration.
- `config/poi_taxonomy.yaml`: source tag rules, disjoint categories, geometry and deduplication policy.
- `config/features.yaml`: revised MVP; contextual and semantic features disabled/deferred.
- `config/data_sources.yaml`: pinned product families, statuses, fallbacks, and blocking admin requirement.
