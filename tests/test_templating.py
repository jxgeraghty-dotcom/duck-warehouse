"""Unit tests for the ref/source/config templating."""

from __future__ import annotations

from warehouse.templating import (
    extract_config,
    find_refs,
    find_sources,
    render,
    resolve_relation,
)


def test_extract_config_pulls_and_strips_block():
    config, body = extract_config("{{ config(materialized='table') }}\nselect 1")
    assert config == {"materialized": "table"}
    assert body.strip() == "select 1"


def test_extract_config_absent_is_noop():
    config, body = extract_config("select 1")
    assert config == {}
    assert body == "select 1"


def test_find_refs_ordered_and_deduped():
    sql = "select * from {{ ref('a') }} join {{ ref('b') }} join {{ ref('a') }}"
    assert find_refs(sql) == ["a", "b"]


def test_find_sources():
    assert find_sources("{{ source('raw', 'prices') }}") == [("raw", "prices")]


def test_render_resolves_ref_and_source(project):
    sql = "select * from {{ ref('stg_prices') }} p join {{ source('raw', 'prices') }} r"
    out = render(sql, project)
    assert "main.stg_prices" in out
    assert "raw.prices" in out
    assert "{{" not in out


def test_resolve_relation_handles_bare_ref_and_passthrough(project):
    assert resolve_relation("ref('dim_security')", project) == "main.dim_security"
    assert resolve_relation("source('raw', 'prices')", project) == "raw.prices"
    assert resolve_relation("some.raw_relation", project) == "some.raw_relation"
