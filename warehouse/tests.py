"""Schema tests, source tests, and singular data tests.

Flavours, mirroring dbt:

* **Generic tests** declared in ``schema.yml`` on models *and* on sources
  (``not_null``, ``unique``, ``accepted_values``, ``relationships``).
* **Singular data tests**: hand-written ``.sql`` files under ``data_tests/``
  that select offending rows.

Each test compiles to a *failing-rows* query. Zero rows = pass. Tests carry a
``severity`` (``error`` by default, or ``warn``): a failing ``warn`` test is
reported but does not fail the build — the standard "investigate vs stop the
line" split. With ``store_failures`` the offending rows are written to CSV so a
red test is debuggable, not just a count.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import yaml

from warehouse.project import Project
from warehouse.runner import Warehouse
from warehouse.templating import extract_config, find_refs, render, resolve_relation


@dataclass
class TestCase:
    """A compiled test: run ``rows_sql`` and expect zero rows."""

    __test__ = False  # not a pytest test class despite the name

    name: str
    kind: str            # not_null | unique | accepted_values | relationships | singular
    scope: str           # model or source table the test is attached to
    column: str
    rows_sql: str        # selects the failing rows
    severity: str = "error"
    refs: tuple[str, ...] = ()   # models a singular test reads (drives --select)


@dataclass
class TestResult:
    __test__ = False  # not a pytest test class despite the name

    name: str
    kind: str
    scope: str
    column: str
    status: str          # "pass" | "fail" | "warn" | "error"
    failures: int
    severity: str
    seconds: float
    error: str = ""
    stored_at: str = ""


def _quote_values(values: list) -> str:
    return ", ".join("'" + str(v).replace("'", "''") + "'" for v in values)


def _compile_generic(project: Project, relation: str, scope: str,
                     column: str, spec) -> TestCase:
    """Turn one ``schema.yml`` test entry into a :class:`TestCase` of failing rows."""

    if isinstance(spec, str):
        kind, cfg = spec, {}
    elif isinstance(spec, dict):
        kind = next(iter(spec))
        cfg = spec[kind] or {}
    else:  # pragma: no cover
        raise ValueError(f"Unrecognised test spec on {scope}.{column}: {spec!r}")

    severity = str(cfg.get("severity", "error"))

    if kind == "not_null":
        rows = f"SELECT * FROM {relation} WHERE {column} IS NULL"
    elif kind == "unique":
        rows = (f"SELECT {column}, count(*) AS n FROM {relation} "
                f"WHERE {column} IS NOT NULL GROUP BY {column} HAVING count(*) > 1")
    elif kind == "accepted_values":
        values = _quote_values(cfg["values"])
        rows = (f"SELECT * FROM {relation} "
                f"WHERE {column} IS NOT NULL AND {column} NOT IN ({values})")
    elif kind == "relationships":
        to_rel = resolve_relation(cfg["to"], project)
        field = cfg["field"]
        rows = (f"SELECT c.* FROM {relation} c "
                f"LEFT JOIN {to_rel} p ON c.{column} = p.{field} "
                f"WHERE c.{column} IS NOT NULL AND p.{field} IS NULL")
    else:
        raise ValueError(f"Unknown generic test '{kind}' on {scope}.{column}")

    return TestCase(name=f"{kind}__{scope}__{column}", kind=kind,
                    scope=scope, column=column, rows_sql=rows, severity=severity)


def _compile_columns(project: Project, relation: str, scope: str,
                     columns: list) -> list[TestCase]:
    cases: list[TestCase] = []
    for col in columns or []:
        cname = col["name"]
        for spec in col.get("tests", []) or []:
            cases.append(_compile_generic(project, relation, scope, cname, spec))
    return cases


def load_schema_tests(project: Project) -> list[TestCase]:
    """Collect generic tests on both models and sources from every schema.yml."""

    cases: list[TestCase] = []
    for schema_path in sorted(project.models_dir.rglob("schema.yml")):
        doc = yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}
        # model tests: relation is target_schema.model
        for model in doc.get("models", []) or []:
            rel = f"{project.target_schema}.{model['name']}"
            cases += _compile_columns(project, rel, model["name"], model.get("columns", []))
        # source tests: relation is the raw schema.table
        for source in doc.get("sources", []) or []:
            schema = source["name"]
            for table in source.get("tables", []) or []:
                rel = f"{schema}.{table['name']}"
                scope = f"source.{table['name']}"
                cases += _compile_columns(project, rel, scope, table.get("columns", []))
    return cases


def load_singular_tests(project: Project) -> list[TestCase]:
    """Collect singular ``.sql`` data tests from the ``data_tests/`` directory."""

    cases: list[TestCase] = []
    data_tests_dir = project.root / "data_tests"
    if not data_tests_dir.exists():
        return cases
    for sql_path in sorted(data_tests_dir.glob("*.sql")):
        config, body = extract_config(sql_path.read_text(encoding="utf-8"))
        rows = render(body, project).strip().rstrip(";")
        cases.append(TestCase(name=sql_path.stem, kind="singular", scope="",
                              column="", rows_sql=rows,
                              severity=str(config.get("severity", "error")),
                              refs=tuple(find_refs(body))))
    return cases


def load_all_tests(project: Project) -> list[TestCase]:
    return load_schema_tests(project) + load_singular_tests(project)


def select_test_cases(cases: list[TestCase], chosen: set[str]) -> list[TestCase]:
    """Restrict *cases* to the selected models, mirroring dbt's semantics.

    Generic tests are kept when the model they are attached to is selected;
    singular tests are kept when any model they ``ref()`` is selected. Source
    tests attach to sources, not models, so a model selection drops them.
    """

    kept: list[TestCase] = []
    for case in cases:
        if case.kind == "singular":
            if set(case.refs) & chosen:
                kept.append(case)
        elif case.scope in chosen:
            kept.append(case)
    return kept


def run_tests(warehouse: Warehouse, cases: list[TestCase], *,
              store_failures: bool = False) -> list[TestResult]:
    """Execute each test, classify it, and optionally store failing rows."""

    failures_dir = warehouse.project.reports_dir / "failures"
    results: list[TestResult] = []
    for case in cases:
        start = time.perf_counter()
        try:
            count = warehouse.fetch(f"SELECT count(*) FROM (\n{case.rows_sql}\n) t")[0][0]
            if count == 0:
                status = "pass"
            else:
                status = "warn" if case.severity == "warn" else "fail"
            stored_at = ""
            if store_failures and count > 0:
                failures_dir.mkdir(parents=True, exist_ok=True)
                dest = (failures_dir / f"{case.name}.csv").as_posix()
                dest_sql = dest.replace("'", "''")
                warehouse.con.execute(
                    f"COPY (\n{case.rows_sql}\n) TO '{dest_sql}' (HEADER, DELIMITER ',')")
                stored_at = dest
            results.append(TestResult(case.name, case.kind, case.scope, case.column,
                                      status, int(count), case.severity,
                                      time.perf_counter() - start, stored_at=stored_at))
        except Exception as exc:  # noqa: BLE001
            results.append(TestResult(case.name, case.kind, case.scope, case.column,
                                      "error", -1, case.severity,
                                      time.perf_counter() - start, error=str(exc)))
    return results
