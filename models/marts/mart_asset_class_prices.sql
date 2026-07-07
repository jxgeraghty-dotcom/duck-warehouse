{{ config(materialized='table') }}
-- Market-value-weighted asset-class total-return indices (base 100), pivoted
-- wide. Each security is weighted by its share of its asset class by current
-- market value (aggregated across accounts, via fct_portfolio_holdings), held
-- constant across history — a current-weights index, more defensible than an
-- equal-weighted one and reused directly by the TAA backtester.
with mv as (
    select security_id, sum(market_value) as mv
    from {{ ref('fct_portfolio_holdings') }}
    group by 1
),

weights as (
    select
        d.security_id,
        d.asset_class,
        mv.mv / sum(mv.mv) over (partition by d.asset_class) as wt
    from {{ ref('dim_security') }} d
    join mv using (security_id)
),

ac_returns as (
    -- renormalise by the weight actually present each month (a security with a
    -- missing return that month drops out and the rest are re-based)
    select
        r.as_of_date,
        w.asset_class,
        sum(r.total_return * w.wt) / nullif(sum(w.wt), 0) as ac_return
    from {{ ref('fct_security_returns') }} r
    join weights w using (security_id)
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
