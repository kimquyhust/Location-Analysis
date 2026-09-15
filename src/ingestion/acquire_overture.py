"""Overture Places / Transportation acquisition for the acquisition AOI,
via DuckDB bbox-pushdown against the public Overture S3 release bucket
(https://docs.overturemaps.org/getting-data/duckdb/). No full theme file is
downloaded -- row groups outside the AOI bbox are pruned server-side.

Per COWORK_START_PROMPT.md, this is a coverage-audit / QA-fallback source,
not the primary POI/road source. Nested `sources`/`confidence`/taxonomy
fields are retained for audit -- do not build new logic on the deprecated
`categories` field; prefer `basic_category`/`taxonomy` mapping (verified
against the actual release schema at run time, not assumed).

Release provenance: an AOI subset parquet is only ever reused if a sidecar
`<path>.meta.json` exists AND its recorded release/bbox/schema match the
CURRENTLY requested release/bbox exactly. A stale file with a stale or
missing sidecar is refused for reuse (re-fetched), never silently relabeled
with whatever release happens to be current when the code runs next --
that mislabeling is exactly the bug this module was rewritten to close.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import duckdb

RELEASE_BUCKET = "overturemaps-us-west-2"
S3_REGION = "us-west-2"

REQUIRED_COLUMNS = {
    "places": {"place": {"id", "basic_category", "taxonomy", "confidence", "sources", "names", "bbox", "geometry", "websites", "phones", "socials"}},
    "transportation": {
        "segment": {"id", "subtype", "class", "connectors", "sources", "bbox", "geometry"},
        "connector": {"id", "sources", "bbox", "geometry"},
    },
}


class ReleaseResolutionError(RuntimeError):
    """Raised when the live Overture release cannot be determined. Never
    caught to silently fall back to a hardcoded release -- a stale
    fallback release is exactly how a subset gets mislabeled."""


class OvertureSchemaError(RuntimeError):
    """Raised when a theme/type's schema is missing columns the audits
    depend on -- fails loudly instead of silently producing nulls
    downstream."""


class OvertureProvenanceError(RuntimeError):
    """Raised when an existing AOI subset's sidecar metadata does not
    match the currently requested release/bbox/schema, and the caller has
    not explicitly allowed a re-fetch."""


def _connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(f"SET s3_region='{S3_REGION}';")
    return con


def resolve_release(con: Optional[duckdb.DuckDBPyConnection] = None) -> str:
    """List releases actually present in the bucket and return the lexically
    latest one. Raises ReleaseResolutionError on any failure -- the caller
    decides what to do (there is no silent hardcoded fallback here).

    Uses the S3 ListObjectsV2 REST API directly (delimiter=/ on the
    `release/` prefix, returning `CommonPrefixes`) rather than DuckDB's
    `glob()`: DuckDB's httpfs glob does not reliably do prefix-only
    "directory" listing against this bucket (`release/*/` returns zero
    rows even though the same prefix+delimiter query against the plain S3
    REST API returns the two real release folders) -- confirmed directly
    in this project's acquisition history, not assumed. A recursive
    `release/**` glob does work but would enumerate every parquet file in
    every release just to read folder names, which defeats the point of
    bbox-pushdown-only access.
    """
    import re
    import urllib.request

    url = f"https://{RELEASE_BUCKET}.s3.amazonaws.com/?list-type=2&prefix=release/&delimiter=/"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            body = resp.read().decode("utf-8")
    except Exception as e:
        raise ReleaseResolutionError(f"Failed to list releases via S3 REST API ({url}): {e}") from e

    prefixes = re.findall(r"<Prefix>release/([0-9]{4}-[0-9]{2}-[0-9]{2}\.[0-9]+)/</Prefix>", body)
    if not prefixes:
        raise ReleaseResolutionError(
            f"No releases found under s3://{RELEASE_BUCKET}/release/ -- REST listing "
            f"returned zero parseable release folders. Raw response (truncated): {body[:500]}"
        )
    return sorted(prefixes)[-1]


@dataclass
class OvertureAoiResult:
    theme: str
    type_: str
    release: str
    s3_path: str
    row_count: int
    output_path: Path
    schema_columns: list[str]


def _theme_path(theme: str, type_: str, release: str) -> str:
    return f"s3://{RELEASE_BUCKET}/release/{release}/theme={theme}/type={type_}/*"


def describe_schema(theme: str, type_: str, release: str, con: Optional[duckdb.DuckDBPyConnection] = None) -> list[tuple]:
    own_con = con is None
    con = con or _connect()
    path = _theme_path(theme, type_, release)
    try:
        return con.execute(f"DESCRIBE SELECT * FROM read_parquet('{path}', filename=true, hive_partitioning=1) LIMIT 0").fetchall()
    finally:
        if own_con:
            con.close()


def validate_schema(theme: str, type_: str, release: str, con: Optional[duckdb.DuckDBPyConnection] = None) -> list[str]:
    """Raises OvertureSchemaError if any column the audits depend on
    (REQUIRED_COLUMNS) is missing from the live schema. Returns the full
    column list on success."""
    cols = [row[0] for row in describe_schema(theme, type_, release, con=con)]
    required = REQUIRED_COLUMNS.get(theme, {}).get(type_, set())
    missing = required - set(cols)
    if missing:
        raise OvertureSchemaError(
            f"{theme}/{type_} release {release} is missing required columns: {sorted(missing)}. "
            f"Present columns: {sorted(cols)}."
        )
    return cols


def count_rows(path: Path, con: Optional[duckdb.DuckDBPyConnection] = None) -> int:
    own_con = con is None
    con = con or _connect()
    try:
        return con.execute(f"SELECT count(*) FROM read_parquet('{path}')").fetchone()[0]
    finally:
        if own_con:
            con.close()


def _sidecar_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".meta.json")


def write_sidecar(output_path: Path, meta: dict) -> Path:
    sidecar = _sidecar_path(output_path)
    with open(sidecar, "w") as f:
        json.dump(meta, f, indent=2)
    return sidecar


def read_sidecar(output_path: Path) -> Optional[dict]:
    sidecar = _sidecar_path(output_path)
    if not sidecar.exists():
        return None
    with open(sidecar) as f:
        return json.load(f)


def sidecar_matches_request(sidecar: dict, theme: str, type_: str, release: str, bbox: tuple, required_columns: set) -> tuple[bool, str]:
    """Returns (matches, reason). `reason` explains a mismatch for logging/
    error messages when it does not match."""
    if sidecar.get("theme") != theme or sidecar.get("type") != type_:
        return False, f"sidecar theme/type {sidecar.get('theme')}/{sidecar.get('type')} != requested {theme}/{type_}"
    if sidecar.get("release") != release:
        return False, f"sidecar release {sidecar.get('release')!r} != requested release {release!r}"
    if tuple(sidecar.get("bbox", ())) != tuple(bbox):
        return False, f"sidecar bbox {sidecar.get('bbox')} != requested bbox {bbox}"
    sidecar_cols = set(sidecar.get("schema_columns", []))
    missing = required_columns - sidecar_cols
    if missing:
        return False, f"sidecar schema is missing required columns: {sorted(missing)}"
    return True, "ok"


def fetch_aoi_subset(
    theme: str,
    type_: str,
    release: str,
    bbox: tuple,  # (west, south, east, north)
    output_path: Path,
    con: Optional[duckdb.DuckDBPyConnection] = None,
) -> OvertureAoiResult:
    """Fetch all records whose Overture `bbox` struct intersects `bbox`
    (bbox-pushdown so only relevant row groups are transferred), validate
    the live schema has every column the audits require, write as
    GeoParquet, and write a provenance sidecar recording exactly which
    release/bbox/schema produced this file.
    """
    own_con = con is None
    con = con or _connect()
    try:
        west, south, east, north = bbox
        path = _theme_path(theme, type_, release)
        schema_cols = validate_schema(theme, type_, release, con=con)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = output_path.with_suffix(output_path.suffix + ".partial")
        if tmp_path.exists():
            tmp_path.unlink()
        # `geometry` is already a native GEOMETRY column in Overture's GeoParquet
        # (verified against the live schema, not assumed from older WKB-blob docs)
        # -- select it as-is, DuckDB's parquet writer serializes it as GeoParquet.
        query = f"""
            COPY (
                SELECT *
                FROM read_parquet('{path}', filename=true, hive_partitioning=1)
                WHERE bbox.xmin <= {east} AND bbox.xmax >= {west}
                  AND bbox.ymin <= {north} AND bbox.ymax >= {south}
            ) TO '{tmp_path}' (FORMAT PARQUET)
        """
        con.execute(query)
        row_count = con.execute(f"SELECT count(*) FROM read_parquet('{tmp_path}')").fetchone()[0]
        tmp_path.replace(output_path)  # atomic: no partially-written file ever sits at output_path

        from .manifest import sha256_of, utc_now_iso
        write_sidecar(output_path, {
            "theme": theme, "type": type_, "release": release, "s3_path": path,
            "bbox": list(bbox), "row_count": row_count, "schema_columns": schema_cols,
            "sha256": sha256_of(output_path), "bytes": output_path.stat().st_size,
            "fetched_at_utc": utc_now_iso(),
        })

        return OvertureAoiResult(
            theme=theme, type_=type_, release=release, s3_path=path,
            row_count=row_count, output_path=output_path, schema_columns=schema_cols,
        )
    finally:
        if own_con:
            con.close()


def verify_output_integrity(output_path: Path, sidecar: dict, required_columns: set, con: duckdb.DuckDBPyConnection) -> tuple[bool, str]:
    """Checks the CURRENT on-disk file against what its OWN sidecar claims
    -- a sidecar whose theme/type/release/bbox/schema_columns match the
    request is not, by itself, proof the file wasn't truncated, corrupted,
    or replaced after the sidecar was written. This never trusts sidecar
    metadata alone: it re-derives the file's actual sha256/bytes/row_count/
    local schema and compares each against the sidecar's own recorded
    values (and, for schema, against `required_columns` directly)."""
    if not output_path.exists():
        return False, "output file does not exist"

    actual_bytes = output_path.stat().st_size
    if sidecar.get("bytes") != actual_bytes:
        return False, f"file bytes {actual_bytes} != sidecar bytes {sidecar.get('bytes')}"

    from .manifest import sha256_of
    actual_sha256 = sha256_of(output_path)
    if sidecar.get("sha256") != actual_sha256:
        return False, f"file sha256 {actual_sha256[:12]} != sidecar sha256 {str(sidecar.get('sha256'))[:12]}"

    try:
        actual_row_count = count_rows(output_path, con=con)
    except Exception as e:
        return False, f"could not read parquet to verify row count: {e}"
    if actual_row_count != sidecar.get("row_count"):
        return False, f"actual row_count {actual_row_count} != sidecar row_count {sidecar.get('row_count')}"

    try:
        local_cols = {row[0] for row in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{output_path}') LIMIT 0").fetchall()}
    except Exception as e:
        return False, f"could not read local parquet schema to verify required columns: {e}"
    missing = required_columns - local_cols
    if missing:
        return False, f"local file is missing required columns: {sorted(missing)}"

    return True, "ok"


def acquire_aoi_subset(
    theme: str,
    type_: str,
    bbox: tuple,
    output_path: Path,
    release: Optional[str] = None,
    con: Optional[duckdb.DuckDBPyConnection] = None,
) -> tuple[OvertureAoiResult, dict]:
    """Pinned mode (release given) vs. live-resolution mode (release=None,
    resolved now via resolve_release -- raises loudly if that fails, never
    falls back to a hardcoded release). Reuses `output_path` only if:
    1. a sidecar exists AND its recorded theme/type/release/bbox/schema
       match the current request exactly (`sidecar_matches_request`); AND
    2. the file's CURRENT sha256/bytes/row_count/local-schema still match
       what that same sidecar claims (`verify_output_integrity`) -- sidecar
       metadata is never trusted on its own.
    Any failure of either check re-fetches. Returns (result,
    provenance_dict) where provenance_dict always reflects the sidecar that
    actually backs the returned file (freshly written or pre-existing and
    fully re-verified).
    """
    own_con = con is None
    con = con or _connect()
    try:
        mode = "pinned" if release is not None else "live-resolved"
        resolved_release = release if release is not None else resolve_release(con)
        required_columns = REQUIRED_COLUMNS.get(theme, {}).get(type_, set())

        existing_sidecar = read_sidecar(output_path)
        if output_path.exists() and existing_sidecar is not None:
            matches, reason = sidecar_matches_request(existing_sidecar, theme, type_, resolved_release, bbox, required_columns)
            if matches:
                integrity_ok, integrity_reason = verify_output_integrity(output_path, existing_sidecar, required_columns, con)
                if integrity_ok:
                    row_count = existing_sidecar["row_count"]
                    result = OvertureAoiResult(
                        theme=theme, type_=type_, release=resolved_release,
                        s3_path=existing_sidecar["s3_path"], row_count=row_count,
                        output_path=output_path, schema_columns=existing_sidecar["schema_columns"],
                    )
                    provenance = dict(existing_sidecar, acquisition_mode=mode, reused=True)
                    return result, provenance
                # Sidecar metadata matched the request, but the file itself
                # does not match what that sidecar claims -- do not trust
                # it; refetch.
                reason = f"sidecar matched request but integrity check failed: {integrity_reason}"
            # Mismatch: refuse silent reuse, re-fetch under the currently
            # requested release/bbox instead.
            output_path.unlink()
            _sidecar_path(output_path).unlink(missing_ok=True)
        elif output_path.exists() and existing_sidecar is None:
            # A file with no provenance sidecar (e.g. produced before this
            # fix) cannot be trusted to be the currently-requested
            # release/bbox -- refuse reuse rather than guess.
            output_path.unlink()

        result = fetch_aoi_subset(theme, type_, resolved_release, bbox, output_path, con=con)
        sidecar = read_sidecar(output_path)
        provenance = dict(sidecar, acquisition_mode=mode, reused=False)
        return result, provenance
    finally:
        if own_con:
            con.close()


def add_release_args(parser) -> None:
    """Adds the explicit, mutually-exclusive, REQUIRED release contract to a
    CLI parser.

    There is deliberately no default. A command line that names no release
    is an error, not an implicit "latest" acquisition: an unpinned default
    silently binds a run to whatever release the bucket happens to hold at
    that moment, which is exactly what makes an audited run
    non-reproducible. Acquiring a *new* release must be opted into by name
    (`--resolve-latest`), so it is visible in shell history, CI configs, and
    reproduction instructions.
    """
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--overture-release", type=str, default=None, metavar="RELEASE",
        help="Pin an exact Overture release (e.g. 2026-08-19.0). Use this to reproduce an audited run.",
    )
    group.add_argument(
        "--resolve-latest", action="store_true",
        help="Opt in to acquiring whatever release is currently latest in the bucket. "
             "Not reproducible by itself -- record the resolved release from the run manifest.",
    )


def release_from_args(args) -> Optional[str]:
    """Maps the parsed release contract onto `acquire_aoi_subset`'s
    `release` parameter: an exact string for pinned mode, or None to
    live-resolve. `--resolve-latest` is the ONLY way to reach None."""
    if args.overture_release is not None:
        return args.overture_release
    if getattr(args, "resolve_latest", False):
        return None
    raise ValueError(
        "No Overture release selected. Pass --overture-release RELEASE to pin an "
        "exact release, or --resolve-latest to explicitly acquire a new one."
    )


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Fetch Overture Places/Transportation AOI subsets.")
    parser.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/prototype/danang_hoian_halo"))
    add_release_args(parser)
    args = parser.parse_args()
    release = release_from_args(args)

    con = _connect()
    results = []
    for theme, type_, out_name in [
        ("places", "place", "overture-places.parquet"),
        ("transportation", "segment", "overture-transportation-segments.parquet"),
        ("transportation", "connector", "overture-transportation-connectors.parquet"),
    ]:
        res, provenance = acquire_aoi_subset(theme, type_, tuple(args.bbox), args.out_dir / out_name, release=release, con=con)
        print(f"{theme}/{type_}: {res.row_count} rows, release={res.release}, reused={provenance['reused']} -> {res.output_path}")
        results.append(res)

    summary = {
        "bbox": args.bbox,
        "results": [
            {"theme": r.theme, "type": r.type_, "release": r.release, "row_count": r.row_count, "path": str(r.output_path), "s3_path": r.s3_path}
            for r in results
        ],
    }
    with open(args.out_dir / "overture-acquisition-summary.json", "w") as f:
        json.dump(summary, f, indent=2)


if __name__ == "__main__":
    main()
