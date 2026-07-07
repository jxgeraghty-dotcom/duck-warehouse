"""Export marts into the exact CSV shapes the sibling showcase tools consume.

This is what makes the "connective tissue" claim concrete: the same warehouse
that models the data also hands each downstream tool a file in the shape it
already expects. Each :class:`ExportSpec` documents which tool it feeds.
"""

from __future__ import annotations

from dataclasses import dataclass

from warehouse.runner import Warehouse


@dataclass(frozen=True)
class ExportSpec:
    filename: str
    target_tool: str
    description: str
    sql: str


def export_specs(target_schema: str) -> list[ExportSpec]:
    s = target_schema
    return [
        ExportSpec(
            "security_master.csv",
            "Portfolio risk & exposure monitor",
            "Instrument reference data (dim_security).",
            f"""SELECT security_id, name, asset_class, sector, region, currency,
                       rating, maturity_date AS maturity, effective_duration
                FROM {s}.dim_security
                ORDER BY security_id""",
        ),
        ExportSpec(
            "portfolio_weights.csv",
            "Portfolio risk & exposure monitor",
            "Active portfolio weights for account ACC-MULTI.",
            f"""SELECT security_id, weight
                FROM {s}.fct_portfolio_holdings
                WHERE account_id = 'ACC-MULTI'
                ORDER BY security_id""",
        ),
        ExportSpec(
            "benchmark_weights.csv",
            "Portfolio risk & exposure monitor",
            "Benchmark weights for GLOBAL-60-40.",
            f"""SELECT security_id, weight
                FROM {s}.fct_benchmark_weights
                WHERE benchmark_id = 'GLOBAL-60-40'
                ORDER BY security_id""",
        ),
        ExportSpec(
            "compliance_portfolio.csv",
            "Guideline & compliance monitoring engine",
            "Valued positions for account ACC-IG-AGG in the engine's schema.",
            f"""SELECT h.security_id, d.issuer, d.sector, d.asset_class,
                       h.market_value, d.rating, d.effective_duration AS duration,
                       d.currency
                FROM {s}.fct_portfolio_holdings h
                JOIN {s}.dim_security d USING (security_id)
                WHERE h.account_id = 'ACC-IG-AGG'
                ORDER BY h.security_id""",
        ),
        ExportSpec(
            "factor_returns.csv",
            "Portfolio risk & exposure monitor",
            "Factor return time series (long format).",
            f"""SELECT as_of_date, factor_id, factor_return
                FROM {s}.fct_factor_returns
                ORDER BY as_of_date, factor_id""",
        ),
        ExportSpec(
            "factor_covariance.csv",
            "Portfolio risk & exposure monitor",
            "Annualised factor covariance matrix (long format).",
            f"""SELECT factor_i, factor_j, covariance, correlation
                FROM {s}.mart_factor_covariance
                ORDER BY factor_i, factor_j""",
        ),
        ExportSpec(
            "asset_class_index.csv",
            "Multi-asset TAA backtesting framework",
            "Cap-weighted asset-class price indices (wide format).",
            f"""SELECT * FROM {s}.mart_asset_class_prices ORDER BY as_of_date""",
        ),
        ExportSpec(
            "macro.csv",
            "Multi-asset TAA backtesting framework",
            "Macro series in wide format (one column per series).",
            f"""SELECT * FROM {s}.mart_macro_wide ORDER BY as_of_date""",
        ),
    ]


def run_exports(warehouse: Warehouse) -> list[tuple[ExportSpec, int]]:
    """Write every export CSV; return (spec, row_count) pairs."""

    out_dir = warehouse.project.exports_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[tuple[ExportSpec, int]] = []
    for spec in export_specs(warehouse.project.target_schema):
        dest = (out_dir / spec.filename).as_posix()
        warehouse.con.execute(
            f"COPY (\n{spec.sql}\n) TO '{dest}' (HEADER, DELIMITER ',')"
        )
        rows = warehouse.fetch(f"SELECT count(*) FROM (\n{spec.sql}\n)")[0][0]
        written.append((spec, int(rows)))
    return written
