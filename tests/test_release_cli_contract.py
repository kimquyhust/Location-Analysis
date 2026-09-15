"""The Overture release must be an explicit CLI choice.

A run that names no release used to silently resolve "whatever the bucket
holds right now", which makes an audited run unreproducible after the next
monthly release lands. These tests pin the CLI contract itself -- they
never touch the network or the S3 bucket.
"""

import argparse

import pytest

from ingestion.acquire_overture import add_release_args, release_from_args
from ingestion.run_acquisition import build_parser


AUDITED_RELEASE = "2026-08-19.0"


# --- src.ingestion.run_acquisition -----------------------------------------

def test_pinned_release_is_passed_through_verbatim():
    args = build_parser().parse_args(["--overture-release", AUDITED_RELEASE])
    assert args.overture_release == AUDITED_RELEASE
    assert args.resolve_latest is False
    assert release_from_args(args) == AUDITED_RELEASE


def test_no_release_argument_is_rejected():
    """Supplying neither flag must NOT silently select a changing release."""
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args([])
    assert exc.value.code == 2


def test_resolve_latest_is_an_explicitly_named_opt_in():
    args = build_parser().parse_args(["--resolve-latest"])
    assert args.resolve_latest is True
    # None is the sentinel acquire_aoi_subset() reads as live-resolution
    # mode; --resolve-latest is the only way to reach it.
    assert release_from_args(args) is None


def test_pinning_and_resolving_latest_are_mutually_exclusive():
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--overture-release", AUDITED_RELEASE, "--resolve-latest"])
    assert exc.value.code == 2


def test_reproduction_command_in_source_validation_report_parses():
    """The literal command docs/source_validation_report.md tells a reader to
    run must still be a valid invocation that pins the audited release."""
    from pathlib import Path

    report = Path("docs/source_validation_report.md").read_text()
    command = f"python -m src.ingestion.run_acquisition --overture-release {AUDITED_RELEASE}"
    assert command in report, "report must pin the audited release in its reproduction command"

    tokens = command.split()
    argv = tokens[tokens.index("src.ingestion.run_acquisition") + 1:]
    assert release_from_args(build_parser().parse_args(argv)) == AUDITED_RELEASE


def test_report_contains_no_unpinned_invocation():
    from pathlib import Path
    import re

    report = Path("docs/source_validation_report.md").read_text()
    for line in report.splitlines():
        stripped = line.strip()
        if not stripped.startswith("python -m src.ingestion.run_acquisition"):
            continue
        assert re.search(r"--overture-release|--resolve-latest", stripped), (
            f"unpinned acquisition invocation in the report: {stripped!r}"
        )


# --- the shared contract, as applied to any parser -------------------------

def test_release_from_args_raises_when_neither_field_is_set():
    """Direct call guard for a caller that built args without the parser."""
    args = argparse.Namespace(overture_release=None, resolve_latest=False)
    with pytest.raises(ValueError, match="No Overture release selected"):
        release_from_args(args)


def test_add_release_args_applies_the_same_contract_to_any_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bbox", nargs=4, type=float)
    add_release_args(parser)

    assert release_from_args(parser.parse_args(["--overture-release", "2026-07-23.0"])) == "2026-07-23.0"
    with pytest.raises(SystemExit):
        parser.parse_args(["--bbox", "1", "2", "3", "4"])
