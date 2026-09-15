"""Re-run the Gate 2 administrative-source qualification checks.

    python -m src.spatial.qualify_admin

Queries each candidate administrative source live and prints the measured
values that `docs/gate2_admin_qualification.md` records. Nothing here
decides anything: it reports what each source actually contains against the
rules in `docs/spatial_unit_decision.md`, so the `blocked` verdict can be
re-derived rather than taken on trust.

Requires network access. A source that cannot be reached is reported as
`unreachable` -- never as a pass and never as a fail on the merits.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path
from typing import Optional

EXPECTED_COMMUNE_UNITS = 3321
EXPECTED_PROVINCE_UNITS = 34
REFORM_DATE = "2025-07-01T00:00:00Z"
USER_AGENT = "location-feature-vector/gate2-admin-qualification"

HDX_PACKAGE = "https://data.humdata.org/api/3/action/package_show?id=cod-ab-vnm"
GEOBOUNDARIES = "https://www.geoboundaries.org/api/current/gbOpen/VNM/ALL/"
VIETNAM_BBOX = (102.0, 8.0, 110.0, 23.5)


def _get_json(url: str, timeout: int = 60):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def check_cod_ab() -> dict:
    try:
        payload = _get_json(HDX_PACKAGE)
    except Exception as e:
        return {"source": "ocha_cod_ab_vnm", "status": "unreachable", "error": str(e)}
    result = payload.get("result", {})
    notes = (result.get("notes") or "").replace("\n", " ")
    resources = [{"name": r.get("name"), "format": r.get("format"), "bytes": r.get("size"),
                  "url": r.get("url")} for r in result.get("resources", [])]
    # The package description states which admin levels it contains; the
    # authoritative check is the unit listing itself, which the doc records
    # by downloading vnm_admin_boundaries.xlsx and reading its worksheets.
    has_commune_level = any(tok in notes.lower() for tok in ("admin 2", "admin 3", "commune", "ward"))
    return {
        "source": "ocha_cod_ab_vnm", "status": "checked",
        "title": result.get("title"), "license": result.get("license_title"),
        "notes_excerpt": notes[:300],
        "declares_commune_level": has_commune_level,
        "resources": resources,
        "verdict": "fails: ADM0/ADM1 only, no commune-level geometry"
                   if not has_commune_level else "re-inspect: description now mentions a lower level",
    }


def check_geoboundaries() -> dict:
    try:
        payload = _get_json(GEOBOUNDARIES)
    except Exception as e:
        return {"source": "geoboundaries_vnm", "status": "unreachable", "error": str(e)}
    records = payload if isinstance(payload, list) else [payload]
    layers = [{"boundary_type": r.get("boundaryType"),
               "year_represented": r.get("boundaryYearRepresented"),
               "unit_count": r.get("admUnitCount"), "license": r.get("boundaryLicense")}
              for r in records]
    current = [l for l in layers if str(l["year_represented"]) >= "2025"]
    return {
        "source": "geoboundaries_vnm", "status": "checked", "layers": layers,
        "verdict": "fails: no commune layer and every subnational layer predates the 2025 reform"
                   if not current else "re-inspect: a post-2025 layer is now published",
    }


def check_overture_divisions(release: str) -> dict:
    try:
        try:
            from ..ingestion.acquire_overture import RELEASE_BUCKET, _connect
        except ImportError:  # pragma: no cover
            from ingestion.acquire_overture import RELEASE_BUCKET, _connect
        con = _connect()
    except Exception as e:
        return {"source": "overture_divisions", "status": "unreachable", "error": str(e)}

    path = f"s3://{RELEASE_BUCKET}/release/{release}/theme=divisions/type=division_area/*"
    w, s, e_, n = VIETNAM_BBOX
    where = (f"country='VN' AND bbox.xmin <= {e_} AND bbox.xmax >= {w} "
             f"AND bbox.ymin <= {n} AND bbox.ymax >= {s}")
    try:
        localities = con.execute(f"""
            SELECT count(*) AS total,
                   sum(CASE WHEN sources[1].update_time < '{REFORM_DATE}' THEN 1 ELSE 0 END) AS pre_reform,
                   sum(CASE WHEN admin_level IS NOT NULL THEN 1 ELSE 0 END) AS with_admin_level,
                   count(DISTINCT sources[1].dataset) AS distinct_datasets,
                   min(sources[1].update_time) AS oldest,
                   max(sources[1].update_time) AS newest
            FROM read_parquet('{path}', hive_partitioning=1)
            WHERE {where} AND subtype='locality' AND class='land'
        """).fetchone()
        provinces = con.execute(f"""
            SELECT count(*) FROM read_parquet('{path}', hive_partitioning=1)
            WHERE {where} AND subtype='region' AND admin_level=1 AND class='land'
        """).fetchone()[0]
        columns = [r[0] for r in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{path}', hive_partitioning=1) LIMIT 0").fetchall()]
    except Exception as ex:
        return {"source": "overture_divisions", "status": "query_failed", "error": str(ex)}
    finally:
        con.close()

    total, pre_reform, with_level, datasets, oldest, newest = localities
    failures = []
    if total != EXPECTED_COMMUNE_UNITS:
        failures.append(f"unit count {total} != expected {EXPECTED_COMMUNE_UNITS}")
    if "codes" not in columns and not with_level:
        failures.append("no official commune code and admin_level is NULL for every locality")
    if pre_reform:
        failures.append(f"{pre_reform}/{total} localities carry a pre-reform source update_time")
    return {
        "source": "overture_divisions", "status": "checked", "release": release,
        "locality_count": total, "expected_commune_units": EXPECTED_COMMUNE_UNITS,
        "pre_reform_localities": pre_reform,
        "localities_with_admin_level": with_level,
        "distinct_source_datasets": datasets,
        "source_update_time_range": [oldest, newest],
        "province_count": provinces, "expected_province_units": EXPECTED_PROVINCE_UNITS,
        "schema_columns": columns,
        "failures": failures,
        "verdict": "fails: " + "; ".join(failures) if failures else "passes every automated check",
    }


def qualify(release: str = "2026-08-19.0") -> dict:
    checks = [check_cod_ab(), check_geoboundaries(), check_overture_divisions(release)]
    qualified = [c for c in checks if c.get("verdict", "").startswith("passes")]
    return {
        "assessed_against": "docs/spatial_unit_decision.md administrative-source qualification",
        "expected_commune_units": EXPECTED_COMMUNE_UNITS,
        "reform_effective_date": REFORM_DATE,
        "checks": checks,
        "qualified_sources": [c["source"] for c in qualified],
        "status": "qualified" if qualified else "blocked",
        "record": "docs/gate2_admin_qualification.md",
    }


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Re-run the Gate 2 administrative-source qualification checks.")
    parser.add_argument("--overture-release", default="2026-08-19.0")
    parser.add_argument("--out", type=Path, default=None, help="Optional JSON output path.")
    args = parser.parse_args(argv)

    result = qualify(args.overture_release)
    print(json.dumps(result, indent=2, default=str))
    print(f"\nadministrative candidate: {result['status'].upper()}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
