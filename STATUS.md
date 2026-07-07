# Status

**State:** complete, self-contained vertical slice. `dw build --generate`
produces the full warehouse; `pytest` and `dw test` are green.

## What works

- **Mini-dbt engine** (`warehouse/`): `source`/`ref`/`config`/`this`/
  `is_incremental` templating, model discovery, DAG build with cycle +
  dangling-ref detection, **node selection** (`--select`/`--exclude`), layered
  **view/table/incremental** materialisation, schema + source + singular tests
  with **severities** and **`--store-failures`**, **source freshness** SLAs,
  docs, and exports — driven by the `dw` CLI.
- **20 models** across staging (8) → intermediate (2) → marts (10), built in
  dependency order against a local DuckDB file. `fct_security_returns` is
  incremental; `mart_factor_covariance` produces an annualised covariance matrix.
- **Deterministic sample feeds** (8 sources, ~40 instruments, 36 months) with
  injected defects that staging repairs; the EQ001 dedup keys on an `ingested_at`
  load timestamp.
- **49 declared data tests** (generic + source + singular) and **30 pytest
  tests** (unit + end-to-end + features), all passing.
- **8 consumer exports** + `scripts/handoff_smoke.py`, which loads each export
  back under the consuming tool's column contract.
- **`mart_data_quality`** observability table + generated lineage/catalog docs.
- **CI** (`.github/workflows/ci.yml`): lint + build + test + smoke on Python
  3.10–3.12.

## Verified

```
dw build --generate        -> 8 seeds, 20 models, 49/49 tests pass
dw source freshness        -> 6 sources fresh
pytest                     -> 30 passed
python scripts/handoff_smoke.py -> 8/8 exports load under contract
ruff check                 -> clean
```

## Deliberately out of scope

Snapshots/SCD-2, full Jinja macros, and a real warehouse adapter — noted under
*Extending* in the README as the path to production. The model SQL and tests are
written so they carry over unchanged.
