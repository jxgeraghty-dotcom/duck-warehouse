{{ config(severity='warn') }}
-- An instrument flagged active must not already be past its maturity date.
-- Severity is 'warn': a hit is worth investigating (a matured bond still marked
-- active) but should not stop the pipeline — a data-steward follow-up, not a
-- build breakage.
select security_id, name, maturity_date
from {{ ref('dim_security') }}
where is_active
  and is_past_maturity
