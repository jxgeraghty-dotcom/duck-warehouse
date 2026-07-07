-- The currency a price is quoted in must match the instrument's currency in
-- the security master. int_positions_valued converts market values using the
-- *master* currency, so a price quoted in a different currency would be
-- silently converted at the wrong rate.
select p.as_of_date, p.security_id, p.price_currency, sm.currency as master_currency
from {{ ref('stg_prices') }} p
join {{ ref('stg_security_master') }} sm using (security_id)
where p.price_currency is not null
  and p.price_currency <> sm.currency
