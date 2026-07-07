-- Sanity bound: no single monthly total return should exceed +/-100%. A breach
-- would point to a bad price pair surviving the cleaning step.
select as_of_date, security_id, total_return
from {{ ref('fct_security_returns') }}
where abs(total_return) > 1.0
