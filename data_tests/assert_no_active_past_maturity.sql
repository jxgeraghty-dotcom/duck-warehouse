-- An instrument flagged active must not already be past its maturity date.
select security_id, name, maturity_date
from {{ ref('dim_security') }}
where is_active
  and is_past_maturity
