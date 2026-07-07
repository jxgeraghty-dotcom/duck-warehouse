-- Typed factor return time series (one row per factor per month).
select
    try_cast(as_of_date as date)        as as_of_date,
    trim(factor_id)                     as factor_id,
    try_cast(factor_return as double)   as factor_return
from {{ source('raw', 'factor_returns') }}
