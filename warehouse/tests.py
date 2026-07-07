"""Schema tests and singular data tests.

Two flavours, mirroring dbt:

* **Generic tests** declared in ``schema.yml`` next to the models
  (``not_null``, ``unique``, ``accepted_values``, ``relationships``). Each is
  compiled to a query that counts failing rows.
* **Singular data tests**: hand-written ``.sql`` files under ``data_tests/``
  that select the offending rows. Any rows returned means failure. These express
  business rules that do not fit a generic test (e.g. "benchmark weights sum to
  one", "no active security is past maturity").

A test passes when it finds zero failing rows.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from warehouse.project import Project
from warehouse.runner import Warehouse
from warehouse.templating import render, resolve_relation


@dataclass
class TestCase:
    """A single compiled test: run its ``sql`` and expect zero failures."""

    name: str
    kind: str            # not_null | unique | accepted_values | relationships | singular
    model: str
    column: str
    sql: str             # returns one row, one column: the failing-row count


@dataclass
class TestResult:
    name: str
    kind: str
    model: str
    column: str
    status: str          # "pass" | "fail" | "error"
    failures: int
    seconds: float
    error: str = ""


def _quote_values(values: list) -> str:
    parts = []
    for v in values:
        parts.append("'" + str(v).replace("'", "''") + "'")
    return ", ".join(parts)


def _compile_generic(project: Project, model: str, column: str, spec) -> TestCase:
    """Turn one ``schema.yml`` test entry into a :class:`TestCase`."""

    rel = f"{project.target_schema}.{model}"

    if isinstance(spec, str):
        kind, cfg = spec, {}
    elif isinstance(spec, dict):
        kind = next(iter(spec))
        cfg = spec[kind] or {}
    else:  # pragma: no cover - guarded by yaml structure
        raise ValueError(f"Unrecognised test spec on {model}.{column}: {spec!r}")

    if kind == "not_null":
        sql = f"SELECT count(*) FROM {rel} WHERE {column} IS NULL"
    elif kind == "unique":
        sql = (f"SELECT count(*) FROM (SELECT {column} FROM {rel} "
               f"WHERE {column} IS NOT NULL GROUP BY {column} HAVING count(*) > 1)")
    elif kind == "accepted_values":
        values = _quote_values(cfg["values"])
        sql = (f"SELECT count(*) FROM {rel} "
               f"WHERE {column} IS NOT NULL AND {column} NOT IN ({values})")
    elif kind == "relationships":
        to_rel = resolve_relation(cfg["to"], project)
        field = cfg["field"]
        sql = (f"SELECT count(*) FROM {rel} c "
               f"LEFT JOIN {to_rel} p ON c.{column} = p.{field} "
               f"WHERE c.{column} IS NOT NULL AND p.{field} IS NULL")
    else:
        raise ValueError(f"Unknown generic test '{kind}' on {model}.{column}")

    return TestCase(name=f"{kind}__{model}__{column}", kind=kind,
                    model=model, column=column, sql=sql)


def load_schema_tests(project: Project) -> list[TestCase]:
    """Collect generic tests from every ``schema.yml`` under the models tree."""

    cases: list[TestCase] = []
    for schema_path in sorted(project.models_dir.rglob("schema.yml")):
        doc = yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}
        for model in doc.get("models", []) or []:
            mname = model["name"]
            for col in model.get("columns", []) or []:
                cname = col["name"]
                for spec in col.get("tests", []) or []:
                    cases.append(_compile_generic(project, mname, cname, spec))
    return cases


def load_singular_tests(project: Project) -> list[TestCase]:
    """Collect singular ``.sql`` data tests from the ``data_tests/`` directory."""

    cases: list[TestCase] = []
    data_tests_dir = project.root / "data_tests"
    if not data_tests_dir.exists():
        return cases
    for sql_path in sorted(data_tests_dir.glob("*.sql")):
        body = render(sql_path.read_text(encoding="utf-8"), project).strip().rstrip(";")
        # Wrap so the test always yields a single failing-row count.
        wrapped = f"SELECT count(*) FROM (\n{body}\n) AS failing_rows"
        cases.append(TestCase(name=sql_path.stem, kind="singular",
                              model="", column="", sql=wrapped))
    return cases


def load_all_tests(project: Project) -> list[TestCase]:
    return load_schema_tests(project) + load_singular_tests(project)


def run_tests(warehouse: Warehouse, cases: list[TestCase]) -> list[TestResult]:
    """Execute each test and classify pass / fail / error."""

    results: list[TestResult] = []
    for case in cases:
        start = time.perf_counter()
        try:
            failures = warehouse.fetch(case.sql)[0][0]
            status = "pass" if failures == 0 else "fail"
            results.append(TestResult(case.name, case.kind, case.model, case.column,
                                      status, int(failures), time.perf_counter() - start))
        except Exception as exc:  # noqa: BLE001
            results.append(TestResult(case.name, case.kind, case.model, case.column,
                                      "error", -1, time.perf_counter() - start, str(exc)))
    return results
