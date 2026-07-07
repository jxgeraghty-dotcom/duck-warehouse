{{ config(materialized='table') }}
-- Factor return fact (pass-through of the cleaned staging model, promoted to a
-- mart so downstream tools depend on the stable marts layer, not on staging).
select
    as_of_date,
    factor_id,
    factor_return
from {{ ref('stg_factor_returns') }}
