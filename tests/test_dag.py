"""Unit tests for model discovery and DAG ordering."""

from __future__ import annotations

from pathlib import Path

import pytest

from warehouse.dag import Model, discover_models, topological_order


def _model(name: str, layer: str, refs: list[str]) -> Model:
    return Model(name=name, layer=layer, path=Path(name), raw_sql="", refs=refs)


def test_discover_models_finds_all_layers(project):
    models = discover_models(project)
    assert "stg_prices" in models
    assert "dim_security" in models
    assert models["dim_security"].layer == "marts"
    assert "stg_security_master" in models["dim_security"].refs


def test_topological_order_respects_dependencies(project):
    models = {
        "a": _model("a", "staging", []),
        "b": _model("b", "intermediate", ["a"]),
        "c": _model("c", "marts", ["b"]),
    }
    order = [m.name for m in topological_order(models, project)]
    assert order.index("a") < order.index("b") < order.index("c")


def test_cycle_is_detected(project):
    models = {
        "a": _model("a", "marts", ["b"]),
        "b": _model("b", "marts", ["a"]),
    }
    with pytest.raises(ValueError, match="Cycle detected"):
        topological_order(models, project)


def test_unknown_ref_raises(project):
    models = {"a": _model("a", "marts", ["missing"])}
    with pytest.raises(ValueError, match="unknown model 'missing'"):
        topological_order(models, project)


def test_real_project_builds_a_valid_dag(project):
    models = discover_models(project)
    order = topological_order(models, project)
    # every ref appears before the model that uses it
    seen: set[str] = set()
    for model in order:
        assert all(r in seen for r in model.refs), f"{model.name} built before its refs"
        seen.add(model.name)
