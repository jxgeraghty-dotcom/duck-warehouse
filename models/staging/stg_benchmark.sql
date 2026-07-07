-- Raw benchmark constituent weights. Deliberately NOT normalised here: the feed
-- ships weights that sum to ~1.03, and re-basing them to exactly 1.0 is a
-- modelling decision made explicit in fct_benchmark_weights.
select
    try_cast(as_of_date as date)    as as_of_date,
    trim(benchmark_id)              as benchmark_id,
    trim(security_id)               as security_id,
    try_cast(weight as double)      as raw_weight
from {{ source('raw', 'benchmark') }}
