{{ config(materialized='table') }}
-- Benchmark weights re-based to sum to exactly 1.0 within each (benchmark, date).
-- This is the deliberate normalisation the staging layer left undone.
select
    as_of_date,
    benchmark_id,
    security_id,
    raw_weight
        / sum(raw_weight) over (partition by benchmark_id, as_of_date) as weight
from {{ ref('stg_benchmark') }}
