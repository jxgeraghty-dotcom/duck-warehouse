"""duck-warehouse: a small, dependency-light dbt-style ELT framework on DuckDB.

The package implements the handful of ideas that make dbt useful, without the
dbt install: ``{{ ref() }}`` / ``{{ source() }}`` templating, a compiled model
DAG, layered materialisation (staging -> intermediate -> marts), and schema /
data tests declared in YAML. It exists to be the warehouse that feeds the other
showcase tools (portfolio risk monitor, compliance engine, TAA backtester).
"""

from warehouse.project import Project, load_project

__all__ = ["Project", "load_project"]
__version__ = "0.1.0"
