Problem
Users
Pain points
Insight
Direction
Scope
Out-of-scope
Feature taxonomy
Spatial-unit study

Owner-provided constraints (2026-09-14, recorded verbatim in intent; see docs/gate2_mvp_decision.md):
- H3 is the owner-approved provisional spatial-unit family for the MVP.
- Gate 2 evaluates only which H3 resolution the MVP uses (r8, r9 or r10); this is an MVP engineering decision, not a claim that H3 or the chosen resolution is optimal for every location in Vietnam.
- The full square-grid / administrative comparison is deferred until after the atomic-feature MVP, preferably Gate 6; full nationwide validation remains Gate 6.
- The Gate 2 run of 2026-09-14 (run_20260914T091321Z) is diagnostic only because two raster clips were truncated at tile boundaries.
- Time-to-MVP is prioritised over research-grade completeness.
- No hardware, runtime, storage budget or lookup-latency requirement has been provided; none is assumed.
Data sources
Normalization
MVP

- Spatial unit: H3 resolution 9, provisional (config/spatial.yaml spatial_unit.decision_status: provisional_mvp); selected by the rule in docs/gate2_mvp_decision.md.
- Representative test geography for the MVP decision: hanoi_core, hoi_an, mu_cang_chai, dong_thap_rural. The other four AOIs in config/spatial.yaml are deferred validation contexts.
Deliverables
Definition of success