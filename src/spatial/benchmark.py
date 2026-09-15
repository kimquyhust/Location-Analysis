"""Gate 2 instrumentation and artifact writing.

Every measured stage is wrapped in `Stage`, which records wall time, peak
RSS sampled during that stage (not the process high-water mark, which would
attribute one stage's memory to every later stage), row counts, and output
bytes. `RunContext` carries the identity every benchmark row must state:
run id, config hash, code version, source releases, and the software and
hardware the numbers were produced on.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import platform
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pandas as pd


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_config(*paths: Path) -> str:
    """One hash over the exact bytes of every config that steers the run."""
    h = hashlib.sha256()
    for p in sorted(paths, key=str):
        h.update(str(p).encode())
        h.update(Path(p).read_bytes())
    return h.hexdigest()


def code_version() -> str:
    """Commit plus a dirty marker. A Gate 2 run on an uncommitted tree is
    legitimate, but it must be labelled as such -- otherwise the recorded
    commit would imply a reproducibility guarantee the tree does not offer."""
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                               text=True, check=True).stdout.strip()
        return f"{commit}{'+dirty' if dirty else ''}"
    except Exception:
        return "unknown"


def environment() -> dict:
    import geopandas
    import numpy
    import rasterio
    import shapely

    try:
        import h3
        h3_version = h3.__version__
    except Exception:
        h3_version = "unknown"

    try:
        import psutil
        total_ram = psutil.virtual_memory().total
        cpus = psutil.cpu_count(logical=True)
    except Exception:
        total_ram, cpus = None, None

    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or platform.machine(),
        "cpu_count_logical": cpus,
        "total_ram_bytes": total_ram,
        "geopandas": geopandas.__version__,
        "shapely": shapely.__version__,
        "rasterio": rasterio.__version__,
        "numpy": numpy.__version__,
        "h3": h3_version,
        "pandas": pd.__version__,
    }


class _RssSampler(threading.Thread):
    """Samples this process's RSS while a stage runs. `resource.getrusage`
    only exposes a process-lifetime high-water mark, which would report the
    largest stage's memory for every stage after it."""

    def __init__(self, interval_s: float = 0.02):
        super().__init__(daemon=True)
        self.interval_s = interval_s
        self.peak_bytes = 0
        self._stop_event = threading.Event()

    def run(self) -> None:
        try:
            import psutil
            proc = psutil.Process()
        except Exception:
            return
        while not self._stop_event.is_set():
            try:
                self.peak_bytes = max(self.peak_bytes, proc.memory_info().rss)
            except Exception:
                return
            self._stop_event.wait(self.interval_s)

    def stop(self) -> int:
        self._stop_event.set()
        self.join(timeout=1.0)
        return self.peak_bytes


@dataclass
class RunContext:
    run_id: str
    config_hash: str
    code_version: str
    environment: dict
    source_releases: dict
    started_at_utc: str = field(default_factory=utc_now_iso)
    rows: list[dict] = field(default_factory=list)

    def stage(self, **labels) -> "Stage":
        return Stage(self, labels)


class Stage:
    """Context manager recording one measured stage as a `benchmark_runs` row.

    Usage:
        with ctx.stage(aoi_id=..., candidate_id=..., stage="generation") as s:
            units = candidate.units(...)
            s.rows = len(units)
    """

    def __init__(self, ctx: RunContext, labels: dict):
        self.ctx = ctx
        self.labels = labels
        self.rows: Optional[int] = None
        self.output_bytes: Optional[int] = None
        self.notes: str = ""
        self.status: str = "ok"
        self._sampler: Optional[_RssSampler] = None
        self._t0: float = 0.0
        self.wall_time_s: float = 0.0
        self.peak_rss_bytes: int = 0

    def __enter__(self) -> "Stage":
        self._sampler = _RssSampler()
        self._sampler.start()
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.wall_time_s = time.perf_counter() - self._t0
        self.peak_rss_bytes = self._sampler.stop() if self._sampler else 0
        if exc_type is not None:
            self.status = "failed"
            self.notes = f"{exc_type.__name__}: {exc}"
        self.ctx.rows.append({
            **self.labels,
            "run_id": self.ctx.run_id,
            "config_hash": self.ctx.config_hash,
            "code_version": self.ctx.code_version,
            "wall_time_s": self.wall_time_s,
            "peak_rss_bytes": int(self.peak_rss_bytes),
            "rows": self.rows,
            "output_bytes": self.output_bytes,
            "status": self.status,
            "notes": self.notes,
            "recorded_at_utc": utc_now_iso(),
            **{f"env_{k}": v for k, v in self.ctx.environment.items()},
            "source_releases": json.dumps(self.ctx.source_releases, sort_keys=True),
        })
        return False  # never swallow an exception


# ---------------------------------------------------------------------------
# Artifact writing
# ---------------------------------------------------------------------------

REQUIRED_SCHEMAS: dict[str, set[str]] = {
    "candidate_inventory": {
        "run_id", "aoi_id", "context", "candidate_id", "family", "role", "unit_id",
        "area_m2", "aoi_overlap_m2", "aoi_overlap_fraction", "land_fraction",
        "neighbor_count", "rep_lat", "rep_lon",
    },
    "candidate_metrics": {
        "run_id", "aoi_id", "context", "candidate_id", "family", "role", "metric",
        "dimension", "spatial_support", "value", "unit", "source_status", "notes",
    },
    "benchmark_runs": {
        "run_id", "config_hash", "code_version", "aoi_id", "candidate_id", "stage",
        "wall_time_s", "peak_rss_bytes", "rows", "output_bytes", "status",
        "source_releases",
    },
    "lookup_benchmark": {
        "run_id", "aoi_id", "candidate_id", "lookup_mode", "queries",
        "p50_latency_us", "p95_latency_us", "errors", "tie_cases", "correctness_checked",
        "correctness_failures", "notes",
    },
    "source_coverage": {
        "run_id", "aoi_id", "source_role", "source_id", "release", "license_id",
        "source_uri", "retrieved_at_utc", "sha256", "bytes", "crs", "bounds",
        "expected_assets", "present_assets", "expected_valid_pixels",
        "processed_valid_pixels", "processing_coverage", "ingest_status", "notes",
    },
}


class SchemaError(RuntimeError):
    pass


def write_table(df: pd.DataFrame, out_dir: Path, name: str) -> dict:
    """Validates `df` against the required schema for `name`, writes it as
    Parquet, and returns a manifest record. A missing required column is an
    error, not a silently-empty artifact."""
    required = REQUIRED_SCHEMAS.get(name)
    if required is None:
        raise SchemaError(f"no required schema registered for {name!r}")
    missing = required - set(df.columns)
    if missing:
        raise SchemaError(f"{name}.parquet is missing required columns: {sorted(missing)}")

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.parquet"
    df.to_parquet(path, index=False)
    return {"artifact": name, "path": str(path), "rows": int(len(df)),
            "bytes": path.stat().st_size, "sha256": sha256_of(path),
            "columns": sorted(df.columns)}


def write_run_manifest(out_dir: Path, ctx: RunContext, payload: dict) -> Path:
    path = out_dir / "run_manifest.json"
    body = {
        "gate": 2,
        "run_id": ctx.run_id,
        "config_hash": ctx.config_hash,
        "code_version": ctx.code_version,
        "started_at_utc": ctx.started_at_utc,
        "finished_at_utc": utc_now_iso(),
        "environment": ctx.environment,
        "source_releases": ctx.source_releases,
        **payload,
    }
    path.write_text(json.dumps(body, indent=2, sort_keys=True, default=str))
    return path
