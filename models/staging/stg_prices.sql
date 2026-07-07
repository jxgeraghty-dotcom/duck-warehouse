-- Typed price observations. Non-positive prices are data errors (a feed sent a
-- negative close) and blanks are missing marks; both become NULL here so the
-- returns logic and tests can treat "no valid price" uniformly.
select
    try_cast(as_of_date as date)                        as as_of_date,
    trim(security_id)                                   as security_id,
    case
        when try_cast(close_price as double) > 0 then try_cast(close_price as double)
    end                                                 as close_price,
    upper(trim(price_currency))                         as price_currency
from {{ source('raw', 'prices') }}
