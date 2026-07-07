{{ config(materialized='incremental', incremental_key='as_of_date') }}
-- Security-level monthly return fact, null returns dropped. Feeds the risk
-- monitor's covariance/tracking-error estimation and the asset-class indices.
--
-- Materialised incrementally: the first build loads the whole history; later
-- runs append only months newer than what is already stored, the pattern you
-- want for an append-only monthly snapshot instead of rebuilding every time.
-- Run `dw run --full-refresh` to rebuild from scratch.
select
    as_of_date,
    security_id,
    total_return
from {{ ref('int_security_returns') }}
where total_return is not null
{% if is_incremental() %}
  and as_of_date > (select max(as_of_date) from {{ this }})
{% endif %}
