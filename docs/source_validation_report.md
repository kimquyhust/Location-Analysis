# Source Validation Report — Da Nang–Hoi An Prototype (Revision 4 — CLOSED)

**Revision 4 note (this pass)**: a third independent review of Revision 3 found three remaining issues, all closed here (§10): (1) §9's reproduction command was unpinned and would have silently acquired a newer Overture release than the audited `2026-08-19.0` — the CLI now requires an explicit release (§2.2); (2) §2.5/§6/§7 described a `≥0.3` recommendation for retail/commercial_service/healthcare as resting on "combined proxy + manual evidence" when the n=16 manual sample contains only `food_drink` and `lodging` records and none of those three groups — evidence is now labelled per group and nothing is generalized across groups (§2.5); (3) §3.4's Overture-only road-inspection groups did not sum to 8 — they now partition the 8 samples exactly (§3.4). **No measured value changed in this pass.** The corrections are to claims about what the measurements support, plus one CLI behaviour change; every headline count in §3–§5 is byte-identical to Revision 3's.

**Revision note (Revisions 2–3)**: Revision 2 was a full rewrite addressing six P1-severity implementation defects found by an independent review of the original report. A **second** independent review of Revision 2 itself found seven further defects: two P1s (derived/Overture-asset reuse trusted sidecar metadata without re-verifying the actual file; two manually-curated CSV evidence files were malformed or missing required provenance fields) and five P2s (a "coastal" stratum that doesn't capture coastlines, a duplicate-rate metric not scoped to match its own headline framing, a review-sample count typed by hand rather than read from the artifact, a false claim about retrieval-timestamp provenance, and no explicit manifest run-status field). This revision fixes all seven with regenerated code, data, and evidence — again, not report language alone. Sections mark **Measured** (computed directly from the AOI data), **Heuristic** (a defined proximity/statistical rule, not ground truth), **Manual** (a human/web-assisted judgment on a small disclosed sample), and **Unresolved** (not established either way).

**Scope**: POI (Overture Places / OSM), road (OSM / Overture Transportation), and population (WorldPop 2025 / WorldPop 2020 vs. GHS-POP 2020) source validation for the Da Nang–Hoi An corridor. `docs/architecture.md` untouched (confirmed by unchanged SHA-256 `bd9b5ab71e95e75705676ecf00e8532584fec1ec11e9c9e9a12915c1164cfa15`, both before and after this revision); no spatial-unit decision or semantic scoring made; no customer/trip/mobility data used; OSM and Overture road networks were never unioned.

**Run date**: 2026-09-14. **AOI**: Evaluation `(108.10, 15.75, 108.35, 16.15)`, Acquisition `(108.07, 15.72, 108.38, 16.18)` (≈3 km halo). **Metric CRS**: EPSG:32649 (UTM 49N).

---

## 1. Exact releases and retrieval facts — Measured

**Authoritative manifest for this revision**: `data/manifests/source_manifest_20260914T075515Z.json`, `status: "complete"`. Three earlier manifests also exist and are kept (manifests are immutable — a failed or superseded run is never edited or deleted): `..._050158Z.json` (the original, pre-fix run), `..._070811Z.json` (an attempt that **failed and is incomplete by design** — it hit the exact live-release-resolution bug fixed in Revision 2 §2.2, and correctly stopped rather than silently falling back to a stale release), and `..._070943Z.json` (Revision 2's manifest, superseded by this run because the manifest schema changed — see §2.11 below). `RunManifest` now carries an explicit `status` field (`in_progress` / `complete` / `failed`) rather than being distinguishable from a genuinely-failed run only by having fewer entries (`src/ingestion/manifest.py::RunManifest.mark_failed`, §2.11).

| source_id | bytes | sha256 (first 12) | `is_derived` | `retrieved_at_utc` | `retrieved_at_utc_method` |
|---|---:|---|---|---|---|
| `osm_geofabrik_vnm_20260913` | 328,456,722 | `3c4b19fea3e5` | no | 2026-09-14T04:38:42Z | `filesystem_mtime_proxy` |
| `worldpop_vnm_2025_cn_100m_r2025a_v1` | 75,215,955 | `21f403884d5a` | no | 2026-09-14T04:44:57Z | `filesystem_mtime_proxy` |
| `worldpop_vnm_2020_cn_100m_r2025a_v1` | 74,064,549 | `d615df574ef2` | no | 2026-09-14T04:50:10Z | `filesystem_mtime_proxy` |
| `ghspop_e2020_r2023a_r8_c29` | 39,426,582 | `d83c34aa9e10` | no | 2026-09-14T04:38:04Z | `filesystem_mtime_proxy` |
| `osm_aoi_extract_complete_ways` | 7,705,634 | (see manifest) | **yes**, parent=`osm_geofabrik_vnm_20260913` | 2026-09-14T07:08:23Z | `derived_at_utc` |
| `worldpop_2025_aoi_clip` | 482,304 | (see manifest) | **yes**, parent=`worldpop_vnm_2025_cn_100m_r2025a_v1` | 2026-09-14T07:08:23Z | `derived_at_utc` |
| `worldpop_2020_aoi_clip` | 475,801 | (see manifest) | **yes**, parent=`worldpop_vnm_2020_cn_100m_r2025a_v1` | 2026-09-14T07:08:24Z | `derived_at_utc` |
| `ghspop_e2020_native_extracted` | 41,319,162 | (see manifest) | **yes**, parent=`ghspop_e2020_r2023a_r8_c29` | 2026-09-14T07:08:24Z | `derived_at_utc` |
| `overture_places_place_2026-08-19.0` | 12,896,272 | (see manifest) | no | 2026-09-14T07:10:16Z | `overture_sidecar` |
| `overture_transportation_segment_2026-08-19.0` | 15,060,893 | (see manifest) | no | 2026-09-14T07:11:35Z | `overture_sidecar` |
| `overture_transportation_connector_2026-08-19.0` | 6,131,212 | (see manifest) | no | 2026-09-14T07:11:54Z | `overture_sidecar` |

These `retrieved_at_utc` values are unchanged from Revision 2's manifest because every derived and Overture asset was **reused this run** (its content passed the new integrity re-verification in §2.6 below) rather than regenerated — reuse correctly preserves the original derivation/fetch time, it does not bump it to "now."

**Correcting a Revision 2 misstatement (P2 §2.10 below)**: Revision 2 claimed the four raw assets' `retrieved_at_utc` values were "real original download timestamps... recovered from filesystem mtimes." That claim was **false as evidence, even though the underlying numbers were genuinely mtime-derived** — filesystem mtime is not proof of when a file was actually first downloaded (it can be changed by copies, checkouts, or any filesystem operation unrelated to the original fetch), and the sidecars backing those numbers recorded a placeholder `url` (`"backfilled-from-filesystem-mtime"`), not the asset's real URL, so there was no way to even confirm the sidecar was describing *this* asset. This revision's `download_pinned()` now: (a) only trusts a sidecar's recorded `retrieved_at_utc` if the sidecar's `url` field matches the asset's actual pinned URL; (b) otherwise falls back to the file's mtime **explicitly labeled** `retrieved_at_utc_method: "filesystem_mtime_proxy"` in both the sidecar and the manifest — never presented as a real retrieval time. The four values above are unchanged numerically from Revision 2 (same files, same mtimes) but are now honestly labeled as a proxy, not a fact.

**What changed from Revision 1's manifest** (Revision 2 §2.4 fixes):
- Every derived asset (AOI extracts/clips) now has its **own manifest entry**, linked to its parent's exact checksum and the exact transform parameters used (`src/ingestion/run_acquisition.py::derive_or_reuse`) — Revision 1 had no manifest entries at all for these.
- `expected_sha256` is now pinned for all four raw assets (using the values verified across this project's multiple independent downloads) — a reused file is checksum-verified, not just byte-count-verified.
- Downloads are atomic (`.partial` → verified → renamed into place); a crashed download can never leave a file at the canonical path.

**What changed from Revision 2's manifest** (this revision, §2.6–2.11 below): `retrieved_at_utc_method` added to every entry; derived-asset and Overture reuse now re-verifies the actual file (checksum/bytes/row-count/local-schema for Overture; checksum/bytes + revalidation for derived assets) instead of trusting sidecar metadata alone; explicit `status`/`failure_reason` fields on the manifest itself.

---

## 2. Fix-by-fix account: six P1 findings from the first review (§2.1–2.5), plus two P1 and five P2 findings from a second review of Revision 2 (§2.6–2.11)

### 2.1 Road audit AOI consistency (P1) — **Fixed**

**The bug**: length/overlap metrics used the evaluation AOI (clipped), while connectivity/intersection metrics used the raw, unclipped road graph — which, because `osmium extract --strategy complete_ways` pulls in the full length of any way merely touching the acquisition bbox, could include stray way fragments extending hundreds of km beyond the AOI (observed directly in this project's Gate-1 work).

**The fix** (`src/roads/topology.py::induced_subgraph_within_bbox`, `src/audit/road_audit.py`): every connectivity/intersection metric is now computed on an **explicitly bbox-bounded induced subgraph** — a node is in-scope only if its coordinate falls inside the given bbox, and an edge is in-scope only if **both** endpoints are in-scope (an edge crossing the boundary is dropped entirely, never partially attributed). This rule is applied **identically** to OSM and Overture, at **two nested, separately labeled scopes**:
- **acquisition-halo scope**: bounded to the acquisition AOI (not the raw unbounded graph)
- **evaluation scope**: bounded to the evaluation AOI

| | OSM (halo) | OSM (eval) | Overture (halo) | Overture (eval) |
|---|---:|---:|---:|---:|
| connected components | 119 | 91 | 121 | 92 |
| largest component share | 99.20% | **99.56%** | 99.31% | **99.59%** |
| intersection/connector count (deg≥3) | 47,683 | 42,301 | 47,188 | 41,769 |

**Reconsidering "near-identical connectivity"**: it still holds, and on a cleaner basis than Revision 1's mixed-scope numbers implied. At matched evaluation scope, OSM and Overture largest-component share differ by only **0.03 percentage points** (99.56% vs. 99.59%) — closer than Revision 1's mismatched comparison (99.18% vs. 99.32%, a 0.14-point gap that was partly a scope artifact, not a real difference). Interestingly, eval-scope share is *higher* than halo-scope share for both sources (91 vs. 119 components, but a higher largest-share) — consistent with the acquisition halo containing some smaller disconnected rural fragments that the evaluation core doesn't, not with the evaluation cut fragmenting a previously-connected network. `feature_impact_notes` in the regenerated `road_audit_summary.json` is empty because no fragmentation-artifact threshold was tripped in either direction. Full data: `data/prototype/danang_hoian_halo/audit/road_audit_summary.json`.

### 2.2 Overture release provenance (P1) — **Fixed**

**The bug**: `resolve_release()` caught all failures and silently fell back to a hardcoded `PINNED_RELEASE` constant; and an existing AOI parquet was reused based on file existence alone, then labeled with whatever release was resolved on the CURRENT run — falsely attributing an old subset to a new release.

**The fix** (`src/ingestion/acquire_overture.py`):
- `resolve_release()` **raises `ReleaseResolutionError`** on any failure — no fallback exists in the code path at all anymore. (Discovering this fix was necessary happened for a genuine, non-hypothetical reason: DuckDB's S3 `glob('release/*/')`, which Revision 1 used, does **not** reliably do prefix-only "directory" listing against this bucket — it returned zero rows in this session even though the equivalent plain S3 REST `ListObjectsV2?delimiter=/` call returns the two real release folders. `resolve_release` now calls that REST API directly.)
- Every AOI subset gets a **provenance sidecar** (`<path>.meta.json`) recording exactly which `theme`/`type`/`release`/`bbox`/`schema_columns` produced it.
- Reuse requires an **exact match** on all of those fields (`sidecar_matches_request`); any mismatch — or a missing sidecar, e.g. a file from before this fix — is refused and the subset is re-fetched, never silently relabeled.
- `acquire_aoi_subset` distinguishes **pinned mode** (an exact release string) from **live-resolution mode** (`release=None`) explicitly, and both are recorded in the manifest's `notes` field (`acquisition_mode=...`).
- Live schema validation (`validate_schema`) runs before every fetch and raises `OvertureSchemaError` if a column the audits depend on (`basic_category`, `confidence`, `sources`, `bbox`, `connectors`, etc.) is missing.

**Closing the last implicit-latest path (this pass).** Revision 3 still let live resolution be reached by *omission*: `python -m src.ingestion.run_acquisition` with no arguments defaulted to `--overture-release=None`, i.e. "whatever the bucket holds right now." That default made the report's own reproduction command non-reproducible the moment Overture published a newer release — the audited run used **2026-08-19.0**, but a reader following §9 would have silently acquired something else. The CLI now requires **exactly one** of:

| flag | mode | reproducible |
|---|---|---|
| `--overture-release RELEASE` | pinned | yes |
| `--resolve-latest` | live resolution, explicitly opted into by name | no — record the resolved release from the manifest |

Supplying neither is an argparse error (exit 2), not a silent selection; supplying both is also an error. The contract lives in `src/ingestion/acquire_overture.py::add_release_args` / `release_from_args` and is applied by both CLI entry points (`run_acquisition.main`, `acquire_overture.main`). The library function `acquire_aoi_subset(release=None)` still means live resolution — but reaching `None` is now an explicit caller decision rather than a CLI default. `tests/test_release_cli_contract.py` covers pinned pass-through, the neither-flag rejection, the both-flags rejection, the direct-call guard, and asserts that §9's literal command both parses and pins `2026-08-19.0` (so this report and the CLI cannot drift apart).

This revision's data was acquired live-resolved against release **2026-08-19.0** (verified at the time as the lexically-latest of the two releases retained by the bucket). That historical fact is unchanged; what changed is that reproducing it now requires naming it.

### 2.3 OSM duplicate logic (P1) — **Fixed, and the headline number changed materially**

**The bug**: the dedup algorithm clustered any same-category, same-normalized-name entities within 75 m **regardless of geometry type** — so two distinct node-mapped businesses sharing a franchise name 50 m apart (two different WinMart branches) were incorrectly collapsed into one. Revision 1's own output showed 99 of 119 "duplicate" pairs were node–node.

**The fix** (`src/poi/dedup.py`, full rewrite): a union-find graph is built with edges **only between a Point and a Polygon/way** representation (same category, ≤75 m, matching normalized name **or** normalized OSM `brand` tag) — node–node and way–way pairs can never be directly merged, per `config/poi_taxonomy.yaml`'s actual cross-geometry-dedup definition. Clustering is transitive (a node linked to a shared polygon from two sides still merges into one cluster) and deterministic (fixed sort order; identical results regardless of input row order — tested explicitly).

| | Revision 1 (buggy) | Revision 2 (fixed) |
|---|---:|---:|
| duplicate pairs found | 119 | **15** |
| duplicate rate (of 8,524 pre-dedup POIs) | 1.40% | **0.176%** |

10 new tests (`tests/test_dedup.py`) cover node–node non-merge, way–way non-merge, node–polygon merge, brand-only matching, far-apart non-merge, missing-name non-merge, chained transitive merging, and order-independence.

### 2.4 Reproducible acquisition and manifest (P1) — **Fixed**

- **Checksums**: all four raw assets now have `expected_sha256` pinned (`src/ingestion/run_acquisition.py::PINNED_ASSETS`); `download_pinned` verifies checksum on reuse, not just byte count (`tests/test_download.py`).
- **Atomicity**: downloads write to `<dest>.partial`, verify, then `os.replace` into `<dest>` — a crash mid-download can never leave a reusable-looking file at the canonical path (tested).
- **CRS/NoData/schema/PBF-structure validation**: `src/ingestion/validators.py` (`validate_raster`, `validate_osm_pbf`) runs on every raw and derived asset and is wired into the manifest's `validation` field; Overture's `validate_schema` runs before every fetch.
- **Derived-asset manifest entries**: the OSM AOI extract, both WorldPop AOI clips, and the extracted-native GHS-POP raster each now have a manifest entry recording `parent_source_id`, `parent_sha256`, the exact `transform` dict used, and the validation result (§1 table).
- **Never mislabels retrieval time**: fixed via filesystem-mtime backfill for pre-existing raw assets (§1) and via the sidecar mechanism for everything acquired from here on.

12 new tests (`tests/test_acquisition_provenance.py`) cover release-resolution failure/success, sidecar match/mismatch (stale release, bbox mismatch, missing columns), and the generic derived-asset reuse helper (fresh/reuse/parent-changed/transform-changed/no-sidecar cases).

### 2.5 Overture Places confidence/provider analysis (P1) — **Fixed**

**The bug**: a `>=0.5` confidence recommendation was based only on retention-rate-by-group, with no evidence it corresponded to record quality; provider analysis only looked at the first non-Overture entry in `sources[]`.

**Multi-provider analysis, corrected** — Measured, on ALL of `sources[]`, not just the first entry:

| | value |
|---|---:|
| records with >1 contributing (non-Overture) provider | **0 / 72,750 (0.0%)** |
| records with exactly 1 contributing provider | 72,750 (100%) |
| provider appearance: meta | 71,903 (98.8%) |
| provider appearance: microsoft | 385 (0.53%) |
| provider appearance: alltheplaces | 291 (0.40%) |
| provider appearance: foursquare | 170 (0.23%) |
| provider appearance: pinmeto | 1 (0.001%) |

This is a **stronger and more precise** finding than Revision 1's "98.8% Meta, functionally Meta data" claim: it isn't just that Meta dominates — **not a single record in this AOI has independent cross-provider corroboration**. Every record is single-sourced. The Meta-dominance framing was directionally right; the "functionally Meta data" framing undersold how absolute the single-provider pattern actually is.

**Three explicit confidence policies** (unfiltered baseline + two thresholds, by canonical group — full table in `poi_audit_summary.json`'s `counts_by_group_multi_policy`):

| group | unfiltered | ≥0.3 | ≥0.6 |
|---|---:|---:|---:|
| commercial | 17,289 | 15,728 | 10,087 |
| retail | 15,434 | 13,477 | 7,719 |
| healthcare | 1,669 | 1,502 | 936 |
| industrial_logistics | 744 | 645 | 346 |
| *(unmapped)* | 28,699 | 24,967 | 14,236 |

**Reproducible precision proxy — Measured, computed on every record, no manual judgment**: fraction of records with website/phone/social present, by confidence band. `has_phone` (~89%) and `has_social` (~99%, driven by an auto-populated Facebook page link on nearly every Meta-sourced record) are both near-saturated and **not informative**. `has_website` (~40% overall) has real spread and shows a broadly consistent (not universal) **positive trend with confidence** — e.g. retail: 30.8% (<0.3) → 40.7% (0.3–0.6) → 53.0% (≥0.6); tourism: 25.9% → 32.8% → 58.2%; commercial_service: 30.9% → 55.3% → 64.8%. A few groups (commercial, education) are non-monotonic. Full table: `poi_audit_summary.json`'s `contact_info_proxy`.

**Manual/web-assisted spot check — Manual, n=16, seed 20260914, NOT statistically powered**: 8 `food_drink` + 8 `lodging` records, 4 high-confidence (≥0.7) and 4 low-confidence (<0.3) per category, each checked against live web search. Full record-by-record findings, now correctly parseable end-to-end by pandas (§2.7 fixed a malformed row that previously broke the file past line 10): `data/prototype/danang_hoian_halo/audit/manual_confidence_spot_check.csv`. Verdicts use a controlled 4-value vocabulary (`corroborated` / `corroborated_partial` / `not_corroborated` / `weak`), reported separately — `corroborated_partial` and `weak` are never merged into `corroborated`, since doing so has no defined basis and would overstate clean verification:

| | high confidence (≥0.7, n=8) | low confidence (<0.3, n=8) |
|---|---|---|
| `corroborated` (clearly a real, findable business) | 6/8 | **3/8** |
| `corroborated_partial` (real chain/entity, exact branch unconfirmed) | 1/8 | **2/8** |
| `not_corroborated` (no independent match found) | 1/8 | 2/8 |
| `weak` (a plausible but inexact name match only) | 0/8 | **1/8** |

**Corrected from Revision 2**, which reported the low-confidence column as 5/8 clearly-corroborated, 1/8 partial, 2/8 not-corroborated — a hand-typed miscount from before the CSV could be reliably parsed (§2.7). The corrected numbers show a **larger** gap between bands than Revision 2 claimed: only 3/8 (37.5%) low-confidence records are cleanly corroborated, vs. 6/8 (75%) high-confidence — not 5/8 (62.5%) vs. 75%. The qualitative direction (higher confidence corroborates more often) is unchanged and, if anything, better supported. Real exceptions remain in both directions: a **high**-confidence record (`Hanoi Center Hotel Apartment`, 0.861) could not be matched to any specific real listing, while a **low**-confidence record (`Pearl Villa Danang Beach`, 0.293) has its own dedicated website and multiple listings. The one clearly *unverifiable* low-confidence record (`Nhà trọ`, 0.043) is unverifiable because its "name" is the generic Vietnamese common noun for "boarding house," not a proper name — a data-quality issue confidence correctly flags, distinct from "business doesn't exist."

**Which groups the manual sample actually covers — Measured, and a correction to Revision 3's recommendation**

The n=16 manual sample is **8 `food_drink` + 8 `lodging` records and nothing else**. Mapped through `config/poi_taxonomy.yaml`'s `group` field, `food_drink` belongs to group **commercial** and `lodging` to group **tourism**. Measured leaf composition of those two groups in the evaluation AOI (n=72,750):

| group | leaf categories present | records | manual records | manual coverage of the group |
|---|---|---:|---:|---|
| `commercial` | `food_drink` only | 17,289 | 8 | the group's only leaf is sampled (4 high / 4 low band) |
| `tourism` | `lodging` 4,240 + `attraction_culture` 721 | 4,961 | 8 | **`lodging` only** — 85.5% of the group by record count; `attraction_culture` (14.5%) unsampled |
| `retail` | `retail_other`, `supermarket`, `convenience`, `mall`, `marketplace` | 15,434 | **0** | none |
| `commercial_service` | `financial_service` | 864 | **0** | none |
| `healthcare` | `clinic`, `pharmacy`, `hospital` | 1,669 | **0** | none |
| `education` | `school`, `early_childhood`, `higher_education` | 1,574 | **0** | none |

Revision 3 described the `≥0.3` recommendation for retail/tourism/commercial_service/healthcare as resting on "combined proxy + manual evidence." That was wrong for three of those four groups: **retail, commercial_service, and healthcare have no manual record at all**, and tourism's manual support covers only the `lodging` subtype. `food_drink` evidence says nothing about a clinic, a bank branch, or a supermarket, and is not generalized to them below.

**The `has_website` proxy measured at the ≥0.3 boundary itself** — Measured. The three-band table above compares `<0.3` / `0.3–0.6` / `≥0.6`; a `≥0.3` threshold is a decision at one boundary, so this collapses the two upper bands into the set the threshold would actually retain:

| group | `has_website`, n < 0.3 | `has_website`, n ≥ 0.3 | gap | n in the `<0.3` band |
|---|---:|---:|---:|---:|
| `commercial_service` | 30.9% | 60.6% | **+29.7 pts** | 97 |
| `tourism` | 25.9% | 51.0% | **+25.2 pts** | 398 |
| `retail` | 30.8% | 47.7% | **+16.9 pts** | 1,957 |
| `healthcare` | 26.3% | 37.7% | **+11.3 pts** | 167 |
| `education` | 34.7% | 45.1% | +10.4 pts | 75 |
| `commercial` | 18.8% | 23.6% | **+4.9 pts** | 1,561 |
| *(unmapped)* | 35.5% | 48.5% | +13.0 pts | 3,732 |

**Recommendation, per group, with evidence labelled precisely.** No single threshold is justified across all groups. Every recommendation below is **provisional**: the proxy is one weak signal (two of its three fields are saturated and uninformative), and where manual evidence exists it is n=8 per group — **not statistically powered**, and not a precision/recall estimate.

| group | evidence in hand | status |
|---|---|---|
| `retail` | website proxy only (+16.9 pts, `<0.3` band n=1,957 — the largest low-band sample of any group). **No manual records.** | **Provisional `≥0.3`, website-proxy-based only.** Not manually validated. |
| `commercial_service` | website proxy only (+29.7 pts, but `<0.3` band n=97). **No manual records.** | **Provisional `≥0.3`, website-proxy-based only.** Large measured gap on a small low-band sample; not manually validated. |
| `healthcare` | website proxy only (+11.3 pts — the weakest of the four, `<0.3` band n=167). **No manual records.** | **Provisional `≥0.3`, website-proxy-based only.** Weakest proxy support of the recommended groups; not manually validated. |
| `tourism` | website proxy (+25.2 pts) **plus partial manual support**: 8 `lodging` records (85.5% of the group by count), 3/4 high-band vs. 2/4 low-band cleanly corroborated. `attraction_culture` (14.5%) unsampled. | **Provisional `≥0.3`.** Manual support is **partial — `lodging` only**, and is not evidence about every tourism subtype. |
| `commercial` | website proxy is weak and non-monotonic across bands (18.8% → 14.9% → 28.5%; only +4.9 pts at the ≥0.3 boundary). Manual: 8 `food_drink` records — the group's only leaf — 3/4 high-band vs. 1/4 low-band cleanly corroborated. | **Unresolved.** The manual direction is supportive but n=4 per band; the automated proxy for this group does not corroborate it. No threshold recommended. |
| `education` | website proxy non-monotonic (34.7% → 48.2% → 44.3%), `<0.3` band n=75. **No manual records.** | **Unresolved.** No threshold recommended. |
| *(unmapped)* | proxy computable, but there is no canonical group to reason about. **No manual records.** | **Unresolved.** No threshold recommended. |

This whole recommendation is explicitly lower-confidence than the road/population findings in this report. It rests on a 16-record manual sample covering two groups and one proxy signal with known gaps — not a large-scale ground-truth comparison.

**Proximity-heuristic language, corrected**: all "matched" terminology has been renamed to make the heuristic explicit (`cross_source_proximity_heuristic`, not `cross_source_match`) and every category result now also reports `overture_records_per_osm_entity_near_it` — e.g. for `clinic`, 32 Overture records sit within 75 m of only 18 distinct OSM entities (**1.78 Overture records per matched OSM entity**), a concrete, visible warning against reading these counts as confirmed 1:1 entity matches.

### 2.6 Verify output integrity before reuse (P1, found in a second review of Revision 2) — **Fixed**

**The bug**: Revision 2's `derive_or_reuse()` (derived rasters/PBF) and `acquire_aoi_subset()` (Overture parquets) both decided whether to reuse an existing file by checking only the SIDECAR's metadata (parent checksum + transform; theme/type/release/bbox/schema) — never re-deriving the actual file's own checksum, row count, or schema. A file matching its own sidecar was trusted as correct; a file tampered with, truncated, or corrupted **after** the sidecar was written (with the sidecar left in place) would have been silently reused.

**The fix**:
- `derive_or_reuse()` (`src/ingestion/run_acquisition.py`) now, on every reuse candidate: recomputes the file's current bytes/sha256 and compares them against the sidecar's OWN recorded bytes/sha256 (not just parent_sha256/transform), and re-runs `validate_fn` against the current file. Any mismatch or revalidation failure discards the file and regenerates it — tested with a file corrupted after derivation (unchanged parent/transform) and with a validator that only starts rejecting a previously-accepted file on a later run (`tests/test_acquisition_provenance.py`).
- `acquire_aoi_subset()` / new `verify_output_integrity()` (`src/ingestion/acquire_overture.py`) does the same for Overture parquets: recomputes the file's actual sha256/bytes, actual row count (`SELECT count(*)`), and actual local column set (`DESCRIBE`), and compares each against the sidecar's own recorded values — sidecar metadata matching the request is necessary but no longer sufficient for reuse. Tested for byte-count mismatch, checksum mismatch with identical byte count, row-count mismatch, missing local columns, and an end-to-end corrupted-file-triggers-refetch case (5 new tests).
- In both cases, a failed integrity check is treated exactly like a stale sidecar: reject and regenerate/refetch, never silently trust.

This revision's manifest (§1) reflects every asset having passed this stronger check — all raw and derived assets were reused (bit-identical to Revision 2's), and all three Overture parquets passed full sha256/bytes/row-count/schema re-verification before being reused rather than refetched.

### 2.7 Manual evidence CSV repairs (P1, found in a second review) — **Fixed**

**The bug**: `manual_confidence_spot_check.csv` contained one row (`Chin Meshi 109 - JackPot BBQ`) with an unescaped `"` character inside an unquoted field. Python's `csv` module tolerated it (silently), but pandas' C parser — the parser this report's own summary numbers are computed with — threw `ParserError: Expected 9 fields in line 10, saw 10` and could not load the file past that row at all. This is why Revision 2's low-confidence-band verdict counts in §2.5 were wrong (typed by hand from a partial/misread view of the file, not computed from a successful parse): it reported 5/1/2 across three verdict categories; the actual file (once readable) has **four** distinct verdicts.

**The fix**: both CSVs are regenerated with Python's `csv.writer` (`csv.QUOTE_MINIMAL`, correct escaping throughout) — `scripts/regenerate_manual_confidence_csv.py`, `scripts/regenerate_road_inspection_csv.py`. Content is otherwise unchanged from the original manual/web-assisted review (same 16 and 10 records respectively). `tests/test_audit_artifacts.py` (4 new tests) loads both files with `pandas.read_csv` — the same parser that broke — and asserts exact row counts, exact column schemas, and a controlled verdict/method vocabulary, so a future malformed edit fails a test instead of silently corrupting a downstream count.

**Corrected low-confidence-band verdict counts** (n=8, was reported as 5/1/2 across three categories in Revision 2 — actual, computed programmatically from the regenerated CSV):

| verdict | count |
|---|---:|
| `corroborated` | 3 |
| `corroborated_partial` | 2 |
| `not_corroborated` | 2 |
| `weak` | 1 |

`corroborated_partial` and `weak` are **not** merged into `corroborated` — no such merge policy is defined, and doing so would overstate how many low-confidence records were cleanly verified. Read narrowly, only 3/8 (37.5%) low-confidence records were **cleanly** corroborated, vs. 6/8 (75%) high-confidence records (§2.5's high-confidence counts were already correct in Revision 2 and are unchanged: 6 corroborated / 1 corroborated_partial / 1 not_corroborated / 0 weak). This is a **larger** high-vs-low gap than Revision 2's incorrect 6/8-vs-5/8 framing implied — the qualitative direction (higher confidence corroborates more often) is unchanged and, if anything, better supported than before, but the effect size Revision 2 reported was wrong.

`unmatched_major_road_inspection.csv` is similarly regenerated: the two narrative/comment lines that were embedded in the CSV (breaking any strict row-count check) are removed from the file and folded into §3.4's prose below; every row now carries an explicit `inspection_method` (`direct` / `inferred` / `not_checked`) plus, for every `direct` row, a `source_url` and `checked_at_utc` (all five Overture-side and both OSM-side direct lookups were re-run against the live OSM API / Nominatim on 2026-09-14 as part of this fix, reproducing Revision 2's original findings exactly — same construction-corridor pattern, same tag values — with provenance now attached to each). See corrected counts in §3.4.

### 2.8 Coastal/water terminology correction (P2, found in a second review) — **Fixed**

**The bug**: Revision 2's §5.3 called this a "coastal/water-cell stratum" and its code named it `water_coastal_stratum`. It is neither complete nor coastal in the sense that name implies: it does not read `natural=coastline` (a line feature, not a closed polygon, and therefore invisible to this stratum), it does not construct an ocean/land mask, and it excludes the 22 water-related multipolygon relations this parser already knew it skips (§4.4) — so it both misses open-ocean/coastline cells entirely and undercounts polygon-mapped water.

**The fix**: renamed throughout code, JSON keys, and this report to `mapped_water_polygon_stratum` (`src/audit/population_audit.py::mapped_water_polygon_stratum`, was `water_coastal_stratum`; JSON key `mapped_water_polygon_stratum`, was `coastal_water_stratum`; cell classification `mapped_water_cell_count`/`mapped_water`, was `coastal_water_cell_count`/`coastal_water`). The function now returns an explicit `coverage_caveat` field stating exactly what it does and does not cover. No new external coastline/land-mask dataset was introduced (out of scope for this pass, per the review's own instruction not to add one "unless strictly necessary") — true coastal-cell analysis remains **unresolved** (§6), not fabricated from what's already on hand. See §5.3 for the (unchanged, correctly-labeled-now) numbers.

### 2.9 AOI/count reporting fixes (P2, found in a second review) — **Fixed**

**OSM duplicate rate, scope-matched**: Revision 2's headline duplicate rate (15 pairs / 8,524 pre-dedup POIs) was internally consistent but was NOT the evaluation-AOI number its surrounding "evaluation AOI" framing implied — both the numerator and denominator were acquisition-scope. This revision adds a genuinely evaluation-scope metric: POIs are clipped to `EVALUATION_AOI` **before** dedup is rerun on that clipped set (`src/audit/run_all_audits.py::run_poi`), so numerator and denominator share one scope end to end. Both metrics are now computed and labeled separately (`osm_duplicate_pair_count_acquisition_scope`/`_rate_acquisition_scope` vs. `..._evaluation_scope`) rather than reporting only one under an ambiguous name. See §4.3 for the corrected headline number: **15 / 8,190 ≈ 0.183%**.

**Review-sample description, computed programmatically**: Revision 2's §4.7 hand-typed "100 records (10 categories × up to 5 per source)" — the actual artifact (`poi_review_sample.csv`, after `park_recreation` was added to `REVIEW_SAMPLE_CATEGORIES`) contains **105** records across **11** requested categories, of which **10** have records from both sources and one (`transport_bus_stop`) has only 5 OSM records because Overture has no matching category in this AOI at all. This was verified by loading the actual CSV and computing `len(df)`, `df["category"].nunique()`, and a `category × source` pivot (not retyped by hand) — see §4.7.

### 2.10 Retrieval-time provenance correction (P2, found in a second review) — **Fixed**

See §1 above for the fix and the corrected claim: Revision 2's four raw-asset `retrieved_at_utc` values were labeled "real original download timestamps... recovered from filesystem mtimes," which overstated their evidentiary status — filesystem mtime is not proof of original retrieval time, and the sidecars behind those numbers did not even identify which asset they belonged to (`url: "backfilled-from-filesystem-mtime"`). `download_pinned()` (`src/ingestion/download.py`) now validates a sidecar's `url` against the asset's actual pinned URL before trusting its `retrieved_at_utc`, and falls back to an explicitly-labeled `filesystem_mtime_proxy` (never presented as a real timestamp) when no matching sidecar exists. `ManifestEntry` and every manifest entry now carry `retrieved_at_utc_method` (`download` / `filesystem_mtime_proxy` / `derived_at_utc` / `overture_sidecar`) so this distinction is visible in the manifest itself, not only in prose (`tests/test_download.py::test_reuse_with_sidecar_url_mismatch_falls_back_to_mtime_proxy`).

### 2.11 Manifest run status (P2, found in a second review) — **Fixed**

**The bug**: a failed acquisition run (e.g. `..._070811Z.json`, which hit the release-resolution bug and stopped) was distinguishable from a smaller-but-successful run only by counting entries — there was no field stating the run's outcome.

**The fix**: `RunManifest` (`src/ingestion/manifest.py`) now carries an explicit `status` (`in_progress` while entries are still being added, `complete` once `finalize()` is called) and `failure_reason`. `src/ingestion/run_acquisition.py::main()` wraps the whole acquisition run in a `try/except` that calls `manifest.mark_failed(...)` and re-raises on any exception, so a genuinely failed run's manifest is marked `failed` with a reason rather than merely looking incomplete (3 new tests in `tests/test_manifest.py`). This revision's manifest carries `status: "complete"`, `failure_reason: null`.

---

## 3. Road audit — OSM vs. Overture Transportation

Code: `src/roads/overture_transportation.py`, `src/roads/topology.py`, `src/audit/road_audit.py`. Both networks parsed independently; **never unioned**.

### 3.1 Total length by class (evaluation scope, metres) — Measured

| class | OSM | Overture |
|---|---:|---:|
| residential | 4,199,547 | 4,111,569 |
| service | 860,398 | 855,913 |
| track | 557,054 | 585,059 |
| tertiary | 496,026 | 462,488 |
| unclassified | 467,986 | 526,562 |
| secondary | 334,262 | 359,702 |
| primary | 216,504 | 222,752 |
| trunk | 175,902 | 202,127 |
| motorway | 84,896 | 98,017 |
| living_street | 40,114 | 42,615 |
| `*_link` classes (5 subtypes) | 33,207 | **0** |

**Total**: OSM 7,465,897 m, Overture 7,466,805 m — **0.01% difference**. Overture has zero `_link`-class segments in this AOI (ramps appear folded into base classes, not a coverage gap — see the OSM-only unmatched-sample inspection in §3.3).

### 3.2 Connectivity (evaluation scope; see §2.1 for the scope fix and halo-scope comparison) — Measured

| | OSM | Overture |
|---|---:|---:|
| connected components | 91 | 92 |
| largest component share | 99.56% | 99.59% |
| intersection/connector count (deg≥3) | 42,301 | 41,769 |

### 3.3 Geometric overlap (10 m buffer, evaluation scope) — Heuristic (proximity, not entity match)

- OSM matched within 10 m of Overture: **99.44%** (41,504 m / 7,465,897 m unmatched)
- Overture matched within 10 m of OSM: **99.52%** (35,640 m / 7,466,805 m unmatched)

### 3.4 Unmatched major-road samples — Manual inspection (not just coordinates)

2 OSM-only and 8 Overture-only major-road segments (majority-unmatched, `top_n=8`). Full inspection, as a clean machine-readable CSV with `inspection_method` (`direct`/`inferred`/`not_checked`), `source_url`, and `checked_at_utc` for every directly-inspected record (§2.7 fix): `data/prototype/danang_hoian_halo/audit/unmatched_major_road_inspection.csv`. Narrative summary (moved out of the CSV itself, §2.7):

- **Both OSM-only segments are real, currently-mapped roads**, looked up directly via the OSM API by way ID: `Cầu Văn Ly` (a named, access-restricted provincial bridge, `ref=ĐT.610B`) and an unnamed `secondary_link` ramp — consistent with Overture's observed lack of `_link`-class tracking in this AOI.
- The 8 Overture-only segments partition into **mutually exclusive** inspection outcomes that sum to 8 (read directly from `inspection_method` + `finding` in the CSV):

  | inspection outcome | count |
  |---|---:|
  | directly confirmed as construction (`highway=construction`) | **3 / 8** |
  | directly confirmed as **non**-construction — 1 × `highway=unclassified` (minor rural road, no construction tag), 1 × `highway=tertiary` (named expressway frontage/collector road) | **2 / 8** |
  | inferred by coordinate proximity to a directly-confirmed construction point, **not** independently re-queried | **2 / 8** |
  | not checked against any external source | **1 / 8** |
  | **total** | **8 / 8** |

  So **5 of 8 were directly reverse-geocoded** (Nominatim) — of which 3 are construction and 2 are not — and the other **3 of 8 were never directly, individually confirmed** (2 proximity-inferred, 1 unchecked). Neither the inferred nor the unchecked records are counted as confirmed construction anywhere in this report.

  Two prior miscounts are corrected here. Revision 2 reported "4 of 5 construction," a hand-typed figure from before the underlying CSV could be reliably parsed (§2.7). Revision 3's own follow-up sentence then labelled the not-directly-confirmed group "3 of 8" while listing four records under it (2 inferred + 1 tertiary + 1 unclassified), so its groups did not sum to 8; the table above replaces it.

  The construction corridor is the most common **directly confirmed** outcome (3 of the 5 directly checked), and the 2 proximity-inferred points sit on that same corridor. Stated as a bound rather than a claim: construction explains **at least 3 of 8** (directly confirmed) and **at most 5 of 8** (if both inferred points are in fact construction). It is a **partial**, not a complete, explanation for the Overture-only samples.

### 3.5 Recommendation — unchanged from Revision 1, now on firmer (consistently-scoped) evidence

**Retain OSM as the canonical road graph.** Near-identical total length (0.01% apart), near-identical evaluation-scope connectivity (0.03-point gap in largest-component share), and 99.4–99.5% mutual geometric overlap, now computed at consistent, matched spatial scope for both sources. OSM additionally carries transit-node, park-polygon, and `landuse=industrial` tagging Overture Transportation does not provide. **Overture Transportation confirmed as road QA/fallback only** — its OSM lineage (empirically confirmed by the overlap figures) means it cannot serve as an independent primary source.

---

## 4. POI audit — Overture Places vs. OSM

Code: `src/poi/overture_places.py`, `src/poi/osm_extract.py`, `src/poi/dedup.py`, `src/audit/poi_audit.py`. See §2.3 and §2.5 for the two P1 fixes from the first review affecting this section's headline numbers, and §2.7/§2.9 for this revision's evidence-CSV and duplicate-rate-scoping fixes.

### 4.1 Record counts by canonical group (evaluation AOI) — Measured

See §2.5's three-policy table; OSM total (deduplicated, fixed algorithm): **8,175** across evaluation AOI (vs. 8,078 under the old, over-aggressive dedup — the corrected algorithm retains 97 more real, distinct entities that the buggy node-node merging had incorrectly collapsed).

### 4.2 Missing name / category — Measured

| | OSM (deduped) | Overture |
|---|---:|---:|
| missing name | 24.7% | 0.0% |
| missing category (`canonical_category`) | 0.0% | 39.4% |

### 4.3 OSM duplicate rate — Measured, corrected (§2.3, scope-fixed §2.9)

**Evaluation-scope (preferred headline number, §2.9)**: POIs clipped to `EVALUATION_AOI` before dedup is rerun on that clipped set — **15 duplicate pairs / 8,190 pre-dedup POIs ≈ 0.183%**.

**Acquisition-scope (retained, separately labeled)**: dedup as originally run on the full acquisition-AOI POI set — **15 duplicate pairs / 8,524 pre-dedup POIs ≈ 0.176%**.

Both are a large improvement over the buggy algorithm (119 pairs / 1.40%, §2.3); the eval-scope number is the one that should be quoted as this report's headline duplicate rate going forward, since it matches the scope of every other §4 metric.

### 4.4 Multipolygon relation omissions — Measured (quantified, not assembled)

This parser does not assemble OSM multipolygon relations into geometry (only simple closed ways). Relations tagged with a relevant area/POI category **in this AOI** (`type=multipolygon` only, to avoid inflating the count with irrelevant relation types like routes/boundaries):

| category | omitted relation count |
|---|---:|
| `area:water_body` | 22 |
| `poi:park_recreation` | 3 |
| `poi:attraction_culture` | 3 |
| `area:park_area` | 1 |
| `area:industrial_site` | 1 |
| `poi:food_drink` | 1 |

**Completeness is explicitly NOT claimed for `park_recreation`, `industrial_logistics`, `attraction_culture`, or the mapped-water-polygon stratum (§5.3, renamed from "coastal/water" per §2.8 — it is not a coastal stratum)** — the water-body omission (22 relations) is the largest, and §5.3's stratum below should be read as an undercount of true water coverage, not a precise measurement. This affects `park_recreation`/`industrial_logistics`/`attraction_culture` counts only for whatever share of those categories in Vietnam happens to be relation-mapped rather than simple-way-mapped in OSM — not quantified further here.

### 4.5 Cross-source proximity heuristic — Heuristic (§2.5)

Selected categories (full table + `*_per_osm_entity_near_it` ratios: `poi_audit_summary.json`):

| category | OSM total | Overture total | Overture records per matched OSM entity |
|---|---:|---:|---:|
| `clinic` | 27 | 986 | 1.78 |
| `transport_bus_stop` | 789 | **0** | n/a |
| `retail_other` | 1,062 | 13,120 | 3.66 |

`transport_bus_stop` confirms OSM remains necessary for mapped transit nodes — Overture has no matching category at all in this AOI.

### 4.6 Spatial density (1 km grid, evaluation AOI, 1,260 cells, fully covering the AOI extent including empty cells) — Measured

| | OSM | Overture |
|---|---:|---:|
| cells with zero POIs | 70.9% | 43.4% |
| densest single cell | 756 | 2,576 |

### 4.7 Reproducible review sample — includes `park_recreation`, counts computed programmatically (§2.9)

**105 records** across **11 requested categories** (up to 5 per source per category, seed `20260914`), of which **10 categories have records from both sources**; `transport_bus_stop` has only 5 OSM records because Overture has no matching category in this AOI at all. These counts are read directly from the artifact (`len(df)`, `df["category"].nunique()`, a `category × source` pivot), not hand-typed — corrected from Revision 2's hand-typed "100 records (10 categories)," which underrepresented both totals. Full sample: `data/prototype/danang_hoian_halo/audit/poi_review_sample.csv`.

---

## 5. Population audit — WorldPop 2025 / WorldPop 2020 vs. GHS-POP 2020

Code: `src/audit/population_audit.py`. Both count rasters regridded onto a common 1 km EPSG:32649 grid using area-conserving `Resampling.sum`.

### 5.1 Totals (acquisition AOI) — Measured

| | WorldPop 2020 | GHS-POP 2020 | WorldPop 2025 |
|---|---:|---:|---:|
| total population | 1,752,534 | 1,731,453 | 1,818,527 |
| non-zero cell fraction | 100.0% | 73.2% | 100.0% |

Totals agree within 1.2%. WorldPop 2025 vs. 2020: +3.8% (internal consistency only — no independent same-epoch 2025 source exists in scope).

### 5.2 Conservation error, per source, on the actual AOI rasters — Measured

Revision 1 only tested conservation on a synthetic fixture. This revision computes native-grid (AOI-windowed, no resampling) vs. regridded-1km totals **for each of the three real source rasters actually used in this audit**:

| source | native total (AOI-windowed) | regridded total (1km) | relative error |
|---|---:|---:|---:|
| WorldPop 2020 | 1,751,492 | 1,752,534 | **+0.059%** |
| WorldPop 2025 | 1,817,444 | 1,818,527 | **+0.060%** |
| GHS-POP 2020 | 1,781,720 | 1,731,453 | **−2.82%** |

WorldPop's conservation is excellent (well under 0.1%). GHS-POP's −2.82% is real and larger — plausibly from reprojecting a Mollweide-native grid into UTM at a coarser common resolution, and/or edge-pixel handling differences between the AOI-window read and the regrid target's window. **This is disclosed as a real, moderate resampling artifact for GHS-POP, not hidden or averaged away.** (A first attempt at this check compared GHS-POP's *whole 1000km native tile* total against the AOI-only regridded total, producing a meaningless ~98% "error" from the extent mismatch alone — caught and fixed before this number was reported; `native_grid_total` now always windows to the AOI in the source's own CRS first, tested in `tests/test_population_conservation.py`.)

### 5.3 Mapped-water-polygon stratum — Measured, a real geometry-based stratum (renamed from "coastal/water", §2.8)

Revision 1 only had a WorldPop-density-based proxy stratification (self-referential, correctly flagged by the first review). Revision 2 added a stratum built from actual OSM water geometry (`config/poi_taxonomy.yaml area_categories.water_body`: `natural=water/bay/strait`, `waterway=riverbank/dock`) intersected with the 1 km grid (>10% cell-area water fraction = "mapped water"), but called it a "coastal/water" stratum — a second review correctly flagged that name as overclaiming: it does not read `natural=coastline`, does not construct an ocean/land mask, and excludes the 22 water-related multipolygon relations already known to be skipped (§4.4). **It covers only the closed OSM water polygons this parser actually captures** — renamed `mapped_water_polygon_stratum` throughout code and this report; the JSON output now carries an explicit `coverage_caveat` field stating this. A true coastal/land-mask analysis remains unresolved (§6) — no new external dataset was introduced to manufacture a complete-looking answer.

| | cell count | WorldPop total | GHS-POP total | median rel. diff |
|---|---:|---:|---:|---:|
| mapped water | 41 | 56,072 | 54,140 | 30.0% |
| non-water | 1,221 | 1,696,461 | 1,660,223 | 25.9% |

Mapped-water cells show *somewhat* higher disagreement than non-water cells, consistent with both products struggling more at land/water boundaries — but the gap is modest, and **this stratum itself is a known undercount** of true water coverage, now on two counts: it excludes `natural=coastline` and any land/ocean mask entirely (no closed polygon exists to intersect), and it excludes the 22 water-body relations already known to be skipped (§4.4) — so some genuinely coastal/water cells are likely classified as "non-water" here, and true open-water/coastline cells outside any mapped polygon are invisible to this stratum altogether.

### 5.4 Allocation agreement (2020 same-epoch pair) — Measured

- Spearman rank correlation: **0.970** (p<0.001, n=1,262)
- Median relative difference: 25.9% (2.2% of cells near-zero-denominator, excluded per `safe_relative_difference`)
- By WorldPop-density proxy stratum: dense_urban 14.7%, peri_urban 16.7%, sparse 36.5% median relative difference — agreement best in dense urban cells, as in Revision 1.

### 5.5 Interpretation — unchanged conclusion, now with real per-source conservation evidence

Neither raster is ground truth. The 2020 pair shows strong rank agreement with a known, now-quantified-per-source allocation/conservation profile. Static residential-population rasters do not represent daytime, tourism-season, or mobility population anywhere in this AOI, mapped-water-adjacent areas included — and, per §5.3, true coastal/open-water cells outside a mapped polygon are not distinguished at all by this audit.

---

## 6. Remaining unresolved issues (honest accounting)

1. **Per-group Overture confidence threshold** is **not fully resolved for any group** (§2.5). `retail`, `commercial_service`, and `healthcare` carry a **provisional `≥0.3` backed by the website proxy only — zero manual records exist for any of them**. `tourism` carries a provisional `≥0.3` backed by the proxy plus manual evidence covering the `lodging` subtype only (85.5% of the group by count; `attraction_culture` unsampled), which is **partial**, not validation of every tourism subtype. `commercial`, `education`, and the unmapped bucket have **no threshold recommendation** — stated explicitly, not defaulted to a number. The manual sample contains `food_drink` and `lodging` records and nothing else; `food_drink` evidence is not transferred to retail, healthcare, or commercial_service anywhere in this report.
2. **GHS-POP's −2.82% conservation error** is disclosed but not fully explained (edge-pixel vs. reprojection-distortion contribution not separated).
3. **3 of the 8 Overture-only unmatched-major-road samples were not directly, individually reverse-geocoded** (2 inferred by proximity to a confirmed point, 1 not queried at all), and of the 5 that were, 2 turned out **not** to be construction — so construction is confirmed for 3 of 8 and possible for at most 5 of 8. §3.4 gives the full mutually-exclusive breakdown summing to 8, with `inspection_method` machine-readable in the CSV itself (§2.7).
4. **Multipolygon relation assembly remains unimplemented** — omissions are counted (§4.4), not filled in. `park_recreation`, `industrial_logistics`, and `attraction_culture` completeness is explicitly not claimed; the mapped-water-polygon stratum (§5.3) is a known undercount.
5. **WorldPop's OSM/Microsoft-derived-product license ambiguity** (flagged in Revision 1) remains unresolved — not something this audit can close.
6. **No rural/mountain coverage check** has been run (recommended, not executed, per original scope).
7. **The manual confidence spot check (n=16) is not statistically powered** — it supports the qualitative direction of the automated `has_website` proxy but should not be treated as a precise precision/recall estimate.
8. **True coastal/open-water-cell analysis remains unresolved** (§2.8, §5.3) — the mapped-water-polygon stratum covers only closed OSM water polygons; no `natural=coastline`-based or land-mask-based coastal analysis has been implemented, and none is planned in this pass without a clear need for it.
9. **GHS-POP's conservation error and the mapped-water stratum's disagreement figures are not yet decomposed against each other** — whether GHS-POP's larger conservation error is itself concentrated in or near mapped-water cells (plausible, given both involve edge/boundary effects) has not been checked.

---

## 7. Source-role decisions (re-evaluated from corrected evidence, not carried over)

None of the P1/P2 fixes in this revision (§2.6–2.11) changed any underlying measured value used by §3–§5's headline connectivity/length/conservation numbers — they corrected reuse-safety, evidence-file integrity, terminology, metric scoping, and provenance labeling. The one number that materially changed is the low-confidence manual-spot-check corroboration rate (§2.5, §2.7: 3/8 clean corroboration, not 5/8), which makes the case for treating the manual evidence as directionally-supportive-but-imprecise even stronger than Revision 2 stated. Decisions below are therefore unchanged from Revision 2, re-stated here for completeness rather than re-derived from scratch:

| Role | Decision | Basis |
|---|---|---|
| **Overture Places — primary commercial POI** | **CONDITIONAL GO** (condition tightened vs. Revision 1) | §2.5: zero multi-provider corroboration anywhere in this AOI (stronger single-source-dependency finding than Revision 1's "98.8% Meta"). No blanket confidence threshold is supported. A **provisional** `≥0.3` applies to `retail`, `commercial_service`, and `healthcare` on the **website proxy alone — none of these three groups has a single manual record**; and to `tourism`, where the proxy is joined by **partial** manual support covering the `lodging` subtype only (85.5% of the group; `attraction_culture` unsampled). `commercial`, `education`, and the unmapped bucket remain **unresolved, not threshold-filtered**. The n=16 manual sample (`food_drink` + `lodging` only) is not statistically powered and is never generalized to groups it did not sample. |
| **OSM — complementary POI source + primary road graph** | **GO** | Corrected, scope-matched duplicate rate (0.183% evaluation-scope, §4.3) is low; only source with mapped transit nodes (§4.5), and `park_area`/`industrial_site` capture (with quantified relation omissions, §4.4); road evidence in §3.5. |
| **Overture Transportation — road QA/fallback** | **GO** (QA/fallback role only) | §3: consistent-scope connectivity gap of 0.03 points, 0.01% length difference, 99.4–99.5% overlap, plus a concretely inspected explanation for the majority (not all) of the remaining unmatched-major-road samples (§3.4, corrected 3/5-construction count). Not GO as an independent primary source — OSM lineage confirmed empirically. |
| **WorldPop 2025 — primary population layer** | **CONDITIONAL GO** | Excellent conservation (+0.06%, §5.2), plausible growth trend, but no independent same-epoch validation exists in scope — carry that caveat in feature metadata. |
| **WorldPop 2020 vs. GHS-POP 2020 — same-epoch validation pair** | **GO** (as a validation method) | Totals agree within 1.2%, rank correlation 0.97, agreement best in dense urban and (moderately) worse in mapped-water cells (§5.3, a real-but-partial-coverage stratum, correctly named now) — a defensible basis for WorldPop as primary with quantified uncertainty on both allocation (§5.4) and conservation (§5.2). |

---

## 8. Verification performed before this handoff

```
$ git diff --check
(no output -- no whitespace-conflict-marker issues)

$ python -m compileall -q src tests scripts
(no output -- all files compile)

$ python -m pytest tests/ -v
91 passed in under 3s (was 76 at the end of Revision 2; 15 new tests address
this review's required coverage: derived-asset corruption/revalidation-on-
reuse, Overture parquet corruption/checksum/row-count/schema mismatch and an
end-to-end refetch-on-corruption case, download sidecar-url-mismatch ->
mtime-proxy fallback, manifest status/failure_reason, and the manual-CSV
schema/vocabulary/count checks)

$ shasum -a 256 against every entry in the new authoritative manifest
all 11 entries verified matching (raw assets matched their pinned
expected_sha256; derived/Overture assets matched their own recorded sha256
-- see data/manifests/source_manifest_20260914T075515Z.json; all reused
bit-identical to Revision 2's files, now under the stronger integrity check
in §2.6)

$ shasum -a 256 docs/architecture.md
bd9b5ab71e95e75705676ecf00e8532584fec1ec11e9c9e9a12915c1164cfa15
(matches the SHA-256 recorded before this revision started; `git status
--short docs/architecture.md` also reports no changes)
```

---

## 9. Reproduction

```bash
# Environment (one-time)
brew install gdal osmium-tool
uv venv .venv --python 3.12 && source .venv/bin/activate
uv pip install -e ".[dev]"

# Acquisition (idempotent -- reuses any file whose checksum/parent/transform
# AND revalidation still match; refuses and regenerates/refetches anything
# that doesn't, per §2.6). Writes a new manifest with status "complete", or
# "failed" with a reason if any step raises.
#
# The Overture release is a REQUIRED, explicit choice -- there is no implicit
# "latest" mode (§2.2). This exact command reproduces the audited run:
python -m src.ingestion.run_acquisition --overture-release 2026-08-19.0

# To deliberately acquire a NEWER Overture release instead (not a
# reproduction of this report -- the resolved release is recorded in the
# new run manifest):
#   python -m src.ingestion.run_acquisition --resolve-latest

# Audits (writes JSON/CSV summaries under data/prototype/danang_hoian_halo/audit/)
python -m src.audit.run_all_audits

# Tests
python -m pytest tests/ -v
```

Manifest for this revision: `data/manifests/source_manifest_20260914T075515Z.json` (`status: "complete"`). Audit artifacts: `data/prototype/danang_hoian_halo/audit/{poi,road,population}_audit_summary.json`, `poi_review_sample.csv`, `poi_density_grid_{osm,overture}.csv`, `osm_poi_duplicate_pairs.csv`, `manual_confidence_spot_check.csv`, `unmatched_major_road_inspection.csv` (the last two regenerated by `scripts/regenerate_manual_confidence_csv.py` / `scripts/regenerate_road_inspection_csv.py`, §2.7).

**Next smallest validation step** (unchanged): a rural/mountain coverage check outside this coastal-urban corridor, to test whether these conclusions generalize to Vietnam's sparser interior before any nationwide commitment.

---

## 10. Closeout

**Status: CLOSED.** This artifact is the completed Gate 1 source-validation deliverable. Gate 2 (spatial-unit evaluation) may proceed against the source roles in §7.

### What closing means, and what it does not

Closed means every defect raised against this report across three independent review rounds has been fixed **in code, data, and evidence** — not in report language alone — and re-verified. It does **not** mean every source question about Vietnam is answered. The nine items in §6 remain genuinely open and are deliberately carried forward as named limitations rather than resolved by assertion; two of them constrain Gate 2 directly:

- **§6.1 — Overture Places confidence thresholds.** No group has a fully-evidenced threshold. Gate 2 must not filter Overture Places by confidence when comparing spatial units; the provisional `≥0.3` in §2.5/§7 is a Gate 3 feature-layer decision, not a Gate 2 input policy, and applying it unevenly across candidates would confound the comparison.
- **§6.6 — no rural/mountain coverage check.** Every conclusion here comes from one coastal-urban corridor. Gate 2's `dong_thap_rural` and `mu_cang_chai` AOIs are the first data from Vietnam's sparser interior; if their source behaviour diverges materially from this corridor, §7's source roles must be re-opened before any nationwide commitment.

### Fix ledger across all four revisions

| Round | Findings | Status |
|---|---|---|
| Review 1 (of Revision 1) | 6 × P1 | Fixed in Revision 2 (§2.1–2.5) |
| Review 2 (of Revision 2) | 2 × P1, 5 × P2 | Fixed in Revision 3 (§2.6–2.11) |
| Review 3 (of Revision 3) | 3 findings: unpinned reproduction command, over-generalized manual evidence, road-inspection arithmetic | Fixed in Revision 4 (§2.2, §2.5, §3.4) |

### Verification for this closeout

```
$ python -m pytest tests/ -v
101 passed  (was 91 at the end of Revision 3; +10 new tests, no test
             removed, skipped, or weakened -- breakdown below)

$ python -m compileall -q src tests
(no output -- all files compile)

$ git diff --check
(no output -- no whitespace/conflict-marker issues)

$ manifest re-verification: data/manifests/source_manifest_20260914T075515Z.json
all 11 entries re-hashed against the files currently on disk -- every
sha256 and byte count matches; every derived entry's parent_sha256 still
matches its parent entry's sha256 in the same manifest; every Overture
entry's release is 2026-08-19.0

$ shasum -a 256 docs/architecture.md
bd9b5ab71e95e75705676ecf00e8532584fec1ec11e9c9e9a12915c1164cfa15
(unchanged; `git status --short docs/architecture.md` reports no changes)
```

**Accounting for 91 → 101**: exactly 10 tests were added and none were removed, skipped, or weakened.

| file | new tests | what they pin |
|---|---:|---|
| `tests/test_release_cli_contract.py` (new file) | 8 | Pinned-release pass-through; a bare invocation is rejected (exit 2); `--resolve-latest` as the only path to live resolution; the two flags are mutually exclusive; the direct-call `ValueError` guard for a hand-built `Namespace`; the shared `add_release_args` contract applied to an arbitrary parser; and **two tests that read this report's own §9 command** and assert it both parses and pins `2026-08-19.0`, plus that no unpinned invocation appears anywhere in the report — so the report and the CLI cannot drift apart. |
| `tests/test_audit_artifacts.py` | 2 | §3.4's four inspection outcomes are mutually exclusive and sum to 8 (3 confirmed construction / 2 confirmed non-construction / 2 inferred / 1 unchecked), with the non-construction pair being one `unclassified` and one `tertiary`; and the manual sample contains only `food_drink` and `lodging`, 8 each, 4 per band — so no future edit can quietly widen its apparent reach into retail, healthcare, or commercial_service. |

These tests are network-free and run against artifacts already in the repository.

No audit code, audit output, or measured number was modified in this pass. The only source change is the CLI argument contract in `src/ingestion/run_acquisition.py` and `src/ingestion/acquire_overture.py`; no acquisition was re-run and no asset was re-downloaded (§2.2 explains why that was neither needed nor desirable for an argument-handling change).
