-- Monthly simple total returns per security, computed from the cleaned price
-- series. Rows with no valid prior price (first observation, or a gap left by a
-- cleaned bad mark) yield a NULL return and are filtered downstream.
select
    as_of_date,
    security_id,
    close_price,
    close_price
        / lag(close_price) over (partition by security_id order by as_of_date)
        - 1                                     as total_return
from {{ ref('stg_prices') }}
where close_price is not null
