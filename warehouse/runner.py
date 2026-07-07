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

import duckdb

from warehouse.dag import Model, discover_models, select_nodes, topological_order
from warehouse.project import Project
from warehouse.templating import apply_incremental, render


@dataclass
class StepResult:
    """Outcome of building one model (or loading one seed)."""

    name: str
    layer: str
    materialized: str
    status: str          # "ok" | "error" | "skip"
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
    def run(self, models: dict[str, Model] | None = None, *,
            select: list[str] | None = None, exclude: list[str] | None = None,
            full_refresh: bool = False) -> list[StepResult]:
        """Build models in dependency order.

        ``select`` / ``exclude`` take dbt-style graph selectors (``m+``, ``+m``)
        to build a subgraph; ``full_refresh`` rebuilds incremental models from
        scratch instead of appending. When a model fails, its descendants are
        skipped rather than built against a stale or missing relation.
        """

        models = models if models is not None else discover_models(self.project)
        order = topological_order(models, self.project)
        chosen = select_nodes(models, select, exclude)
        results: list[StepResult] = []
        blocked: set[str] = set()  # failed this run, or skipped because a parent did
        for model in order:
            if model.name not in chosen:
                continue
            bad_parents = [r for r in model.refs if r in blocked]
            if bad_parents:
                blocked.add(model.name)
                results.append(StepResult(
                    model.name, model.layer, model.materialized(self.project),
                    "skip", 0, 0.0,
                    f"upstream failed: {', '.join(bad_parents)}"))
                continue
            result = self._build_model(model, full_refresh=full_refresh)
            if result.status == "error":
                blocked.add(model.name)
            results.append(result)
        return results

    def _relation_exists(self, name: str) -> bool:
        found = self.con.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = ? AND table_name = ?",
            [self.project.target_schema, name],
        ).fetchone()[0]
        return found > 0

    def _build_model(self, model: Model, full_refresh: bool = False) -> StepResult:
        materialized = model.materialized(self.project)
        relation = f"{self.project.target_schema}.{model.name}"
        compiled_base = render(model.raw_sql, self.project).strip().rstrip(";")

        start = time.perf_counter()
        try:
            if materialized == "incremental":
                label = self._build_incremental(model, relation, compiled_base, full_refresh)
            else:
                keyword = "VIEW" if materialized == "view" else "TABLE"
                self.con.execute(f"CREATE OR REPLACE {keyword} {relation} AS\n{compiled_base}")
                label = materialized
            rows = self.con.execute(f"SELECT count(*) FROM {relation}").fetchone()[0]
            return StepResult(model.name, model.layer, label, "ok",
                              rows, time.perf_counter() - start)
        except Exception as exc:  # noqa: BLE001
            return StepResult(model.name, model.layer, materialized, "error", 0,
                              time.perf_counter() - start, str(exc))

    def _build_incremental(self, model: Model, relation: str,
                           compiled_base: str, full_refresh: bool) -> str:
        """Create-or-append an incremental model; return a status label."""

        if full_refresh or not self._relation_exists(model.name):
            sql = apply_incremental(compiled_base, relation, is_incremental=False)
            self.con.execute(f"CREATE OR REPLACE TABLE {relation} AS\n{sql}")
            return "incremental (full)"
        sql = apply_incremental(compiled_base, relation, is_incremental=True)
        self.con.execute(f"INSERT INTO {relation}\n{sql}")
        return "incremental (append)"

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
