"""Load and represent the ``dw.yaml`` project configuration.

Everything downstream (the runner, tests, docs) takes a :class:`Project`, so
this is the single place that knows the on-disk layout and the naming rules for
schemas. Paths in ``dw.yaml`` are resolved relative to the file itself, which
keeps the project runnable from any working directory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SourceDef:
    """A declared raw source: ``{{ source(schema, name) }}`` -> ``schema.name``.

    Optional freshness config (``loaded_at_field`` + ``warn_after_days`` /
    ``error_after_days``) lets ``dw source freshness`` flag stale feeds.
    """

    schema: str
    name: str
    seed: str  # CSV filename under the seeds directory
    loaded_at_field: str | None = None
    warn_after_days: int | None = None
    error_after_days: int | None = None

    @property
    def relation(self) -> str:
        return f"{self.schema}.{self.name}"

    @property
    def has_freshness(self) -> bool:
        return self.loaded_at_field is not None


@dataclass
class Project:
    """Resolved project configuration.

    Attributes mirror ``dw.yaml`` but with every path made absolute and every
    source flattened into :class:`SourceDef` records keyed by ``schema.name``.
    """

    root: Path
    name: str
    version: str
    database: Path
    raw_schema: str
    target_schema: str
    seeds_dir: Path
    models_dir: Path
    exports_dir: Path
    reports_dir: Path
    materializations: dict[str, str]
    sources: dict[str, SourceDef] = field(default_factory=dict)

    # -- source lookup ---------------------------------------------------
    def source(self, schema: str, name: str) -> SourceDef:
        key = f"{schema}.{name}"
        if key not in self.sources:
            raise KeyError(
                f"source('{schema}', '{name}') is not declared in dw.yaml "
                f"(known sources: {', '.join(sorted(self.sources)) or 'none'})"
            )
        return self.sources[key]

    def materialization_for(self, layer: str) -> str:
        return self.materializations.get(layer, "table")


def load_project(config_path: str | Path = "dw.yaml") -> Project:
    """Parse ``dw.yaml`` into a :class:`Project`.

    Raises a clear error if the file is missing so a mistyped path does not
    surface later as a confusing DuckDB failure.
    """

    path = Path(config_path).resolve()
    if not path.exists():
        raise FileNotFoundError(
            f"Project config not found: {path}. Run commands from the project "
            f"root or pass --project /path/to/dw.yaml."
        )

    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    root = path.parent
    paths = raw.get("paths", {})

    def _resolve(key: str, default: str) -> Path:
        return (root / paths.get(key, default)).resolve()

    sources: dict[str, SourceDef] = {}
    for schema, tables in (raw.get("sources") or {}).items():
        for name, meta in (tables or {}).items():
            meta = meta or {}
            fresh = meta.get("freshness") or {}
            sources[f"{schema}.{name}"] = SourceDef(
                schema=schema,
                name=name,
                seed=meta.get("seed", f"{name}.csv"),
                loaded_at_field=fresh.get("loaded_at_field"),
                warn_after_days=fresh.get("warn_after_days"),
                error_after_days=fresh.get("error_after_days"),
            )

    return Project(
        root=root,
        name=raw.get("name", "duck_warehouse"),
        version=str(raw.get("version", "0.0.0")),
        database=(root / raw.get("database", "warehouse.duckdb")).resolve(),
        raw_schema=raw.get("raw_schema", "raw"),
        target_schema=raw.get("target_schema", "main"),
        seeds_dir=_resolve("seeds", "seeds"),
        models_dir=_resolve("models", "models"),
        exports_dir=_resolve("exports", "exports"),
        reports_dir=_resolve("reports", "reports"),
        materializations=dict(raw.get("materializations", {})),
        sources=sources,
    )
