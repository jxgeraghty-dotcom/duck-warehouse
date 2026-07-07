{{ config(materialized='incremental', incremental_strategy='delete+insert', unique_key='as_of_date') }}
-- Security-level monthly return fact, null returns dropped. Feeds the risk
-- monitor's covariance/tracking-error estimation and the asset-class indices.
--
-- Materialised incrementally with a delete+insert strategy: the first build
-- loads the whole history; later runs reprocess every month >= the newest
-- month already stored, replacing those rows (keyed on as_of_date) rather
-- than appending. New months arrive as before, and a *restated* price in the
-- newest stored month is picked up instead of being silently ignored — the
-- usual failure mode of a pure `>` append filter. Widen the window here if
-- the feed can restate deeper history. Run `dw run --full-refresh` to
-- rebuild from scratch.
select
    as_of_date,
    security_id,
    total_return
from {{ ref('int_security_returns') }}
where total_return is not null
{% if is_incremental() %}
  and as_of_date >= (select max(as_of_date) from {{ this }})
{% endif %}
