{{ config(materialized='table') }}
-- Security x factor exposure fact, restricted to securities that exist in the
-- conformed dimension (an inner join drops loadings for unknown instruments).
select
    e.security_id,
    e.factor_id,
    e.exposure
from {{ ref('stg_factor_exposures') }} e
join {{ ref('dim_security') }} d using (security_id)
