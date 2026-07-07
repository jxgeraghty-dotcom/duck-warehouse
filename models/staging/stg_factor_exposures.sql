-- Typed security x factor loadings (sparse: only relevant factors per security).
select
    trim(security_id)           as security_id,
    trim(factor_id)             as factor_id,
    try_cast(exposure as double) as exposure
from {{ source('raw', 'factor_exposures') }}
