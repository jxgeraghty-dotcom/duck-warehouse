-- Each account's active weights must sum to 1.0 (within float tolerance).
select account_id, as_of_date, sum(weight) as weight_sum
from {{ ref('fct_portfolio_holdings') }}
group by account_id, as_of_date
having abs(sum(weight) - 1.0) > 1e-6
