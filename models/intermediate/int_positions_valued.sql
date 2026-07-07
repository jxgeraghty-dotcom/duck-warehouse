-- Value each position at its as-of price and convert to USD via the FX table.
-- market_value_local is in the instrument's own currency; market_value is in USD
-- (base currency) so exposures across a multi-currency book are comparable.
with positions as (
    select
        h.as_of_date,
        h.account_id,
        h.security_id,
        h.quantity,
        p.close_price,
        sm.currency,
        sm.asset_class,
        sm.sector
    from {{ ref('stg_holdings') }} h
    join {{ ref('stg_prices') }} p
        on p.security_id = h.security_id
       and p.as_of_date = h.as_of_date
    join {{ ref('stg_security_master') }} sm
        on sm.security_id = h.security_id
)

select
    positions.*,
    quantity * close_price                              as market_value_local,
    quantity * close_price * coalesce(fx.usd_per_unit, 1.0) as market_value
from positions
left join {{ ref('stg_fx_rates') }} fx
    on fx.currency = positions.currency
   and fx.as_of_date = positions.as_of_date
