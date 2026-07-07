"""Model discovery and DAG construction.

A "model" is a single ``.sql`` file under ``models/<layer>/``. The layer (the
immediate sub-folder: ``staging`` / ``intermediate`` / ``marts``) decides the
default materialisation. Dependencies are inferred from ``ref()`` calls, giving
a directed acyclic graph that we topologically sort so every model is built
after the models it reads from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from warehouse.project import Project
from warehouse.templating import extract_config, find_refs, find_sources


@dataclass
class Model:
    """One SQL model plus the metadata parsed out of its file."""

    name: str
    layer: str
    path: Path
    raw_sql: str
    config: dict[str, str] = field(default_factory=dict)
    refs: list[str] = field(default_factory=list)
    sources: list[tuple[str, str]] = field(default_factory=list)

    def materialized(self, project: Project) -> str:
        """Resolve materialisation: explicit config wins, else the layer default."""

        return self.config.get("materialized") or project.materialization_for(self.layer)

    @property
    def relation(self) -> str:
        return self.name


def discover_models(project: Project) -> dict[str, Model]:
    """Parse every ``.sql`` file under the models directory into a :class:`Model`."""

    models: dict[str, Model] = {}
    if not project.models_dir.exists():
        return models

    for sql_path in sorted(project.models_dir.rglob("*.sql")):
        name = sql_path.stem
        layer = sql_path.parent.name
        text = sql_path.read_text(encoding="utf-8")
        config, body = extract_config(text)
        if name in models:
            raise ValueError(
                f"Duplicate model name '{name}': {sql_path} collides with "
                f"{models[name].path}. Model names must be globally unique."
            )
        models[name] = Model(
            name=name,
            layer=layer,
            path=sql_path,
            raw_sql=body,
            config=config,
            refs=find_refs(body),
            sources=find_sources(body),
        )
    return models


def _validate(models: dict[str, Model], project: Project) -> None:
    """Fail early on dangling refs and undeclared sources."""

    for model in models.values():
        for ref in model.refs:
            if ref not in models:
                raise ValueError(
                    f"Model '{model.name}' references unknown model '{ref}'. "
                    f"Check the ref() name and that {ref}.sql exists."
                )
        for schema, name in model.sources:
            project.source(schema, name)  # raises KeyError with a helpful message


def topological_order(models: dict[str, Model], project: Project) -> list[Model]:
    """Return models in dependency order (Kahn's algorithm).

    Ties are broken by (layer priority, name) so runs are deterministic and read
    top-to-bottom staging -> intermediate -> marts. Raises on cycles, naming the
    models still stuck in the cycle.
    """

    _validate(models, project)

    layer_rank = {"staging": 0, "intermediate": 1, "marts": 2}
    indegree = {name: 0 for name in models}
    dependents: dict[str, list[str]] = {name: [] for name in models}
    for model in models.values():
        for ref in model.refs:
            indegree[model.name] += 1
            dependents[ref].append(model.name)

    def sort_key(name: str) -> tuple[int, str]:
        return (layer_rank.get(models[name].layer, 99), name)

    ready = sorted((n for n, d in indegree.items() if d == 0), key=sort_key)
    order: list[Model] = []
    while ready:
        current = ready.pop(0)
        order.append(models[current])
        for dep in dependents[current]:
            indegree[dep] -= 1
            if indegree[dep] == 0:
                ready.append(dep)
        ready.sort(key=sort_key)

    if len(order) != len(models):
        stuck = sorted(set(models) - {m.name for m in order})
        raise ValueError(f"Cycle detected in model DAG among: {', '.join(stuck)}")
    return order


# -- node selection (dbt-style graph operators) --------------------------

def _dependents_map(models: dict[str, Model]) -> dict[str, list[str]]:
    dependents: dict[str, list[str]] = {name: [] for name in models}
    for model in models.values():
        for ref in model.refs:
            if ref in dependents:
                dependents[ref].append(model.name)
    return dependents


def _ancestors(name: str, models: dict[str, Model]) -> set[str]:
    """All models *upstream* of ``name`` (transitive refs)."""

    out: set[str] = set()
    stack = list(models[name].refs)
    while stack:
        cur = stack.pop()
        if cur in out or cur not in models:
            continue
        out.add(cur)
        stack.extend(models[cur].refs)
    return out


def _descendants(name: str, dependents: dict[str, list[str]]) -> set[str]:
    """All models *downstream* of ``name`` (transitive dependents)."""

    out: set[str] = set()
    stack = list(dependents.get(name, []))
    while stack:
        cur = stack.pop()
        if cur in out:
            continue
        out.add(cur)
        stack.extend(dependents.get(cur, []))
    return out


def _resolve_selector(token: str, models: dict[str, Model],
                      dependents: dict[str, list[str]]) -> set[str]:
    """Resolve one selector like ``stg_prices+`` / ``+dim_security`` / ``+m+``."""

    want_ancestors = token.startswith("+")
    want_descendants = token.endswith("+")
    base = token.strip("+")
    if base not in models:
        raise ValueError(
            f"Selector '{token}' matches no model. Known models: "
            f"{', '.join(sorted(models))}"
        )
    result = {base}
    if want_ancestors:
        result |= _ancestors(base, models)
    if want_descendants:
        result |= _descendants(base, dependents)
    return result


def select_nodes(models: dict[str, Model],
                 select: list[str] | None,
                 exclude: list[str] | None) -> set[str]:
    """Return the set of model names matched by ``select`` minus ``exclude``.

    Supports the core dbt graph operators: ``m`` (just m), ``m+`` (m and
    descendants), ``+m`` (m and ancestors), ``+m+`` (both). Multiple selectors
    union together.
    """

    dependents = _dependents_map(models)
    if not select:
        selected = set(models)
    else:
        selected = set()
        for token in select:
            selected |= _resolve_selector(token, models, dependents)
    for token in exclude or []:
        selected -= _resolve_selector(token, models, dependents)
    return selected
