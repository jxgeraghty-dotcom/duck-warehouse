"""End-to-end handoff smoke test.

Proves the "connective tissue" claim for real: it runs ``dw export`` and then
*loads every exported CSV back through DuckDB with the column types the consuming
tool expects*, failing if any file is missing, mis-shaped, empty, or won't parse
under its contract. That is a genuine consumer-side load, not just a header
string comparison.

Run standalone (after `dw build`):

    python scripts/handoff_smoke.py

or from tests via :func:`run_smoke`.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

# allow running as a plain script from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from warehouse.export import run_exports  # noqa: E402
from warehouse.project import load_project  # noqa: E402
from warehouse.runner import Warehouse  # noqa: E402

# Each export file -> the consumer's expected column contract (name -> DuckDB
# type). A typed re-read that satisfies this is what the downstream tool does.
CONTRACTS: dict[str, dict[str, str]] = {
    "security_master.csv": {
        "security_id": "VARCHAR", "name": "VARCHAR", "asset_class": "VARCHAR",
        "sector": "VARCHAR", "region": "VARCHAR", "currency": "VARCHAR",
        "rating": "VARCHAR", "maturity": "DATE", "effective_duration": "DOUBLE",
    },
    "portfolio_weights.csv": {"security_id": "VARCHAR", "weight": "DOUBLE"},
    "benchmark_weights.csv": {"security_id": "VARCHAR", "weight": "DOUBLE"},
    "compliance_portfolio.csv": {
        "security_id": "VARCHAR", "issuer": "VARCHAR", "sector": "VARCHAR",
        "asset_class": "VARCHAR", "market_value": "DOUBLE", "rating": "VARCHAR",
        "duration": "DOUBLE", "currency": "VARCHAR",
    },
    "factor_returns.csv": {
        "as_of_date": "DATE", "factor_id": "VARCHAR", "factor_return": "DOUBLE",
    },
    "factor_covariance.csv": {
        "factor_i": "VARCHAR", "factor_j": "VARCHAR",
        "covariance": "DOUBLE", "correlation": "DOUBLE",
    },
    "asset_class_index.csv": {
        "as_of_date": "DATE", "eq_index": "DOUBLE", "credit_index": "DOUBLE",
        "govt_index": "DOUBLE", "cash_index": "DOUBLE",
    },
    "macro.csv": {
        "as_of_date": "DATE", "ust_10y": "DOUBLE", "ust_2y": "DOUBLE",
        "ig_oas": "DOUBLE", "hy_oas": "DOUBLE", "tbill_3m": "DOUBLE", "cpi_yoy": "DOUBLE",
    },
}


@dataclass
class SmokeResult:
    filename: str
    ok: bool
    rows: int
    detail: str


def _load_with_contract(wh: Warehouse, path: Path, contract: dict[str, str]) -> SmokeResult:
    # 1) the header must match the consumer's expected columns, in order
    header = path.read_text(encoding="utf-8").splitlines()[0].split(",")
    expected = list(contract)
    if header != expected:
        return SmokeResult(path.name, False, 0,
                           f"header mismatch: got {header}, want {expected}")
    # 2) the rows must parse under the consumer's column types (a real load)
    columns = ", ".join(f"'{c}': '{t}'" for c, t in contract.items())
    try:
        rows = wh.fetch(
            f"SELECT count(*) FROM read_csv('{path.as_posix()}', header=true, "
            f"columns={{{columns}}})"
        )[0][0]
    except Exception as exc:  # noqa: BLE001
        return SmokeResult(path.name, False, 0, f"load failed: {str(exc).splitlines()[0]}")
    if rows == 0:
        return SmokeResult(path.name, False, 0, "loaded but empty")
    return SmokeResult(path.name, True, int(rows), "loaded under consumer contract")


def run_smoke(project) -> list[SmokeResult]:
    """Export, then load every file back under its consumer contract."""

    with Warehouse(project) as wh:
        run_exports(wh)
        results: list[SmokeResult] = []
        for filename, contract in CONTRACTS.items():
            path = project.exports_dir / filename
            if not path.exists():
                results.append(SmokeResult(filename, False, 0, "not exported"))
                continue
            results.append(_load_with_contract(wh, path, contract))
    return results


def main() -> int:
    project = load_project(Path(__file__).resolve().parent.parent / "dw.yaml")
    try:
        results = run_smoke(project)
    except Exception as exc:  # noqa: BLE001
        print(f"Smoke test could not run (is the warehouse built? run `dw build`): {exc}")
        return 2

    print("\nHandoff smoke test")
    print("-" * 18)
    ok_all = True
    for r in results:
        marker = "[ok] " if r.ok else "[FAIL]"
        print(f"  {marker} {r.filename:<26} {r.rows:>5} rows  {r.detail}")
        ok_all = ok_all and r.ok
    print(f"\n  {'PASS' if ok_all else 'FAIL'}: "
          f"{sum(r.ok for r in results)}/{len(results)} exports load cleanly")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
