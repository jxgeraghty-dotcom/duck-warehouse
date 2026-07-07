"""Generate the raw seed CSVs — the simulated upstream feeds.

The data is deliberately *messy* so the staging layer has something real to do
and the tests have something real to prove: duplicate keys, stray whitespace, a
blank asset class, mixed-case ratings/currencies, a negative price, a missing
price, and benchmark weights that do not quite sum to one. Every one of these is
repaired by a specific staging transformation, and a test then asserts the
repair worked. Generation is fully deterministic (fixed RNG seed) so the CSVs
are reproducible and diff-friendly in git.
"""

from __future__ import annotations

import csv
import random
from datetime import date
from pathlib import Path

from warehouse.project import Project

# --- universe definition ------------------------------------------------

_SECTORS = ["Technology", "Financials", "Health Care", "Energy", "Industrials", "Consumer"]
_REGIONS = ["North America", "Europe", "Asia Pacific"]
_REGION_CCY = {"North America": "USD", "Europe": "EUR", "Asia Pacific": "JPY"}
_CREDIT_RATINGS = ["AAA", "AA", "A", "BBB", "BB", "B"]

_FACTORS = [
    "EQ_MARKET", "EQ_SIZE", "EQ_VALUE", "EQ_MOMENTUM", "EQ_QUALITY",
    "RATE_LEVEL", "RATE_SLOPE", "CREDIT_IG", "CREDIT_HY",
]
_MACRO_SERIES = ["UST_10Y", "UST_2Y", "IG_OAS", "HY_OAS", "TBILL_3M", "CPI_YOY"]
_FX_CCYS = ["USD", "EUR", "GBP", "JPY"]

N_EQUITY = 20
N_CORP = 12
N_GOVT = 7


def _month_ends(n: int, end: date) -> list[str]:
    """Return the last *n* month-end dates ending at the month of *end* (YYYY-MM-DD)."""

    months: list[str] = []
    y, m = end.year, end.month
    for _ in range(n):
        # first day of next month minus one day = month end
        nm_y, nm_m = (y + 1, 1) if m == 12 else (y, m + 1)
        last = (date(nm_y, nm_m, 1) - date.resolution).isoformat()
        months.append(last)
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return list(reversed(months))


def _build_securities() -> list[dict]:
    """Construct the clean instrument universe (before messiness is injected)."""

    rng = random.Random(101)
    secs: list[dict] = []

    for i in range(1, N_EQUITY + 1):
        region = _REGIONS[i % len(_REGIONS)]
        sector = _SECTORS[i % len(_SECTORS)]
        secs.append({
            "security_id": f"EQ{i:03d}",
            "name": f"{sector} Equity {i}",
            "issuer": f"{sector} Holdings {i}",
            "asset_class": "Equity",
            "gics_sector": sector,
            "region": region,
            "currency": _REGION_CCY[region],
            "rating": "NR",
            "maturity_date": "",
            "coupon_rate": "",
            "effective_duration": "0",
            "inception_date": "2016-01-31",
            "is_active": "true",
            "_base_price": round(rng.uniform(40, 160), 2),
            "_vol": 0.055,
        })

    for i in range(1, N_CORP + 1):
        region = _REGIONS[i % len(_REGIONS)]
        sector = _SECTORS[i % len(_SECTORS)]
        rating = _CREDIT_RATINGS[i % len(_CREDIT_RATINGS)]
        secs.append({
            "security_id": f"CB{i:03d}",
            "name": f"{sector} Corp {rating} 20{27 + i % 8}",
            "issuer": f"{sector} Capital {i}",
            "asset_class": "Corporate",
            "gics_sector": sector,
            "region": region,
            "currency": _REGION_CCY[region],
            "rating": rating,
            "maturity_date": f"20{27 + i % 8}-06-30",
            "coupon_rate": round(rng.uniform(2.0, 6.5), 2),
            "effective_duration": round(rng.uniform(1.5, 8.5), 2),
            "inception_date": "2019-06-30",
            "is_active": "true",
            "_base_price": round(rng.uniform(94, 106), 2),
            "_vol": 0.012,
        })

    govt_issuers = [
        ("US Treasury", "North America", "USD", "AAA"),
        ("German Bund", "Europe", "EUR", "AAA"),
        ("UK Gilt", "Europe", "GBP", "AA"),
        ("Japan JGB", "Asia Pacific", "JPY", "A"),
        ("US Treasury", "North America", "USD", "AAA"),
        ("French OAT", "Europe", "EUR", "AA"),
        ("US Treasury", "North America", "USD", "AAA"),
    ]
    for i, (issuer, region, ccy, rating) in enumerate(govt_issuers[:N_GOVT], start=1):
        secs.append({
            "security_id": f"GB{i:03d}",
            "name": f"{issuer} {2027 + i}",
            "issuer": issuer,
            "asset_class": "Government",
            "gics_sector": "Government",
            "region": region,
            "currency": ccy,
            "rating": rating,
            "maturity_date": f"{2027 + i}-12-31",
            "coupon_rate": round(rng.uniform(1.5, 4.5), 2),
            "effective_duration": round(rng.uniform(2.0, 9.0), 2),
            "inception_date": "2018-12-31",
            "is_active": "true",
            "_base_price": round(rng.uniform(96, 104), 2),
            "_vol": 0.009,
        })

    secs.append({
        "security_id": "CASH",
        "name": "USD Cash",
        "issuer": "Cash",
        "asset_class": "Cash",
        "gics_sector": "Cash",
        "region": "North America",
        "currency": "USD",
        "rating": "NR",
        "maturity_date": "",
        "coupon_rate": "",
        "effective_duration": "0",
        "inception_date": "2016-01-31",
        "is_active": "true",
        "_base_price": 100.0,
        "_vol": 0.0,
    })
    return secs


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def generate_seeds(project: Project, seed: int = 7, n_months: int = 36) -> list[Path]:
    """Write every raw seed CSV and return the list of paths written."""

    rng = random.Random(seed)
    project.seeds_dir.mkdir(parents=True, exist_ok=True)
    dates = _month_ends(n_months, date(2026, 6, 30))
    securities = _build_securities()
    written: list[Path] = []

    # -- security_master (with injected messiness) -----------------------
    sm_header = [
        "security_id", "name", "issuer", "asset_class", "gics_sector", "region",
        "currency", "rating", "maturity_date", "coupon_rate", "effective_duration",
        "inception_date", "is_active",
    ]
    sm_rows: list[list] = []
    for s in securities:
        sm_rows.append([s[c] for c in sm_header])
    # messiness:
    #  1) exact-ish duplicate of EQ001 with a leading space on the id (trim + dedup)
    dup = [securities[0][c] for c in sm_header]
    dup[0] = " EQ001"
    dup[1] = "Technology Equity 1 (stale feed)"
    sm_rows.append(dup)
    #  2) blank asset_class on EQ007 -> recovered from the id prefix
    for row in sm_rows:
        if row[0] == "EQ007":
            row[3] = ""
    #  3) messy rating on CB003 -> trim + upper
        if row[0] == "CB003":
            row[7] = " bbb "
    #  4) lower-case currency on EQ010 -> upper-cased
        if row[0] == "EQ010":
            row[6] = "usd"
    _write_csv(project.seeds_dir / "security_master.csv", sm_header, sm_rows)
    written.append(project.seeds_dir / "security_master.csv")

    # -- prices (long, monthly random walk) ------------------------------
    price_paths: dict[str, list[float]] = {}
    for s in securities:
        px = [s["_base_price"]]
        for _ in range(1, n_months):
            drift = 0.004 if s["asset_class"] == "Equity" else 0.0009
            shock = rng.gauss(drift, s["_vol"])
            px.append(max(1.0, px[-1] * (1 + shock)))
        price_paths[s["security_id"]] = [round(p, 4) for p in px]
    price_paths["CASH"] = [100.0] * n_months

    price_rows: list[list] = []
    ccy_by_id = {s["security_id"]: s["currency"] for s in securities}
    for sid, series in price_paths.items():
        for d, px in zip(dates, series):
            price_rows.append([d, sid, px, ccy_by_id[sid]])
    # messiness: one negative price and one missing price
    for row in price_rows:
        if row[1] == "EQ004" and row[0] == dates[10]:
            row[2] = -5.0            # data error -> nulled in staging
        if row[1] == "CB002" and row[0] == dates[20]:
            row[2] = ""              # missing feed -> null
    _write_csv(project.seeds_dir / "prices.csv",
               ["as_of_date", "security_id", "close_price", "price_currency"], price_rows)
    written.append(project.seeds_dir / "prices.csv")

    # -- holdings (2 accounts, latest as_of_date) ------------------------
    as_of = dates[-1]
    latest_px = {sid: series[-1] for sid, series in price_paths.items()}
    accounts = {
        "ACC-IG-AGG": [s for s in securities if s["asset_class"] in ("Corporate", "Government", "Cash")],
        "ACC-MULTI": securities,
    }
    holdings_rows: list[list] = []
    for account, members in accounts.items():
        raw_notional = {s["security_id"]: rng.uniform(0.5, 3.0) for s in members}
        total = sum(raw_notional.values())
        for s in members:
            target_mv = 100_000_000 * raw_notional[s["security_id"]] / total
            qty = round(target_mv / max(latest_px[s["security_id"]], 1.0), 2)
            holdings_rows.append([as_of, account, s["security_id"], qty])
    _write_csv(project.seeds_dir / "holdings.csv",
               ["as_of_date", "account_id", "security_id", "quantity"], holdings_rows)
    written.append(project.seeds_dir / "holdings.csv")

    # -- benchmark (weights intentionally un-normalised) -----------------
    benchmarks = {
        "BBG-AGG": [s for s in securities if s["asset_class"] in ("Corporate", "Government")],
        "GLOBAL-60-40": securities,
    }
    bm_rows: list[list] = []
    for bench, members in benchmarks.items():
        raw_w = {s["security_id"]: rng.uniform(0.5, 2.0) for s in members}
        total = sum(raw_w.values())
        # scale so the raw file sums to ~1.03, not exactly 1 -> staging normalises
        for s in members:
            w = 1.03 * raw_w[s["security_id"]] / total
            bm_rows.append([as_of, bench, s["security_id"], round(w, 8)])
    _write_csv(project.seeds_dir / "benchmark.csv",
               ["as_of_date", "benchmark_id", "security_id", "weight"], bm_rows)
    written.append(project.seeds_dir / "benchmark.csv")

    # -- factor returns --------------------------------------------------
    fr_rows: list[list] = []
    for f in _FACTORS:
        vol = 0.02 if f.startswith("EQ") else 0.006
        for d in dates:
            fr_rows.append([d, f, round(rng.gauss(0.001, vol), 6)])
    _write_csv(project.seeds_dir / "factor_returns.csv",
               ["as_of_date", "factor_id", "factor_return"], fr_rows)
    written.append(project.seeds_dir / "factor_returns.csv")

    # -- factor exposures (sparse, only relevant factors per security) ---
    fe_rows: list[list] = []
    for s in securities:
        sid = s["security_id"]
        if s["asset_class"] == "Equity":
            fe_rows.append([sid, "EQ_MARKET", round(rng.uniform(0.7, 1.3), 3)])
            for f in ("EQ_SIZE", "EQ_VALUE", "EQ_MOMENTUM", "EQ_QUALITY"):
                fe_rows.append([sid, f, round(rng.gauss(0.0, 1.0), 3)])
        elif s["asset_class"] in ("Corporate", "Government"):
            fe_rows.append([sid, "RATE_LEVEL", round(rng.uniform(2.0, 8.0), 3)])
            fe_rows.append([sid, "RATE_SLOPE", round(rng.gauss(0.0, 1.5), 3)])
            credit = "CREDIT_HY" if s["rating"] in ("BB", "B") else "CREDIT_IG"
            if s["asset_class"] == "Corporate":
                fe_rows.append([sid, credit, round(rng.uniform(0.5, 3.0), 3)])
    _write_csv(project.seeds_dir / "factor_exposures.csv",
               ["security_id", "factor_id", "exposure"], fe_rows)
    written.append(project.seeds_dir / "factor_exposures.csv")

    # -- macro series ----------------------------------------------------
    macro_levels = {"UST_10Y": 4.2, "UST_2Y": 4.6, "IG_OAS": 1.2, "HY_OAS": 3.8,
                    "TBILL_3M": 5.1, "CPI_YOY": 3.1}
    macro_rows: list[list] = []
    for series_id, level in macro_levels.items():
        val = level
        for d in dates:
            val = max(0.0, val + rng.gauss(0.0, 0.08))
            macro_rows.append([d, series_id, round(val, 3)])
    _write_csv(project.seeds_dir / "macro.csv",
               ["as_of_date", "series_id", "series_value"], macro_rows)
    written.append(project.seeds_dir / "macro.csv")

    # -- fx rates (USD per unit of currency) -----------------------------
    fx_base = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "JPY": 0.0068}
    fx_rows: list[list] = []
    for ccy, base in fx_base.items():
        val = base
        for d in dates:
            val = max(0.0001, val * (1 + rng.gauss(0.0, 0.0 if ccy == "USD" else 0.015)))
            fx_rows.append([d, ccy, round(val, 6)])
    _write_csv(project.seeds_dir / "fx_rates.csv",
               ["as_of_date", "currency", "usd_per_unit"], fx_rows)
    written.append(project.seeds_dir / "fx_rates.csv")

    return written
