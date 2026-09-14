# Data Sources — Vietnam (Gate 1, reviewed)

_No nationwide pipeline has been run. “Global” below is provider scope, not proof of complete Vietnam records. Exact release, URI, checksum, byte count, license text, and retrieval time must be captured in each run manifest. Full evidence is in [the technical review](gate1_technical_review.md)._

## Administrative context

Vietnam changed to 34 provincial-level units and 3,321 commune-level units, with district-level administrations ending on 1 July 2025. This is confirmed by the [Government of Vietnam](https://en.baochinhphu.vn/historic-milestone-in-modern-viet-nam-111250701123506887.htm). Any earlier geometry is historical, not a current spatial key.

The government describes an official map while noting continued commune-boundary correction ([official notice](https://baochinhphu.vn/tra-cuu-dia-gioi-sau-sap-nhap-qua-ban-do-dien-tu-102250708175104468.htm)). A web map does not establish a bulk-download license.

## POI, roads, buildings, and transport

| Source | Provider / coverage | Resolution, update, access, format | License / commercial use | Decision |
|---|---|---|---|---|
| OpenStreetMap via Geofabrik | OSM contributors; Vietnam country extract, variable real-world completeness | Native vector; daily bulk PBF plus diffs; reviewed PBF about 313 MB | ODbL 1.0; commercial use allowed with attribution and derivative-database obligations | **Preferred** for POI, roads, and mapped transit nodes. PBF is complete/unfiltered; free SHP/GPKG is filtered. |
| BBBike | BBBike redistribution of OSM; cities/custom AOIs | PBF, GeoJSON, GeoParquet, GPKG, SHP and others; daily/weekly depending product | ODbL | AOI convenience only; same lineage and not an independent nationwide fallback. |
| HOTOSM | HOT/HDX redistribution of OSM | Theme/AOI vector packages; periodic/custom | ODbL | Extraction cross-check only; avoid a duplicate primary pipeline. |
| Overture Places | Overture; advertised global POI points | GeoParquet; monthly global release; bbox query through DuckDB/CLI; Vietnam counts unmeasured | CDLA-Permissive 2.0 or Apache 2.0 by source; no OSM in Places | **Independent POI fallback/QA** after Vietnam category audit. |
| Overture Transportation | Overture; global roads/rail/ferries, primarily OSM with enhancements | Segment/connector GeoParquet; monthly cloud bulk/bbox access | ODbL | **Road fallback/QA**; measure incremental Vietnam coverage. |
| Overture Buildings | Overture; global conflated footprints | Polygon GeoParquet; monthly cloud access | ODbL | Footprint fallback after AOI precision test; provider warns ML precision risk in the Global South. |

Primary pages: [Geofabrik Vietnam](https://download.geofabrik.de/asia/vietnam.html), [Geofabrik technical details](https://download.geofabrik.de/technical.html), [OSM license](https://www.openstreetmap.org/copyright), [BBBike](https://download.bbbike.org/osm/), [Overture Places](https://docs.overturemaps.org/guides/places/), [Overture Transportation](https://docs.overturemaps.org/guides/transportation/), [Overture Buildings](https://docs.overturemaps.org/guides/buildings/), and [Overture access](https://docs.overturemaps.org/getting-data/cloud-sources/).

**Transit limitation:** no current, licensed, nationwide Vietnam GTFS source was established. Hanoi-only data cannot support nationwide frequency or service-quality features. MVP transport features describe mapped nodes only.

## Population

| Source | Provider / coverage | Resolution, update, access, format | License / commercial use | Decision |
|---|---|---|---|---|
| WorldPop Global 2 R2025A v1 | University of Southampton; explicit Vietnam package | Approx. 100 m, people per pixel, GeoTIFF; annual estimates 2015–2030; reviewed count file about 72 MB; catalog/STAC/direct/API | Vietnam catalog says CC BY 4.0; commercial reuse with attribution | **Preferred.** Pin one year and bulk GeoTIFF. Sum counts, then derive density. Current page labels release alpha, so validate totals. |
| GHS-POP R2023A | EC JRC GHSL; global | 100 m/1 km or 3/30 arc-second; count/density by projection; five-year epochs 1975–2030; bulk GeoTIFF | EU reuse authorized with acknowledgment | **Fallback/QA.** Independent implementation, but also modeled. |
| Vietnam NSO/GSO | Official nationwide administrative totals | Tables/reports, not a raster; no qualified bulk spatial API identified | Check exact publication terms | Calibration/total checks only. |
| Meta HRSL | Historic Vietnam product | High-resolution raster; frozen/discontinued | Product terms not verified | Do not use as primary; optional historical QA. |

Sources: [WorldPop Vietnam Global 2 count](https://hub.worldpop.org/geodata/summary?id=75408), [WorldPop product catalog](https://hub.worldpop.org/project/categories?id=3), [GHS-POP](https://human-settlement.emergency.copernicus.eu/ghs_pop2023.php), and [Vietnam NSO codes](https://danhmuchanhchinh.nso.gov.vn/).

## Land cover and built-up surface

| Source | Provider / coverage | Resolution, update, access, format | License / commercial use | Decision |
|---|---|---|---|---|
| ESA WorldCover 2021 v200 | ESA/VITO consortium; global | 10 m, 11-class COG, WGS84; static release via downloader/AWS/Zenodo/GEE | CC BY 4.0 | **Preferred land-cover prototype.** 2020 and 2021 used different algorithms, so their difference is not pure land-cover change. |
| Copernicus LCFM LCM 2020 v1 | Copernicus CLMS/VITO; global | 10 m GeoTIFF/COG; operational successor line via CDSE S3/OData/browser | Product metadata says CC BY 4.0 | **Fallback/future primary** after later releases mature and local comparison. |
| GHS-BUILT-S R2023A | EC JRC GHSL; global | Generalized 100 m and 1 km built-up surface; five-year epochs 1975–2030; GeoTIFF | EU reuse authorized with acknowledgment | **Preferred built-up MVP.** Non-residential is not synonymous with industrial. |
| GHS-BUILT-S E2018 | EC JRC GHSL; global | Separate 10 m sub-pixel built-up fraction, 2018 snapshot | Same GHSL policy | Higher-resolution fallback/QA, not a current time series. |

WorldCover and LCFM are land **cover**, not authoritative land-use zoning; neither supplies residential/commercial/industrial zoning. Sources: [WorldCover access/license](https://esa-worldcover.org/en/data-access), [Copernicus LCFM](https://land.copernicus.eu/en/products/global-dynamic-land-cover/land-cover-2020-raster-10-m-global-annual), and [GHSL datasets](https://human-settlement.emergency.copernicus.eu/datasets.php).

No licensed, current, authoritative nationwide Vietnam zoning/land-use parcel source was qualified. OSM `landuse=*` is an observed community map and may support explicitly source-qualified features such as `osm_industrial_site_area_ratio`; it must not be presented as official land use. Residential/commercial land-use ratios are deferred.

## Administrative boundaries and urban centres

| Source | Provider / coverage | Resolution, update, access, format | License / commercial use | Decision |
|---|---|---|---|---|
| OCHA COD-AB 2025 | OCHA/authoritative lineage; downstream catalogs report 34 current provinces | ADM1 bulk vector package; exact metadata/date/bytes require package inspection | Verify exact package terms; do not infer | Province metadata candidate after validation. A current 3,321-unit polygon package was not confirmed. |
| geoBoundaries current API | William & Mary geoBoundaries | API reports Vietnam ADM1 year 2008/64 units and ADM2 year 2020/708 districts; ZIP/GeoJSON | Record-specific Public Domain / CC BY 3.0 IGO | **Reject for current geometry.** Historical QA only. |
| Overture Divisions | Overture; advertised global, primarily OSM + geoBoundaries | Point/area/boundary GeoParquet; monthly cloud release | ODbL | Fallback only if a Vietnam query verifies all current units, codes, geometry, and timestamps. |
| GADM 4.1 | GADM; nationwide historic hierarchy | GPKG/SHP, versioned | Official license disallows commercial use/redistribution without permission | Reject for commercial MVP absent written permission. |
| GHS Urban Centre Database R2024A | EC JRC GHSL; global | Versioned urban-centre geometry/database | GHSL reuse policy | Preferred reproducible source for nearest-urban-centre distance; pin release. |

Sources: [geoBoundaries Vietnam API](https://www.geoboundaries.org/api/current/gbOpen/VNM/ALL/), [Overture Divisions](https://docs.overturemaps.org/guides/divisions/), [GADM license](https://gadm.org/license.html), and [GHSL downloads](https://human-settlement.emergency.copernicus.eu/downloadWizard.php).

## Preferred stack

| Category | Preferred | Fallback | Reason |
|---|---|---|---|
| POI | Dated Geofabrik OSM PBF | Overture Places | Reproducible tag-rich source plus independent QA option. |
| Roads | Same Geofabrik PBF | Overture Transportation | One bulk source; Overture normalized but shares lineage. |
| Population | WorldPop Global 2 R2025A v1, pinned year, 100 m count | GHS-POP R2023A 100 m | Current Vietnam package plus independent sensitivity source. |
| Land cover | WorldCover 2021 v200 | Copernicus LCFM 2020 v1 | Stable documented prototype versus operational successor. |
| Built-up | GHS-BUILT-S R2023A 100 m, pinned epoch | E2018 10 m | Consistent time series plus higher-resolution check. |
| Province metadata | Verified OCHA 2025 ADM1 + NSO codes | Overture after validation | Current code/name context. |
| Commune geometry | **No qualified source yet** | Overture/OSM only after full validation | Declaring the gap is safer than using stale districts. |
| Transit nodes | Geofabrik OSM | Overture after AOI audit | Nationwide schedules were not established. |

## Extraction and scale rules

- Use bulk PBF, GeoTIFF/COG, and GeoParquet. Do not issue Overpass or per-polygon population API calls for nationwide computation.
- Clip sources once per AOI/prototype; do not download national/global assets repeatedly.
- Do not blindly union OSM, HOTOSM, BBBike, and Overture. Record lineage and conflate canonical entities.
- Before use, capture source ID, provider, product/release, represented date, retrieval time, URI, local path, SHA-256, bytes, license ID, CRS, bounds, and expected/present assets.
- Measure Vietnam/AOI presence, completeness proxies, geometry validity, and taxonomy yield. Provider “global coverage” is not a quality result.
