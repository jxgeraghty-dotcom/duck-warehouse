{{ config(materialized='table') }}
-- Security-level monthly return fact, null returns dropped. Feeds the risk
-- monitor's covariance/tracking-error estimation and the asset-class indices.
select
    as_of_date,
    security_id,
    total_return
from {{ ref('int_security_returns') }}
where total_return is not null
