{#-
  PX4 console messages. `message_template` replaces numbers and hex values with '#', so messages that
  differ only in values (one log produced 10k unique ERROR lines) can be counted together.
-#}
{{ config(materialized='incremental', incremental_strategy='append') }}

select
    log_id,
    t_boot_s,
    ts_utc,
    _log_date as uploaded_date,
    upper(level) as level,
    message,
    regexp_extract(message, '^\[([^\]]+)\]', 1) as module,
    trim(regexp_replace(
        regexp_replace(regexp_replace(message, '0x[0-9A-Fa-f]+', '#'), '[-+]?\d+(\.\d+)?', '#'),
        '\s+', ' ')) as message_template,
    _ingested_at
from {{ source('bronze', 'log_messages_raw') }}
{% if is_incremental() %}
where _ingested_at > (select max(_ingested_at) from {{ this }})
{% endif %}
