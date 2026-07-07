-- Every non-USD position must have an FX rate for its currency on its
-- valuation date. int_positions_valued falls back to parity (usd_per_unit ->
-- 1.0) when the rate is missing, so an uncovered position would be silently
-- misvalued in USD rather than failing loudly; this test is the loud failure.
select h.as_of_date, h.account_id, h.security_id, sm.currency
from {{ ref('stg_holdings') }} h
join {{ ref('stg_security_master') }} sm using (security_id)
left join {{ ref('stg_fx_rates') }} fx
    on fx.currency = sm.currency
   and fx.as_of_date = h.as_of_date
where sm.currency <> 'USD'
  and fx.usd_per_unit is null
