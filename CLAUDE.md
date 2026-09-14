# Claude Project Instructions

Read `PROJECT_BRIEF.md` before making architecture decisions.

## Non-negotiable scope

The core output is a reusable **Location Feature Vector**.

Customer mobility data is downstream only.

Do NOT use:
- customer_id
- trip_id
- pickup_count
- dropoff_count
- trip volume
- OD flow
- customer segmentation
- customer behavioral patterns

to construct the core location feature layer.

## Working methodology

Always separate:

Raw geographic data
→ Atomic features
→ Contextual / normalized features
→ Derived features
→ Optional semantic scores

Do not skip directly from raw data to area scores.

## Spatial unit

Do not assume H3 automatically.

Compare:
- administrative boundaries
- square grids
- H3

If H3 is used, evaluate multiple candidate resolutions empirically.

## Before implementing any feature

Document:
1. feature definition
2. source dataset
3. grain
4. radius / spatial scope
5. unit
6. calculation
7. missing-data policy
8. normalization policy
9. limitations

Update `docs/feature_dictionary.md`.

## Tooling principles

Prefer for MVP:
- Python
- GeoPandas
- Shapely
- DuckDB + Spatial
- PyArrow
- GeoParquet / Parquet
- H3 only if justified

Do not introduce Spark, Sedona, PostGIS, Kafka, or cloud infrastructure unless scale measurements show they are needed.

## Engineering principles

- No production logic in notebooks.
- Keep code modular and configurable.
- Do not hard-code radii, H3 resolutions, category mappings, scoring weights, or paths.
- Add tests for spatial conversion, POI mapping, aggregation, and missing-value behavior.
- Document major design decisions under `docs/`.

## Gates

Do not move to the next gate without an artifact from the previous one.

Gate 1: data-source research  
Gate 2: spatial-unit evaluation  
Gate 3: atomic feature MVP  
Gate 4: contextual normalization  
Gate 5: optional semantic scores  
Gate 6: nationwide scale  
Gate 7: location lookup demo
