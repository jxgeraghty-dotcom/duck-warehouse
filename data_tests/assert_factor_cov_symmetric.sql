-- The factor covariance matrix must be symmetric: cov(i, j) == cov(j, i).
select a.factor_i, a.factor_j, a.covariance, b.covariance as transposed
from {{ ref('mart_factor_covariance') }} a
join {{ ref('mart_factor_covariance') }} b
    on a.factor_i = b.factor_j
   and a.factor_j = b.factor_i
where abs(a.covariance - b.covariance) > 1e-9
