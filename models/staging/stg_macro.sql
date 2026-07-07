-- Typed macro series (yields, spreads, inflation) in long format.
select
    try_cast(as_of_date as date)        as as_of_date,
    trim(series_id)                     as series_id,
    try_cast(series_value as double)    as series_value
from {{ source('raw', 'macro') }}
