# Vietnam Location Feature Vector

Starter project for building a reusable **Location Feature Layer for Vietnam**.

## Core idea

The project builds standardized features describing geographic locations themselves.

**Core project:**
- spatial unit
- POI
- population
- road / transport
- land use
- accessibility
- contextual normalization
- optional semantic area scores

**Out of scope for the core layer:**
- customer trips
- pickup/dropoff volume
- customer mobility
- OD flow
- behavioral segmentation

Customer mobility is a downstream consumer of the location feature layer.

## Recommended workflow

1. Read `CLAUDE.md`
2. Read `PROJECT_BRIEF.md`
3. Read `.claude/skills/location-feature-engineering/SKILL.md`
4. Run the design/research phase first
5. Do not build nationwide data pipelines until the spatial-unit and data-source decisions are documented
6. Build atomic features before semantic scores

## Main deliverables

- `docs/problem_definition.md`
- `docs/data_sources.md`
- `docs/spatial_unit_decision.md`
- `docs/feature_dictionary.md`
- `docs/architecture.md`
- `docs/validation_report.md`
- `data/features/location_feature_vector.parquet`
