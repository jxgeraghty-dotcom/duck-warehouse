"""Shared pytest fixtures.

The ``built_project`` fixture stands up a *complete, isolated* warehouse in a
temp directory (freshly generated seeds + full build) so the data tests below
run against exactly what a user gets from ``dw build --generate``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from warehouse.project import load_project
from warehouse.runner import Warehouse
from warehouse.seeds import generate_seeds

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def project():
    """The real project config, used for fast (no-DB) parsing/templating tests."""

    return load_project(ROOT / "dw.yaml")


@pytest.fixture(scope="session")
def built_project(tmp_path_factory):
    """A fully built warehouse in an isolated temp dir. Returns the Project."""

    tmp = tmp_path_factory.mktemp("warehouse")
    proj = load_project(ROOT / "dw.yaml")
    # Redirect all writable paths into the temp dir; keep models where they are.
    proj.database = tmp / "test.duckdb"
    proj.seeds_dir = tmp / "seeds"
    proj.exports_dir = tmp / "exports"
    proj.reports_dir = tmp / "reports"

    generate_seeds(proj, seed=7)
    with Warehouse(proj) as wh:
        wh.seed()
        wh.run()
    return proj
