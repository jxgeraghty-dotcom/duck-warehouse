"""Source freshness checks — the data-ops guardrail.

For every source that declares a ``loaded_at_field`` and thresholds in
``dw.yaml``, compare the newest value in the raw table against today and flag it
``pass`` / ``warn`` / ``error``. A stale feed is one of the most common (and
most silent) causes of a wrong number downstream, so this is the check you want
running before every build.
"""

from __future__ import annotations

from dataclasses import dataclass

from warehouse.runner import Warehouse


@dataclass
class FreshnessResult:
    source: str
    max_loaded_at: str | None
    age_days: int | None
    status: str          # "pass" | "warn" | "error" | "skip"
    warn_after_days: int | None
    error_after_days: int | None
    detail: str = ""


def check_freshness(warehouse: Warehouse) -> list[FreshnessResult]:
    """Evaluate the freshness policy for every source that declares one."""

    results: list[FreshnessResult] = []
    for src in warehouse.project.sources.values():
        if not src.has_freshness:
            continue
        try:
            row = warehouse.fetch(
                f"SELECT max(try_cast({src.loaded_at_field} AS DATE)), "
                f"       date_diff('day', max(try_cast({src.loaded_at_field} AS DATE)), "
                f"                 current_date) "
                f"FROM {src.relation}"
            )[0]
        except Exception as exc:  # noqa: BLE001 - surfaced as a skip
            results.append(FreshnessResult(src.name, None, None, "skip",
                                           src.warn_after_days, src.error_after_days,
                                           f"query failed: {exc}"))
            continue

        max_loaded, age = row
        if age is None:
            status, detail = "skip", "no dated rows"
        elif src.error_after_days is not None and age > src.error_after_days:
            status, detail = "error", f"{age}d old > {src.error_after_days}d limit"
        elif src.warn_after_days is not None and age > src.warn_after_days:
            status, detail = "warn", f"{age}d old > {src.warn_after_days}d warn"
        else:
            status, detail = "pass", f"{age}d old"
        results.append(FreshnessResult(
            src.name, str(max_loaded) if max_loaded is not None else None,
            int(age) if age is not None else None, status,
            src.warn_after_days, src.error_after_days, detail))
    return results
