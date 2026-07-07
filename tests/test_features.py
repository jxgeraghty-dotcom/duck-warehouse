"""Tests for the added capabilities: node selection, incremental models,
source freshness, source/severity tests, and the export handoff contract.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from warehouse.dag import discover_models, select_nodes
from warehouse.freshness import check_freshness
from warehouse.project import load_project
from warehouse.runner import Warehouse
from warehouse.seeds import generate_seeds
from warehouse.tests import TestCase, load_all_tests, run_tests

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def fresh_project(tmp_path):
    """A function-scoped isolated build (safe to mutate raw tables)."""

    proj = load_project(ROOT / "dw.yaml")
    proj.database = tmp_path / "t.duckdb"
    proj.seeds_dir = tmp_path / "seeds"
    proj.exports_dir = tmp_path / "exports"
    proj.reports_dir = tmp_path / "reports"
    generate_seeds(proj, seed=7)
    with Warehouse(proj) as wh:
        wh.seed()
        wh.run()
    return proj


# -- node selection --------------------------------------------------------

def test_select_descendants_and_ancestors(built_project):
    models = discover_models(built_project)
    desc = select_nodes(models, ["stg_prices+"], None)
    assert {"stg_prices", "int_security_returns", "fct_security_returns"} <= desc
    assert "stg_macro" not in desc

    anc = select_nodes(models, ["+mart_asset_class_prices"], None)
    assert {"mart_asset_class_prices", "fct_security_returns", "stg_prices",
            "dim_security"} <= anc
    assert "mart_macro_wide" not in anc


def test_exclude_removes_nodes(built_project):
    models = discover_models(built_project)
    kept = select_nodes(models, None, ["mart_data_quality"])
    assert "mart_data_quality" not in kept
    assert "dim_security" in kept


def test_unknown_selector_raises(built_project):
    models = discover_models(built_project)
    with pytest.raises(ValueError, match="matches no model"):
        select_nodes(models, ["nope+"], None)


# -- incremental materialisation ------------------------------------------

def test_incremental_appends_only_new_months(fresh_project):
    q = "SELECT count(*) FROM main.fct_security_returns"
    with Warehouse(fresh_project) as wh:
        before = wh.fetch(q)[0][0]

        # re-running with no new data is idempotent (append mode, nothing new)
        wh.run(select=["fct_security_returns"])
        assert wh.fetch(q)[0][0] == before

        # a new month arrives for one security -> exactly one new return row
        wh.con.execute(
            "INSERT INTO raw.prices "
            "SELECT '2026-07-31', security_id, close_price, price_currency "
            "FROM raw.prices WHERE as_of_date = '2026-06-30' AND security_id = 'EQ001'"
        )
        wh.run(select=["fct_security_returns"])
        assert wh.fetch(q)[0][0] == before + 1

        # running again does not double-count
        wh.run(select=["fct_security_returns"])
        assert wh.fetch(q)[0][0] == before + 1

        # full-refresh rebuilds from scratch (still includes the new month)
        wh.run(select=["fct_security_returns"], full_refresh=True)
        assert wh.fetch(q)[0][0] == before + 1


# -- failure isolation -------------------------------------------------------

def test_failed_model_skips_descendants(fresh_project):
    with Warehouse(fresh_project) as wh:
        wh.con.execute("DROP TABLE raw.prices")
        steps = wh.run()
    by_name = {s.name: s for s in steps}
    assert by_name["stg_prices"].status == "error"
    # everything downstream of the failure is skipped, not built on stale data
    for downstream in ("int_security_returns", "fct_security_returns",
                       "int_positions_valued", "mart_asset_class_prices"):
        assert by_name[downstream].status == "skip"
    assert "stg_prices" in by_name["int_security_returns"].error
    # unrelated branches of the DAG still build
    assert by_name["stg_macro"].status == "ok"
    assert by_name["mart_macro_wide"].status == "ok"


# -- source freshness ------------------------------------------------------

def test_freshness_reports_every_dated_source(built_project):
    with Warehouse(built_project) as wh:
        results = check_freshness(wh)
    assert len(results) == 6
    assert all(r.max_loaded_at == "2026-06-30" for r in results)
    assert all(r.age_days is not None for r in results)


# -- source-level + severity tests ----------------------------------------

def test_source_tests_are_loaded(built_project):
    cases = load_all_tests(built_project)
    source_tests = [c for c in cases if c.scope.startswith("source.")]
    assert len(source_tests) >= 5


def test_warn_severity_does_not_count_as_failure(built_project):
    warn_case = TestCase("w", "singular", "", "", "SELECT 1", severity="warn")
    err_case = TestCase("e", "singular", "", "", "SELECT 1", severity="error")
    with Warehouse(built_project) as wh:
        results = run_tests(wh, [warn_case, err_case])
    by_name = {r.name: r for r in results}
    assert by_name["w"].status == "warn"
    assert by_name["e"].status == "fail"


def test_store_failures_writes_a_csv(built_project, tmp_path):
    # point failures at a temp reports dir so we don't touch the real one
    built_project.reports_dir = tmp_path
    failing = TestCase("boom", "singular", "", "", "SELECT 42 AS x", severity="error")
    with Warehouse(built_project) as wh:
        results = run_tests(wh, [failing], store_failures=True)
    assert results[0].status == "fail"
    assert Path(results[0].stored_at).exists()


# -- export handoff contract ----------------------------------------------

def test_handoff_smoke_all_exports_load(built_project):
    spec = importlib.util.spec_from_file_location(
        "handoff_smoke", ROOT / "scripts" / "handoff_smoke.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses need the module registered
    spec.loader.exec_module(mod)
    results = mod.run_smoke(built_project)
    failed = [r.filename for r in results if not r.ok]
    assert not failed, f"exports failed contract: {failed}"
    assert len(results) == 8
