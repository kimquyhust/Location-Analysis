# Problem Definition

_Gate 1 deliverable. Status: independently reviewed; proceed only with the required fixes in [`gate1_technical_review.md`](gate1_technical_review.md)._

## 1. Restated scope

**Core project.** Build a reusable **Location Feature Vector** for Vietnam: a table keyed by a spatial unit (TBD, see [`spatial_unit_decision.md`](spatial_unit_decision.md)) that describes the *place itself* — what is physically and functionally present at that location — independent of any customer or trip data. The output is meant to be consumed by many downstream products, not built for one.

The feature taxonomy follows the pipeline mandated in [`CLAUDE.md`](../CLAUDE.md):

```
Raw geographic data → Atomic features → Contextual/normalized features → Derived features → Optional semantic scores
```

Each stage is a materialized layer, not a shortcut. Atomic features (counts, distances, ratios) are computed first and documented before any contextual normalization or semantic scoring is attempted (Gates 3–5).

**Core feature groups** (see [`feature_dictionary.md`](feature_dictionary.md) for the full MVP list):
- spatial/administrative context
- population
- built environment / land use / built-up area
- road network and transportation
- points of interest (education, healthcare, commercial, industrial, tourism, leisure)
- simple cross-POI counts/category richness

Contextual normalization is a Gate 4 experiment, not part of the atomic MVP.

**Explicitly out of scope for the core layer** (per `CLAUDE.md` non-negotiable scope):
- `customer_id`, `trip_id`
- pickup/dropoff counts, trip volume, OD flow
- customer segmentation or behavioral patterns

## 2. Core project vs. customer-mobility downstream tasks

This distinction is the single most important boundary in the project and is treated as a hard constraint, not a style preference.

| | Core location-feature project (this repo, Gates 1–7) | Customer-mobility downstream tasks (explicitly out of scope here) |
|---|---|---|
| Subject | The location itself (a grid cell / H3 cell / admin unit) | A customer, a trip, or an OD pair |
| Inputs | POI, roads, population, land use, built-up area, admin boundaries — all *supply-side* geographic data | Pickup/dropoff logs, trip volumes, customer segments — *demand-side* behavioral data |
| Reusability | Designed to be reused by any product that needs "what is this place like" (pricing, expansion planning, risk, marketing, mobility) | Specific to one mobility/demand modeling use case |
| Update cadence | Tied to how often POI/population/land-use sources refresh (months–years) | Tied to operational trip data (near real-time) |
| Where it lives | This repo, `data/features/location_feature_vector.parquet` | A separate downstream pipeline that *joins onto* the location feature vector by spatial-unit key |

Customer mobility data may eventually **consume** the location feature vector (e.g., join trip data onto a location's POI density to explain demand), but mobility signals must never leak backward into the construction of the core feature layer. This prevents the feature vector from being a disguised proxy for existing trip patterns, which would make it circular for any use case that tries to *predict* mobility/demand from location characteristics.

## 3. Why this separation matters (problem framing)

If the location feature layer were built from trip data (e.g., `pickup_count` as a location feature), then:
- any downstream model using this layer to *predict or explain* demand would be trained on a feature that already encodes demand — a leakage/circularity failure, not a modeling improvement.
- the feature layer would only be valid where the mobility product already operates, defeating the goal of a *reusable, nationwide* layer usable for expansion into areas with no existing trip data.

This is why Gate 1 explicitly forbids touching customer/trip data, and why `CLAUDE.md` hard-bans those fields from the core layer.

## 4. User and pain-point hypothesis

The repository does not identify an approved primary user. The working hypothesis is a data scientist or geospatial analyst who needs a reproducible feature row for an arbitrary Vietnam latitude/longitude and a stable table for batch joins. Likely pain points are inconsistent spatial keys, repeated source-specific preprocessing, unknown source vintage/coverage, and leakage from demand data. These are hypotheses to validate with the project owner, not discovered user research.

The defensible insight is narrower: an upstream, source-versioned description of place can be reused across downstream decisions and in locations without customer activity. Therefore the direction is to build atomic geographic observations first, then validate contextual transforms and use-case-specific scores separately.

## 5. Success criteria for the core layer

`PROJECT_BRIEF.md` currently contains section headers only (Problem, Users, Pain points, Insight, Direction, Scope, Out-of-scope, Feature taxonomy, Spatial-unit study, Data sources, Normalization, MVP, Deliverables, Definition of success) with no filled-in content. In the absence of that content, the operative source of truth for Gate 1 is `CLAUDE.md` plus the existing repo scaffolding (`README.md`, `config/*.yaml`, `src/` module layout), which are internally consistent with each other. **This is flagged as an open item**: `PROJECT_BRIEF.md` should be filled in by the project owner so that "Definition of success," "Users," and "Pain points" are grounded in real requirements rather than inferred ones. See the Open Assumptions section of [`architecture.md`](architecture.md).

Testable technical success for Gate 2–3:

1. A coordinate inside the supported Vietnam land mask maps deterministically to exactly one spatial-unit key; boundary/tie behavior is tested.
2. Gate 2 evaluates every qualified candidate across every required context and selects only through the documented acceptance rules, or reports no decision.
3. Re-running pinned source artifacts and config/feature versions produces identical outputs within declared numeric tolerance.
4. Every output row identifies the spatial method/resolution, feature-set version, source manifest, and run; detailed checksums/releases live in linked manifests.
5. Technical source failure/non-coverage is distinguishable from a successful measured zero.
6. Every MVP feature has an explicit source, unit, geometry treatment, spatial support, denominator, calculation, missing policy, and limitation.
7. The core output contains no customer/trip-derived columns or hidden demand proxies.

The approximate 25–40 feature range and use of commodity tools are scope/engineering constraints, not evidence of user value. Business success—adoption, downstream utility, SLA, refresh cadence, and distribution terms—must be added by the project owner.

## 6. Missing governing inputs

`COWORK_START_PROMPT.md` and `CLAUDE.md` both reference `.claude/skills/location-feature-engineering/SKILL.md` and its `references/`. **That directory does not exist in this repository** (`.claude/` has no files at all). Gate 1 was therefore executed using `CLAUDE.md` as the authoritative methodology document, since its content (non-negotiable scope, feature-documentation checklist, spatial-unit-comparison mandate, tooling principles, gates) covers the same ground a skill file would. If a skill package exists elsewhere and should govern this project, it should be added to the repo and Gate 1 outputs re-checked against it.
