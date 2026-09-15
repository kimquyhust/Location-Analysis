# Gate 2 — administrative-candidate qualification record

_Assessed 2026-09-14 against the qualification rules in [`spatial_unit_decision.md`](spatial_unit_decision.md) ("Administrative-source qualification"). Every finding below was produced by querying or downloading the source, not by repeating a prior review's conclusion._

## Verdict

**`blocked`.** No qualifying post-1-July-2025 nationwide commune/ward/special-zone package was found. `config/gate2.yaml` keeps `candidates.administrative.enabled: false`, and the Gate 2 comparison covers **two families (square and H3), not three**. This is stated as an incomplete comparison wherever Gate 2 results are reported.

The requirement is a licensed nationwide package of the current **3,321** commune-level units carrying **official unit codes**. Three candidate sources were tested against it.

## Source 1 — OCHA COD-AB, Viet Nam Subnational Administrative Boundaries

Checked by querying the HDX package API and downloading and unpacking the unit listing itself.

| Field | Finding |
|---|---|
| Package | `cod-ab-vnm`, "Viet Nam - Subnational Administrative Boundaries", version **v02** |
| Licence | CC BY-IGO — commercial reuse permitted with attribution |
| Vintage | Reviewed, validated, and last edited **25 September 2025** — comfortably post-reform |
| Levels present | **ADM0 and ADM1 only.** The package description states "structured into 1 level: Admin 1: 34 Province" |
| Verified unit count | Downloaded `vnm_admin_boundaries.xlsx` (40,979 bytes, sha256 `a0457a9924822f938aa81c32cfeb818141e9a8103f36803229dff6827f0dff93`) and read its four worksheets directly: `vnm_admin0` = 1 unit, `vnm_admin1` = **34 provinces** with `adm1_pcode` values (`VN91`, `VN24`, …), `vnm_adminlines`, `vnm_adminpoints` = 34 points. **No ADM2, ADM3, or commune/ward sheet exists.** |
| Bulk access | GDB 12,405,269 B / SHP 36,852,707 B / GeoJSON 28,415,237 B, all on HDX |

**Result: fails.** The vintage and licence are fine and the 34 provinces match the current system, but the package contains **no commune-level geometry at all**. It qualifies as a current **province** metadata source — which is what `config/data_sources.yaml` already records it as — and cannot serve as the Gate 2 administrative spatial unit.

## Source 2 — geoBoundaries current API

Queried `https://www.geoboundaries.org/api/current/gbOpen/VNM/ALL/` live.

| Boundary type | Year represented | Units | Licence |
|---|---:|---:|---|
| ADM0 | 2016 | 1 | CC BY 4.0 |
| ADM1 | **2008** | **64** | Public Domain |
| ADM2 | **2020** | **708** | CC BY 3.0 IGO |

**Result: fails.** No commune layer is returned at all, and both subnational layers predate the reform — ADM1 reports 64 units against the current 34 provinces, and ADM2 reports the 708 districts of a tier that no longer exists. Confirmed unchanged from the Gate 1 review. Usable only for historical QA, never as the current spatial key.

## Source 3 — Overture Divisions (the fallback named in `config/data_sources.yaml`)

Queried `theme=divisions/type=division_area` at release **2026-08-19.0** over a Vietnam-wide bbox.

| Check | Measured | Required | Pass |
|---|---|---|---|
| Commune-level unit count | **3,399** `subtype=locality`, `class=land` | 3,321 | **no** — 78 units over (+2.35%) |
| Official unit codes | None. `admin_level` is **NULL** for every locality; identity is an Overture UUID plus `region`, which is the province-level ISO 3166-2 code (`VN-HN`, `VN-SG`, …). The `division_area` schema has no commune code field. | official codes present | **no** |
| Authoritative lineage | **3,399 / 3,399 (100%) sourced from OpenStreetMap.** Crowd-sourced, not a government package. | authoritative | **no** |
| Uniform post-reform vintage | **234 of 3,399 (6.9%)** carry a source `update_time` before 2025-07-01; the full range is 2017-02-15 to 2026-07-23. The layer is a **mixed-vintage** snapshot. | effective on or after 2025-07-01 | **no** |
| Province level, for comparison | 34 `subtype=region`, `admin_level=1`, `class=land` — matches the current system | 34 | yes |
| Licence | ODbL-1.0 (OSM lineage) — commercial use permitted, with share-alike obligations on a publicly used derivative database | reusable | conditional |

**Result: fails on four of five rules.** The named wards are genuinely post-reform (`Phường Hoàn Kiếm`, `Phường Đống Đa` and similar merged wards appear), so this is the *closest* thing found to a current commune layer — but "closest" is not qualified. Adopting a 3,399-unit OSM-derived layer with no official codes and a 6.9% pre-reform tail as *the* administrative spatial unit would attach an authority to it that the data does not have, and the 78-unit discrepancy is not reconcilable without the official register to reconcile against.

## What this blocks, and what it does not

- **Blocked:** the administrative family in the Gate 2 comparison. No Gate 2 output claims a completed three-family comparison.
- **Not blocked:** current **province** context from the COD-AB v02 package (34 units, official `adm1_pcode` codes, CC BY-IGO, September 2025). That remains available for later contextual/normalisation work.
- **Not substituted:** no stale district layer, no geoBoundaries ADM2, no GADM, and no province polygon stands in for commune geometry anywhere in Gate 2.

## Next smallest action to unblock

Obtain the official commune-level register and geometry — the General Statistics Office / Ministry of Home Affairs 3,321-unit package with official codes, or a licensed redistribution of it — and record provider, effective date, unit count, codes, bulk URI, byte count, checksum, CRS, geometry validity, and commercial terms here. Until that exists, re-running Gate 2 adds no administrative evidence; only a new source does.

Reproduce these checks:

```bash
python -m src.spatial.qualify_admin
```
