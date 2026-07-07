-- Every benchmark's weights must sum to 1.0 (within float tolerance) per date.
select benchmark_id, as_of_date, sum(weight) as weight_sum
from {{ ref('fct_benchmark_weights') }}
group by benchmark_id, as_of_date
having abs(sum(weight) - 1.0) > 1e-6
