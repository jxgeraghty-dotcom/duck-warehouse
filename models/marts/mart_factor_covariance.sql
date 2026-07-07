{{ config(materialized='table') }}
-- Annualised factor return covariance matrix (long format), estimated from the
-- factor return history. Handing the risk monitor a ready covariance/correlation
-- matrix — rather than raw returns it must re-estimate — is exactly the kind of
-- reusable quant artifact a warehouse should own.
with fr as (
    select as_of_date, factor_id, factor_return
    from {{ ref('fct_factor_returns') }}
)

select
    a.factor_id                                   as factor_i,
    b.factor_id                                   as factor_j,
    count(*)                                      as n_obs,
    covar_samp(a.factor_return, b.factor_return) * 12.0 as covariance,   -- monthly -> annual
    corr(a.factor_return, b.factor_return)        as correlation
from fr a
join fr b on a.as_of_date = b.as_of_date
group by 1, 2
