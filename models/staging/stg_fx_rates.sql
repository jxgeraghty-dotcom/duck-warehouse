-- Typed FX rates expressed as USD per one unit of the currency (USD -> 1.0).
select
    try_cast(as_of_date as date)        as as_of_date,
    upper(trim(currency))               as currency,
    try_cast(usd_per_unit as double)    as usd_per_unit
from {{ source('raw', 'fx_rates') }}
