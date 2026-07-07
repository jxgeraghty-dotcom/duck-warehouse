"""Minimal ``{{ ref() }}`` / ``{{ source() }}`` / ``{{ config() }}`` templating.

dbt uses full Jinja; this project only needs three constructs, so it resolves
them with small, well-scoped regexes instead of pulling in a template engine.
Keeping it explicit also makes the compiled SQL easy to reason about and easy to
show in ``dw compile`` output.

The grammar understood here:

    {{ config(materialized='table') }}     -> stripped, returns {'materialized': 'table'}
    {{ ref('stg_prices') }}                -> <target_schema>.stg_prices
    {{ source('raw', 'prices') }}          -> raw.prices

Anything else inside ``{{ ... }}`` is left untouched and will surface as a SQL
error, which is the behaviour we want: unknown macros should fail loudly.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from warehouse.project import Project

# A quoted string argument: 'foo' or "foo". Includes '+' and ',' so config
# values like incremental_strategy='delete+insert' and unique_key='a, b' parse.
_STR = r"""['"]([A-Za-z0-9_.\- +,]+)['"]"""

_CONFIG_RE = re.compile(r"\{\{\s*config\((?P<args>.*?)\)\s*\}\}", re.DOTALL)
_REF_RE = re.compile(rf"\{{\{{\s*ref\(\s*{_STR}\s*\)\s*\}}\}}")
_SOURCE_RE = re.compile(rf"\{{\{{\s*source\(\s*{_STR}\s*,\s*{_STR}\s*\)\s*\}}\}}")
_KWARG_RE = re.compile(rf"(\w+)\s*=\s*(?:{_STR}|(\w+))")


def extract_config(sql: str) -> tuple[dict[str, str], str]:
    """Pull a leading ``config()`` block out of *sql*.

    Returns the parsed key/value config and the SQL with the block removed.
    Only simple ``key='value'`` pairs are supported (that is all a model needs
    here: typically ``materialized``).
    """

    config: dict[str, str] = {}
    match = _CONFIG_RE.search(sql)
    if not match:
        return config, sql
    for kw in _KWARG_RE.finditer(match.group("args")):
        key = kw.group(1)
        value = kw.group(2) if kw.group(2) is not None else kw.group(3)
        config[key] = value
    cleaned = _CONFIG_RE.sub("", sql, count=1).lstrip("\n")
    return config, cleaned


def find_refs(sql: str) -> list[str]:
    """Return the model names referenced via ``ref()``, in order, de-duplicated."""

    seen: dict[str, None] = {}
    for m in _REF_RE.finditer(sql):
        seen.setdefault(m.group(1), None)
    return list(seen)


def find_sources(sql: str) -> list[tuple[str, str]]:
    """Return ``(schema, name)`` pairs referenced via ``source()``."""

    seen: dict[tuple[str, str], None] = {}
    for m in _SOURCE_RE.finditer(sql):
        seen.setdefault((m.group(1), m.group(2)), None)
    return list(seen)


_BARE_REF_RE = re.compile(rf"^\s*ref\(\s*{_STR}\s*\)\s*$")
_BARE_SOURCE_RE = re.compile(rf"^\s*source\(\s*{_STR}\s*,\s*{_STR}\s*\)\s*$")


def resolve_relation(expr: str, project: "Project") -> str:
    """Resolve a *bare* ``ref('x')`` / ``source('a','b')`` (no ``{{ }}``) to a
    relation. Used for the ``to:`` field of a relationships test, which — as in
    dbt — is written without the template braces. A plain string is passed
    through unchanged so a fully-qualified relation also works.
    """

    m = _BARE_REF_RE.match(expr)
    if m:
        return f"{project.target_schema}.{m.group(1)}"
    m = _BARE_SOURCE_RE.match(expr)
    if m:
        return project.source(m.group(1), m.group(2)).relation
    return expr.strip()


def render(sql: str, project: "Project") -> str:
    """Resolve ``ref``/``source`` calls to fully-qualified relations.

    Assumes any ``config()`` block has already been removed via
    :func:`extract_config`.
    """

    def _ref(m: re.Match[str]) -> str:
        return f"{project.target_schema}.{m.group(1)}"

    def _source(m: re.Match[str]) -> str:
        return project.source(m.group(1), m.group(2)).relation

    sql = _REF_RE.sub(_ref, sql)
    sql = _SOURCE_RE.sub(_source, sql)
    return sql


_THIS_RE = re.compile(r"\{\{\s*this\s*\}\}")
_INCREMENTAL_BLOCK_RE = re.compile(
    r"\{%\s*if\s+is_incremental\(\)\s*%\}(.*?)\{%\s*endif\s*%\}", re.DOTALL
)


def apply_incremental(sql: str, this_relation: str, is_incremental: bool) -> str:
    """Resolve the incremental constructs in a model.

    ``{{ this }}`` becomes the model's own relation, and any
    ``{% if is_incremental() %} ... {% endif %}`` block is kept only when the
    model is being appended to (the table already exists and this is not a
    full refresh); otherwise the block is dropped so the first build reads the
    whole history.
    """

    sql = _INCREMENTAL_BLOCK_RE.sub(lambda m: m.group(1) if is_incremental else "", sql)
    sql = _THIS_RE.sub(this_relation, sql)
    return sql
