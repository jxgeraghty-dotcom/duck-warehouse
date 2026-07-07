-- Clean the raw instrument master: this is where every piece of upstream mess
-- is repaired so downstream models can trust the data.
--   * trim stray whitespace on the key and de-duplicate, keeping the most
--     recently ingested row per key (a stale feed re-sent EQ001 with a leading
--     space and an older load timestamp)
--   * recover a blank asset_class from the security_id prefix
--   * normalise rating (trim/upper, blank -> 'NR') and currency (upper)
--   * cast numerics/dates safely with try_cast
with cleaned as (
    select
        trim(security_id)                                   as security_id,
        name,
        issuer,
        case
            when nullif(trim(asset_class), '') is not null then trim(asset_class)
            when starts_with(trim(security_id), 'EQ')      then 'Equity'
            when starts_with(trim(security_id), 'CB')      then 'Corporate'
            when starts_with(trim(security_id), 'GB')      then 'Government'
            when trim(security_id) = 'CASH'                then 'Cash'
        end                                                 as asset_class,
        gics_sector                                         as sector,
        region,
        upper(trim(currency))                               as currency,
        case
            when nullif(trim(rating), '') is null then 'NR'
            else upper(trim(rating))
        end                                                 as rating,
        try_cast(nullif(trim(maturity_date), '') as date)   as maturity_date,
        try_cast(coupon_rate as double)                     as coupon_rate,
        coalesce(try_cast(effective_duration as double), 0) as effective_duration,
        try_cast(inception_date as date)                    as inception_date,
        lower(trim(is_active)) in ('true', '1', 't', 'yes') as is_active,
        try_cast(ingested_at as timestamp)                  as ingested_at
    from {{ source('raw', 'security_master') }}
),

deduped as (
    select
        *,
        row_number() over (
            partition by security_id
            order by ingested_at desc nulls last, security_id
        ) as _rn
    from cleaned
)

select
    * exclude (_rn),
    (maturity_date is not null and maturity_date < current_date) as is_past_maturity
from deduped
where _rn = 1
