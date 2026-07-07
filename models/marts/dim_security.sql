{{ config(materialized='table') }}
-- Conformed security dimension: the single source of truth for instrument
-- attributes used by every downstream tool (risk monitor, compliance engine).
select
    security_id,
    name,
    issuer,
    asset_class,
    sector,
    region,
    currency,
    rating,
    maturity_date,
    coupon_rate,
    effective_duration,
    is_active,
    is_past_maturity
from {{ ref('stg_security_master') }}
