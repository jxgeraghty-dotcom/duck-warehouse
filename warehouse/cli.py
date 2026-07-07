"""Command-line interface: ``dw <command>``.

Commands mirror the dbt vocabulary so the mental model transfers:

    dw seed [--generate]   load raw CSVs into the warehouse (optionally regenerate them)
    dw run                 build staging -> intermediate -> marts in DAG order
    dw test                run schema + data tests
    dw build               seed + run + test + docs (the one-shot demo command)
    dw export              write consumer-shaped CSVs for the sibling tools
    dw docs                write the lineage graph and model catalog
    dw dag                 print build order and write the Mermaid lineage
    dw compile <model>     print a model's fully-resolved SQL
    dw preview <relation>  show a few rows from any table/view

Exit code is non-zero when any model or test fails, so it drops cleanly into CI.
"""

from __future__ import annotations

import argparse
import json
import sys

from warehouse import __version__
from warehouse.dag import discover_models, select_nodes, topological_order
from warehouse.docs import write_docs
from warehouse.export import run_exports
from warehouse.freshness import check_freshness
from warehouse.project import Project, load_project
from warehouse.runner import StepResult, Warehouse, results_as_dicts
from warehouse.seeds import generate_seeds
from warehouse.tests import load_all_tests, run_tests


def _print_steps(title: str, steps: list[StepResult]) -> bool:
    """Print a table of build/seed steps; return True if all succeeded."""

    print(f"\n{title}")
    print("-" * len(title))
    ok = True
    for s in steps:
        marker = "[ok] " if s.status == "ok" else "[ERR]"
        print(f"  {marker} {s.layer:<12} {s.name:<28} {s.rows:>7,} rows  "
              f"{s.seconds*1000:6.0f} ms  {s.materialized}")
        if s.status != "ok":
            ok = False
            print(f"        -> {s.error.splitlines()[0] if s.error else 'unknown error'}")
    return ok


def _write_run_results(project: Project, steps: list[StepResult]) -> None:
    project.reports_dir.mkdir(parents=True, exist_ok=True)
    (project.reports_dir / "run_results.json").write_text(
        json.dumps(results_as_dicts(steps), indent=2), encoding="utf-8"
    )


# -- commands ------------------------------------------------------------

def cmd_seed(project: Project, args: argparse.Namespace) -> int:
    if args.generate:
        written = generate_seeds(project, seed=args.seed)
        print(f"Generated {len(written)} seed files in {project.seeds_dir}")
    with Warehouse(project) as wh:
        steps = wh.seed()
    ok = _print_steps("Seeding raw sources", steps)
    return 0 if ok else 1


def cmd_run(project: Project, args: argparse.Namespace) -> int:
    with Warehouse(project) as wh:
        steps = wh.run(select=args.select, exclude=args.exclude,
                       full_refresh=args.full_refresh)
    ok = _print_steps("Building models", steps)
    _write_run_results(project, steps)
    return 0 if ok else 1


def cmd_test(project: Project, args: argparse.Namespace) -> int:
    cases = load_all_tests(project)
    select = getattr(args, "select", None)
    exclude = getattr(args, "exclude", None)
    if select or exclude:
        models = discover_models(project)
        chosen = select_nodes(models, select, exclude)
        # keep generic tests on selected models; singular tests always run
        cases = [c for c in cases if c.kind == "singular" or c.scope in chosen]
    store = getattr(args, "store_failures", False)
    with Warehouse(project) as wh:
        results = run_tests(wh, cases, store_failures=store)
    print(f"\nRunning {len(results)} tests")
    print("-" * 21)
    passed = warned = failed = errored = 0
    for r in results:
        if r.status == "pass":
            passed += 1
            continue
        if r.status == "warn":
            warned += 1
            marker = "[WARN]"
        elif r.status == "fail":
            failed += 1
            marker = "[FAIL]"
        else:
            errored += 1
            marker = "[ERR] "
        detail = (f"{r.failures} failing rows" if r.status in ("fail", "warn")
                  else r.error.splitlines()[0])
        stored = f"  -> {r.stored_at}" if r.stored_at else ""
        print(f"  {marker} {r.name:<45} {detail}{stored}")
    summary = f"\n  {passed} passed, {failed} failed"
    if warned:
        summary += f", {warned} warned"
    if errored:
        summary += f", {errored} errored"
    print(summary + f" of {len(results)} tests")
    return 0 if failed == 0 and errored == 0 else 1


def cmd_build(project: Project, args: argparse.Namespace) -> int:
    if args.generate:
        generate_seeds(project, seed=args.seed)
        print(f"Generated seed files in {project.seeds_dir}")
    with Warehouse(project) as wh:
        seed_steps = wh.seed()
        run_steps = wh.run(full_refresh=args.full_refresh)
    all_steps = seed_steps + run_steps
    ok = _print_steps("Seeding raw sources", seed_steps)
    ok = _print_steps("Building models", run_steps) and ok
    _write_run_results(project, all_steps)
    if not ok:
        print("\nBuild failed; skipping tests.")
        return 1
    rc = cmd_test(project, args)
    write_docs(project)
    print(f"\nDocs written to {project.reports_dir}")
    return rc


def cmd_export(project: Project, args: argparse.Namespace) -> int:
    with Warehouse(project) as wh:
        written = run_exports(wh)
    print(f"\nExported {len(written)} files to {project.exports_dir}")
    print("-" * 40)
    for spec, rows in written:
        print(f"  {spec.filename:<28} {rows:>6,} rows  -> {spec.target_tool}")
    return 0


def cmd_source(project: Project, args: argparse.Namespace) -> int:
    if args.source_command != "freshness":
        print("usage: dw source freshness")
        return 2
    with Warehouse(project) as wh:
        results = check_freshness(wh)
    print("\nSource freshness")
    print("-" * 16)
    worst_error = False
    for r in results:
        marker = {"pass": "[ok]  ", "warn": "[WARN]",
                  "error": "[ERR] ", "skip": "[skip]"}[r.status]
        latest = r.max_loaded_at or "-"
        print(f"  {marker} {r.source:<20} latest={latest:<12} {r.detail}")
        worst_error = worst_error or r.status == "error"
    if not results:
        print("  (no sources declare a freshness policy)")
    return 1 if worst_error else 0


def cmd_docs(project: Project, args: argparse.Namespace) -> int:
    paths = write_docs(project)
    print("Wrote:")
    for p in paths:
        print(f"  {p}")
    return 0


def cmd_dag(project: Project, args: argparse.Namespace) -> int:
    models = discover_models(project)
    order = topological_order(models, project)
    print("Build order:")
    for i, m in enumerate(order, 1):
        deps = ", ".join(m.refs) or "-"
        print(f"  {i:>2}. {m.layer:<12} {m.name:<28} deps: {deps}")
    paths = write_docs(project)
    print(f"\nLineage graph written to {paths[0]}")
    return 0


def cmd_compile(project: Project, args: argparse.Namespace) -> int:
    models = discover_models(project)
    if args.model not in models:
        print(f"Unknown model '{args.model}'. Known: {', '.join(sorted(models))}")
        return 1
    with Warehouse(project) as wh:
        print(wh.compile_model(models[args.model]))
    return 0


def cmd_preview(project: Project, args: argparse.Namespace) -> int:
    relation = args.relation
    if "." not in relation:
        relation = f"{project.target_schema}.{relation}"
    with Warehouse(project) as wh:
        cols = wh.table_columns(relation)
        rows = wh.fetch(f"SELECT * FROM {relation} LIMIT {args.limit}")
    print(" | ".join(cols))
    print("-" * 80)
    for row in rows:
        print(" | ".join("" if v is None else str(v) for v in row))
    return 0


# -- entrypoint ----------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dw", description="duck-warehouse: a dbt-style ELT on DuckDB")
    parser.add_argument("--version", action="version", version=f"duck-warehouse {__version__}")
    parser.add_argument("--project", default="dw.yaml", help="path to dw.yaml (default: ./dw.yaml)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_seed = sub.add_parser("seed", help="load raw seed CSVs")
    p_seed.add_argument("--generate", action="store_true", help="regenerate sample CSVs first")
    p_seed.add_argument("--seed", type=int, default=7, help="RNG seed for data generation")
    p_seed.set_defaults(func=cmd_seed)

    p_run = sub.add_parser("run", help="build all models")
    p_run.add_argument("--select", nargs="*", metavar="SELECTOR",
                       help="dbt-style node selectors, e.g. stg_prices+ +dim_security")
    p_run.add_argument("--exclude", nargs="*", metavar="SELECTOR", help="selectors to exclude")
    p_run.add_argument("--full-refresh", action="store_true",
                       help="rebuild incremental models from scratch")
    p_run.set_defaults(func=cmd_run)

    p_test = sub.add_parser("test", help="run schema + source + data tests")
    p_test.add_argument("--select", nargs="*", metavar="SELECTOR",
                        help="restrict model tests to selected models")
    p_test.add_argument("--exclude", nargs="*", metavar="SELECTOR", help="selectors to exclude")
    p_test.add_argument("--store-failures", action="store_true",
                        help="write failing rows to reports/failures/")
    p_test.set_defaults(func=cmd_test)

    p_build = sub.add_parser("build", help="seed + run + test + docs")
    p_build.add_argument("--generate", action="store_true", help="regenerate sample CSVs first")
    p_build.add_argument("--seed", type=int, default=7, help="RNG seed for data generation")
    p_build.add_argument("--full-refresh", action="store_true",
                         help="rebuild incremental models from scratch")
    p_build.add_argument("--store-failures", action="store_true",
                         help="write failing rows to reports/failures/")
    p_build.set_defaults(func=cmd_build)

    p_export = sub.add_parser("export", help="write consumer-shaped CSVs")
    p_export.set_defaults(func=cmd_export)

    p_source = sub.add_parser("source", help="source utilities (freshness)")
    p_source.add_argument("source_command", choices=["freshness"], help="what to check")
    p_source.set_defaults(func=cmd_source)

    p_docs = sub.add_parser("docs", help="write lineage + catalog")
    p_docs.set_defaults(func=cmd_docs)

    p_dag = sub.add_parser("dag", help="print build order + write lineage")
    p_dag.set_defaults(func=cmd_dag)

    p_compile = sub.add_parser("compile", help="print a model's resolved SQL")
    p_compile.add_argument("model")
    p_compile.set_defaults(func=cmd_compile)

    p_preview = sub.add_parser("preview", help="show rows from a table/view")
    p_preview.add_argument("relation")
    p_preview.add_argument("--limit", type=int, default=10)
    p_preview.set_defaults(func=cmd_preview)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        project = load_project(args.project)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return args.func(project, args)


if __name__ == "__main__":
    raise SystemExit(main())
