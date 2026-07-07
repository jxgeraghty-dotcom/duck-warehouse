"""End-to-end tests: build the warehouse and assert the data is clean.

These prove the two claims the project makes: (1) the messy raw feed is actually
repaired by staging, and (2) every declared test passes on the built marts.
"""

from __future__ import annotations

import pytest

from warehouse.export import run_exports
from warehouse.runner import Warehouse
from warehouse.tests import load_all_tests, run_tests


@pytest.fixture(scope="module")
def wh(built_project):
    with Warehouse(built_project) as w:
        yield w


def _scalar(wh: Warehouse, sql: str):
    return wh.fetch(sql)[0][0]


# -- the headline test: everything the project declares must pass ----------

def test_all_declared_tests_pass(built_project):
    cases = load_all_tests(built_project)
    assert len(cases) >= 30
    with Warehouse(built_project) as w:
        results = run_tests(w, cases)
    failures = [f"{r.name}: {r.status} ({r.failures})" for r in results if r.status != "pass"]
    assert not failures, "tests failed: " + "; ".join(failures)


# -- staging repaired the injected messiness -------------------------------

def test_duplicate_key_is_deduped(wh):
    total = _scalar(wh, "SELECT count(*) FROM main.dim_security")
    eq001 = _scalar(wh, "SELECT count(*) FROM main.dim_security WHERE security_id = 'EQ001'")
    assert total == 40          # 41 raw rows -> 40 after de-dup
    assert eq001 == 1


def test_blank_asset_class_recovered_from_prefix(wh):
    ac = _scalar(wh, "SELECT asset_class FROM main.dim_security WHERE security_id = 'EQ007'")
    assert ac == "Equity"


def test_rating_normalised(wh):
    rating = _scalar(wh, "SELECT rating FROM main.dim_security WHERE security_id = 'CB003'")
    assert rating == "BBB"      # from a raw ' bbb '


def test_currency_upper_cased(wh):
    ccy = _scalar(wh, "SELECT currency FROM main.dim_security WHERE security_id = 'EQ010'")
    assert ccy == "EUR"         # from a raw 'eur' (EQ010 is a European equity)


def test_bad_prices_cleaned_to_null(wh):
    nulls = _scalar(wh, "SELECT count(*) FROM main.stg_prices WHERE close_price IS NULL")
    assert nulls == 2           # one negative + one blank in the raw feed


# -- modelling logic is correct --------------------------------------------

def test_portfolio_weights_sum_to_one(wh):
    worst = _scalar(wh, """
        SELECT max(abs(s - 1.0)) FROM (
            SELECT sum(weight) AS s FROM main.fct_portfolio_holdings
            GROUP BY account_id, as_of_date)
    """)
    assert worst < 1e-9


def test_benchmark_weights_sum_to_one(wh):
    worst = _scalar(wh, """
        SELECT max(abs(s - 1.0)) FROM (
            SELECT sum(weight) AS s FROM main.fct_benchmark_weights
            GROUP BY benchmark_id, as_of_date)
    """)
    assert worst < 1e-9


def test_asset_class_index_starts_at_base_100(wh):
    # the first row is the explicit base-100 anchor for every series
    first = wh.fetch("SELECT eq_index, credit_index, govt_index, cash_index "
                     "FROM main.mart_asset_class_prices ORDER BY as_of_date LIMIT 1")[0]
    assert all(abs(v - 100.0) < 1e-9 for v in first)


# -- exports produce the consumer-shaped files -----------------------------

def test_exports_written_with_expected_headers(built_project):
    with Warehouse(built_project) as w:
        written = run_exports(w)
    names = {spec.filename for spec, _ in written}
    assert {"security_master.csv", "compliance_portfolio.csv", "macro.csv"} <= names

    compliance = built_project.exports_dir / "compliance_portfolio.csv"
    header = compliance.read_text(encoding="utf-8").splitlines()[0]
    # matches the guideline engine's portfolio.csv schema
    assert header.split(",") == [
        "security_id", "issuer", "sector", "asset_class",
        "market_value", "rating", "duration", "currency",
    ]
