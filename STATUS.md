# Status

**State:** complete, self-contained vertical slice. `dw build --generate`
produces the full warehouse; `pytest` and `dw test` are green.

## What works

- **Mini-dbt engine** (`warehouse/`): `source`/`ref`/`config` templating, model
  discovery, DAG build with cycle + dangling-ref detection, layered
  view/table materialisation, schema + singular tests, docs, and exports —
  driven by the `dw` CLI.
- **19 models** across staging (8) → intermediate (2) → marts (9), built in
  dependency order against a local DuckDB file.
- **Deterministic sample feeds** (8 sources, ~40 instruments, 36 months) with
  injected defects that staging repairs.
- **40 declared data tests** (generic + singular) and **21 pytest tests** (unit
  + end-to-end), all passing.
- **7 consumer exports** matching the schemas the risk monitor, compliance
  engine and TAA backtester already read.
- **`mart_data_quality`** observability table + generated lineage/catalog docs.

## Verified

```
dw build --generate   -> 8 seeds, 19 models, 40/40 tests pass
pytest                -> 21 passed
dw export             -> 7 files written to exports/
```

## Deliberately out of scope

Incremental models, snapshots/SCD, full Jinja macros, and a real warehouse
adapter — noted under *Extending* in the README as the path to production. The
model SQL and tests are written so they carry over unchanged.

## Possible next steps

- Wire `export` output straight into a sibling tool's `data/` dir as a smoke
  test of the end-to-end handoff.
- Add source freshness thresholds and fail the build when a feed is stale.
- Add a `--select` flag to build/test a subgraph (dbt-style node selection).
