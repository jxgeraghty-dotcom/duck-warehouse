# Handoff — duck-warehouse (data pipeline demo)

A context snapshot for picking this up later. For how to *run* the project, see
[README.md](README.md); for the feature checklist, see [STATUS.md](STATUS.md).

## Goal

Build the "data pipeline demo": a dbt-style analytics warehouse on DuckDB that is
the **connective tissue** for the rest of the showcase portfolio. It models raw
investment feeds into clean, tested marts and hands each sibling tool (portfolio
risk monitor, compliance engine, TAA backtester) a file in the shape it already
consumes. The point is to demonstrate, to asset-management employers, the
usually-invisible data-infrastructure competency — sources → staging → marts,
tests, lineage, freshness — credibly standing in for Snowflake/Databricks work
without a cloud account.

Secondary goal (this session): make the whole showcase portfolio consistent —
CI + README badges + green builds across every repo.

## Current state

**duck-warehouse — complete and shipped.**
- Public repo: https://github.com/jxgeraghty-dotcom/duck-warehouse (default branch `main`).
- **CI green** on Python 3.10 / 3.11 / 3.12 (ruff + `dw build` + pytest + handoff smoke).
- 20 models (8 staging → 2 intermediate → 10 marts), 51 declared data tests,
  34 pytest tests, 8 consumer exports. `dw build --generate` and `pytest` both pass; ruff clean.
- Engine features: `source`/`ref`/`config`/`this`/`is_incremental` templating,
  DAG build with cycle detection, **node selection** (`--select`/`--exclude`),
  view/table/**incremental** materialisation, schema + source + singular tests
  with **severities** and `--store-failures`, **source freshness** SLAs, docs,
  and exports — all via the `dw` CLI.

**Sibling portfolio — all consistent and green.**
| Repo | State |
| --- | --- |
| [duck-warehouse](https://github.com/jxgeraghty-dotcom/duck-warehouse) | new this session; CI + 3 badges; green |
| [guideline-compliance-engine](https://github.com/jxgeraghty-dotcom/guideline-compliance-engine) | already had CI + badges; green |
| [portfolio-risk-monitor](https://github.com/jxgeraghty-dotcom/portfolio-risk-monitor) | already had CI + badges; green |
| [view-to-portfolio-translator](https://github.com/jxgeraghty-dotcom/view-to-portfolio-translator) | **CI build fixed** this session; green |
| [taa-backtest](https://github.com/jxgeraghty-dotcom/taa-backtest) | **CI added + MIT license added + badges** this session; green |

Every repo now carries a CI + License(MIT) + Python(3.10–3.12) badge set.

## Key decisions (and why)

- **Hand-rolled "mini-dbt" instead of installing dbt** — keeps deps to
  `duckdb` + `pyyaml`, runs anywhere, and makes the modelling mechanics legible
  (the goal is to *show* competency, not hide it behind a tool).
- **Raw seeds loaded as all-varchar** — the raw layer preserves whatever the
  feed sent (blanks, negatives, whitespace); every cast is explicit and testable
  in staging.
- **Marts = tables, staging/intermediate = views** — downstream tools read
  stable materialised marts; cheap upstream transforms recompute on demand.
- **Deterministic sample data (fixed RNG seed)** — reproducible, diff-friendly CSVs.
- **Incremental model keyed on `as_of_date`** (`fct_security_returns`) — appends
  new months instead of full rebuilds; `--full-refresh` forces a rebuild.
- **De-dup on an `ingested_at` load timestamp** — keeps the most recently loaded
  row per key, rather than an arbitrary tie-break.
- **Market-value-weighted asset-class index** — more defensible than equal-weight
  and reuses `fct_portfolio_holdings`.
- **Isolated nested git repo per project** — the home dir `C:/Users/User` is
  itself a catch-all git repo, so each showcase project gets its own repo.
- **TAA full backtest left out of CI** — `scripts/run_backtest.py` runs >6 min
  (bootstrap/walk-forward); pytest (incl. the no-look-ahead harness) is the gate.
- **v2p CI fix = mypy override to skip numpy stubs** — numpy ≥2.5 (only on
  Python 3.12+) uses PEP 695 `type` statements its stubs, which mypy rejects
  under `python_version = 3.10`, failing only the 3.12 job. Chosen over pinning
  numpy (fragile) or bumping the mypy target (would drop 3.10-compat checking).
- **taa-backtest licensed MIT** — it had no license; MIT matches the rest of the
  portfolio (confirmed with the user before adding the LICENSE file).

## Open questions / unresolved

- **Deferred dbt features** (noted in README → Extending): snapshots / SCD-2
  (e.g. rating migrations on `dim_security`), full Jinja macros, and a real
  warehouse adapter (Snowflake/Postgres) in place of DuckDB + CSV seeds.
- **Live end-to-end handoff** — `scripts/handoff_smoke.py` validates each export
  against its consumer's column contract *within* this repo; it does not yet
  drop a file straight into a sibling's `data/` dir and run that tool's loader.
- **Freshness in CI is advisory** — `dw source freshness` runs with `|| true`
  because the sample feeds are static (fixed to 2026-06-30, so they age in real
  time). A real deployment would enforce it and alert per source.
- **taa-backtest CI has no lint/type-check** — the project ships no ruff/mypy
  config, so CI runs pytest only; adding a lint gate is a possible follow-up.
- ~~Node.js 20 deprecation warnings on `actions/checkout` / `setup-python`~~ —
  resolved 2026-07-07: bumped to checkout@v5 / setup-python@v6 in every repo
  (portfolio-risk-monitor already had it).

## Files / artifacts

Within this repo (`Data pipeline demo/`):
- [README.md](README.md) — full design rationale + how to run.
- [STATUS.md](STATUS.md) — feature checklist and verification commands.
- `dw.yaml` — project config (sources, schemas, materialisations, freshness policy).
- `warehouse/` — the mini-dbt engine: `templating.py`, `dag.py`, `runner.py`,
  `tests.py`, `freshness.py`, `seeds.py`, `export.py`, `docs.py`, `cli.py`.
- `models/{staging,intermediate,marts}/` — the 20 SQL models + `schema.yml` tests.
- `data_tests/` — eight singular business-rule tests.
- `scripts/handoff_smoke.py` — loads every export back under its consumer contract.
- `seeds/` — the eight generated raw feeds (checked in).
- `tests/` — pytest suite (framework + data + features).
- `.github/workflows/ci.yml` — lint + build + test + smoke on 3.10–3.12.
- Build outputs (git-ignored): `warehouse.duckdb`, `exports/*.csv`,
  `reports/{dag.md,catalog.md,run_results.json}`.

Sibling repos this session touched:
- [view-to-portfolio-translator](https://github.com/jxgeraghty-dotcom/view-to-portfolio-translator)
  — `pyproject.toml` mypy override (the CI fix).
- [taa-backtest](https://github.com/jxgeraghty-dotcom/taa-backtest)
  — new `.github/workflows/ci.yml`, `LICENSE`, README badges, `pyproject.toml` license field.
