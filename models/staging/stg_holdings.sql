-- Typed account positions (share/par quantities per account and date).
select
    try_cast(as_of_date as date)    as as_of_date,
    trim(account_id)                as account_id,
    trim(security_id)               as security_id,
    try_cast(quantity as double)    as quantity
from {{ source('raw', 'holdings') }}
