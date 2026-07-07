{{ config(materialized='table') }}
-- Macro series pivoted to one column per series, the wide shape the TAA
-- backtester's macro overlay expects.
select
    as_of_date,
    max(case when series_id = 'UST_10Y'  then series_value end) as ust_10y,
    max(case when series_id = 'UST_2Y'   then series_value end) as ust_2y,
    max(case when series_id = 'IG_OAS'   then series_value end) as ig_oas,
    max(case when series_id = 'HY_OAS'   then series_value end) as hy_oas,
    max(case when series_id = 'TBILL_3M' then series_value end) as tbill_3m,
    max(case when series_id = 'CPI_YOY'  then series_value end) as cpi_yoy
from {{ ref('stg_macro') }}
group by as_of_date
order by as_of_date
