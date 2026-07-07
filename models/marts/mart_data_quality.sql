{{ config(materialized='table') }}
-- A compact data-observability summary: one row per metric, computed from the
-- built models. This is the "continuous improvement of data infrastructure"
-- surface — freshness, completeness and integrity numbers you can trend over
-- time or alert on. metric_value is numeric; metric_detail carries context.
with metrics as (
    select 'securities_total' as metric,
           count(*)::double as metric_value,
           'instruments in dim_security' as metric_detail
    from {{ ref('dim_security') }}

    union all
    select 'securities_unrated',
           count(*) filter (where rating = 'NR')::double,
           'securities with no credit rating (equities/cash)'
    from {{ ref('dim_security') }}

    union all
    select 'prices_cleaned_to_null',
           count(*) filter (where close_price is null)::double,
           'price marks nulled by cleaning (bad/missing feed)'
    from {{ ref('stg_prices') }}

    union all
    select 'price_history_months',
           count(distinct as_of_date)::double,
           'distinct monthly snapshots in the price history'
    from {{ ref('stg_prices') }}

    union all
    select 'benchmark_weight_max_error',
           max(abs(wsum - 1.0)),
           'largest deviation of a benchmark weight-sum from 1.0'
    from (
        select benchmark_id, sum(weight) as wsum
        from {{ ref('fct_benchmark_weights') }}
        group by benchmark_id
    )

    union all
    select 'accounts_total',
           count(distinct account_id)::double,
           'accounts valued in fct_portfolio_holdings'
    from {{ ref('fct_portfolio_holdings') }}

    union all
    select 'aum_usd_millions',
           round(sum(market_value) / 1e6, 1),
           'total valued AUM across accounts, USD millions'
    from {{ ref('fct_portfolio_holdings') }}
)

select
    metric,
    metric_value,
    metric_detail,
    current_timestamp as computed_at
from metrics
order by metric
