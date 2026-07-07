{{ config(materialized='table') }}
-- Valued holdings with active weights per account. weight is the USD market
-- value normalised within each (account, date), so weights sum to 1 per book
-- and feed straight into the compliance engine and the risk monitor.
select
    as_of_date,
    account_id,
    security_id,
    asset_class,
    sector,
    quantity,
    market_value_local,
    market_value,
    market_value
        / sum(market_value) over (partition by account_id, as_of_date) as weight
from {{ ref('int_positions_valued') }}
