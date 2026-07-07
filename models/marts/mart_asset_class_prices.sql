{{ config(materialized='table') }}
-- Cap-free, equal-weighted asset-class total-return indices (base 100),
-- pivoted wide. This is a genuine transformation — turning security returns
-- into asset-class series — that the TAA backtester consumes directly.
with ac_returns as (
    select
        r.as_of_date,
        d.asset_class,
        avg(r.total_return) as ac_return
    from {{ ref('fct_security_returns') }} r
    join {{ ref('dim_security') }} d using (security_id)
    group by 1, 2
),

indexed as (
    select
        as_of_date,
        asset_class,
        100.0 * exp(
            sum(ln(1 + ac_return)) over (partition by asset_class order by as_of_date)
        ) as index_level
    from ac_returns
)

select
    as_of_date,
    max(case when asset_class = 'Equity'     then index_level end) as eq_index,
    max(case when asset_class = 'Corporate'  then index_level end) as credit_index,
    max(case when asset_class = 'Government' then index_level end) as govt_index,
    max(case when asset_class = 'Cash'       then index_level end) as cash_index
from indexed
group by as_of_date
order by as_of_date
