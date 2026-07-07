-- Staging must never emit a non-positive price; the raw negative mark should
-- have been cleaned to NULL rather than passed through.
select as_of_date, security_id, close_price
from {{ ref('stg_prices') }}
where close_price is not null
  and close_price <= 0
