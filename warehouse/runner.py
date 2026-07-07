"""Execute the warehouse against DuckDB: seed, then build models in DAG order.

Seeds are loaded as *all-varchar* tables so the raw layer faithfully preserves
whatever the upstream feed sent (blanks, negatives, stray whitespace); every
cast and clean then happens explicitly in the staging models, which is where you
want that logic to live and be tested.
"""

from __future__ import annotations

import time
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb

from warehouse.dag import Model, discover_models, topological_order
from warehouse.project import Project
from warehouse.templating import render


@dataclass
class StepResult:
    """Outcome of building one model (or loading one seed)."""

    name: str
    layer: str
    materialized: str
    status: str          # "ok" | "error"
    rows: int
    seconds: float
    error: str = ""


class Warehouse:
    """Thin wrapper around a DuckDB connection scoped to one project."""

    def __init__(self, project: Project):
        self.project = project
        self.con = duckdb.connect(str(project.database))
        self._ensure_schemas()

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "Warehouse":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- setup -----------------------------------------------------------
    def _ensure_schemas(self) -> None:
        for schema in (self.project.raw_schema, self.project.target_schema):
            self.con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    # -- seeds -----------------------------------------------------------
    def seed(self) -> list[StepResult]:
        """Load every declared source's CSV into the raw schema as text."""

        results: list[StepResult] = []
        for src in self.project.sources.values():
            csv_path = (self.project.seeds_dir / src.seed)
            start = time.perf_counter()
            try:
                if not csv_path.exists():
                    raise FileNotFoundError(
                        f"Seed file missing: {csv_path}. Run `dw seed --generate` "
                        f"first to create the sample data."
                    )
                self.con.execute(
                    f"CREATE OR REPLACE TABLE {src.relation} AS "
                    f"SELECT * FROM read_csv(?, header=true, all_varchar=true)",
                    [csv_path.as_posix()],
                )
                rows = self.con.execute(f"SELECT count(*) FROM {src.relation}").fetchone()[0]
                results.append(StepResult(src.name, "seed", "table", "ok",
                                          rows, time.perf_counter() - start))
            except Exception as exc:  # noqa: BLE001 - surfaced to the CLI
                results.append(StepResult(src.name, "seed", "table", "error", 0,
                                          time.perf_counter() - start, str(exc)))
                raise
        return results

    # -- models ----------------------------------------------------------
    def run(self, models: dict[str, Model] | None = None) -> list[StepResult]:
        """Build all models in dependency order via CREATE OR REPLACE."""

        models = models if models is not None else discover_models(self.project)
        order = topological_order(models, self.project)
        results: list[StepResult] = []
        for model in order:
            results.append(self._build_model(model))
        return results

    def _build_model(self, model: Model) -> StepResult:
        materialized = model.materialized(self.project)
        relation = f"{self.project.target_schema}.{model.name}"
        keyword = "VIEW" if materialized == "view" else "TABLE"
        compiled = render(model.raw_sql, self.project).strip().rstrip(";")

        start = time.perf_counter()
        try:
            self.con.execute(f"CREATE OR REPLACE {keyword} {relation} AS\n{compiled}")
            rows = self.con.execute(f"SELECT count(*) FROM {relation}").fetchone()[0]
            return StepResult(model.name, model.layer, materialized, "ok",
                              rows, time.perf_counter() - start)
        except Exception as exc:  # noqa: BLE001
            return StepResult(model.name, model.layer, materialized, "error", 0,
                              time.perf_counter() - start, str(exc))

    # -- helpers ---------------------------------------------------------
    def compile_model(self, model: Model) -> str:
        """Return the fully-resolved SQL for a model (no execution)."""

        return render(model.raw_sql, self.project).strip()

    def table_columns(self, relation: str) -> list[str]:
        rows = self.con.execute(f"SELECT * FROM {relation} LIMIT 0").description
        return [r[0] for r in rows]

    def fetch(self, sql: str) -> list[tuple]:
        return self.con.execute(sql).fetchall()


def build_all(project: Project) -> list[StepResult]:
    """Convenience: seed + run in one call (used by the end-to-end tests)."""

    with closing(Warehouse(project)) as wh:
        seeded = wh.seed()
        built = wh.run()
        return seeded + built


def results_as_dicts(results: list[StepResult]) -> list[dict]:
    return [asdict(r) for r in results]
