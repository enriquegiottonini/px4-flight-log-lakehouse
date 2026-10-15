-- What the ingestion did: one row per run and entity (from the audit tables).
select
    run_id,
    entity,
    status,
    started_at,
    finished_at,
    cast(duration_s as double) as duration_s,
    coalesce(read, 0) as records_read,
    coalesce(inserted, 0) as records_inserted,
    coalesce(updated, 0) as records_updated,
    coalesce(rejected, 0) as records_rejected,
    coalesce(bytes, 0) as bytes
from {{ source('audit', 'ingestion_runs') }}
