"""Generate lightweight docs from the compiled project: lineage + a catalog.

Everything here is derived from the models themselves (their ``ref``/``source``
calls and the ``schema.yml`` descriptions), so the docs never drift from the
code. Output is plain Markdown/Mermaid that renders on GitHub.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from warehouse.dag import discover_models, topological_order
from warehouse.project import Project
from warehouse.runner import Warehouse


def _sanitize(node: str) -> str:
    return node.replace(".", "_").replace("-", "_")


def _descriptions(project: Project) -> dict[str, dict]:
    """Map model name -> {description, columns:{name: description}} from schema.yml."""

    out: dict[str, dict] = {}
    for schema_path in project.models_dir.rglob("schema.yml"):
        doc = yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}
        for model in doc.get("models", []) or []:
            cols = {c["name"]: c.get("description", "") for c in model.get("columns", []) or []}
            out[model["name"]] = {"description": model.get("description", ""), "columns": cols}
    return out


def build_lineage_mermaid(project: Project) -> str:
    """Render the model DAG (including sources) as a Mermaid graph."""

    models = discover_models(project)
    order = topological_order(models, project)
    lines = ["```mermaid", "graph LR"]

    # source nodes
    sources = {f"{sch}.{name}" for m in models.values() for sch, name in m.sources}
    for src in sorted(sources):
        lines.append(f'  {_sanitize(src)}["{src}"]:::source')

    for model in order:
        shape = "([%s])" if model.layer == "staging" else "[%s]"
        lines.append(f"  {_sanitize(model.name)}{shape % model.name}:::{model.layer}")

    for model in models.values():
        for sch, name in model.sources:
            lines.append(f"  {_sanitize(f'{sch}.{name}')} --> {_sanitize(model.name)}")
        for ref in model.refs:
            lines.append(f"  {_sanitize(ref)} --> {_sanitize(model.name)}")

    lines += [
        "  classDef source fill:#eee,stroke:#999,color:#333;",
        "  classDef staging fill:#e6f0ff,stroke:#4a7fd4;",
        "  classDef intermediate fill:#fff4e6,stroke:#d4913a;",
        "  classDef marts fill:#e8f7ec,stroke:#3aa563;",
        "```",
    ]
    return "\n".join(lines)


def build_catalog(project: Project) -> str:
    """Build a Markdown catalog of every model with tests and (if built) row counts."""

    models = discover_models(project)
    order = topological_order(models, project)
    descs = _descriptions(project)

    # row counts, best-effort (DB may not be built yet)
    counts: dict[str, int] = {}
    try:
        with Warehouse(project) as wh:
            existing = {
                r[0] for r in wh.fetch(
                    f"SELECT table_name FROM information_schema.tables "
                    f"WHERE table_schema = '{project.target_schema}'"
                )
            }
            for model in order:
                if model.name in existing:
                    counts[model.name] = wh.fetch(
                        f"SELECT count(*) FROM {project.target_schema}.{model.name}"
                    )[0][0]
    except Exception:  # noqa: BLE001 - docs must work pre-build
        pass

    lines = ["# Model catalog", "",
             f"Project **{project.name}** v{project.version} — "
             f"{len(models)} models across staging, intermediate and marts.", ""]

    for layer in ("staging", "intermediate", "marts"):
        layer_models = [m for m in order if m.layer == layer]
        if not layer_models:
            continue
        lines.append(f"## {layer}")
        lines.append("")
        for model in layer_models:
            meta = descs.get(model.name, {})
            rows = counts.get(model.name)
            rowtxt = f" · {rows:,} rows" if rows is not None else ""
            mat = model.materialized(project)
            lines.append(f"### `{model.name}` ({mat}{rowtxt})")
            if meta.get("description"):
                lines.append("")
                lines.append(meta["description"])
            deps = model.refs + [f"{s}.{n}" for s, n in model.sources]
            if deps:
                lines.append("")
                lines.append(f"*Depends on:* {', '.join(f'`{d}`' for d in deps)}")
            cols = meta.get("columns") or {}
            if cols:
                lines.append("")
                lines.append("| Column | Description |")
                lines.append("| --- | --- |")
                for cname, cdesc in cols.items():
                    lines.append(f"| `{cname}` | {cdesc} |")
            lines.append("")
    return "\n".join(lines)


def write_docs(project: Project) -> list[Path]:
    """Write dag.md and catalog.md into the reports directory."""

    project.reports_dir.mkdir(parents=True, exist_ok=True)
    dag_path = project.reports_dir / "dag.md"
    catalog_path = project.reports_dir / "catalog.md"
    dag_path.write_text("# Lineage graph\n\n" + build_lineage_mermaid(project) + "\n",
                        encoding="utf-8")
    catalog_path.write_text(build_catalog(project) + "\n", encoding="utf-8")
    return [dag_path, catalog_path]
