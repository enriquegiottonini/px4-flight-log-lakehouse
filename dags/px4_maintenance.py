"""
### Lakehouse maintenance (weekly)

For every Iceberg table in bronze/silver/gold/audit, through Trino (connection `trino_default`, from `AIRFLOW_CONN_TRINO_DEFAULT`):
- `optimize`: compacts the many small files that daily appends create.
- `expire_snapshots`: drops snapshots older than 7 days. Time travel reaches back 7 days.
- `remove_orphan_files`: deletes files no snapshot references, e.g. from a commit conflict retry.

Runs Sunday 03:00 America/Hermosillo, after the 02:00 ingestion.
"""

from __future__ import annotations

from airflow.sdk import dag, task

from px4_common import DEFAULT_ARGS, START

RETENTION = "7d"
LAYERS = ("bronze", "silver", "gold", "audit")


@dag(
    dag_id="px4_maintenance",
    schedule="0 3 * * 0",
    start_date=START,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["px4", "maintenance"],
    doc_md=__doc__,
)
def px4_maintenance():
    @task
    def iceberg_tables() -> list[str]:
        from airflow.providers.trino.hooks.trino import TrinoHook

        layers = ", ".join(f"'{layer}'" for layer in LAYERS)
        rows = TrinoHook(trino_conn_id="trino_default").get_records(
            "SELECT table_schema || '.' || table_name FROM iceberg.information_schema.tables "
            f"WHERE table_schema IN ({layers}) AND table_type = 'BASE TABLE' ORDER BY 1")
        return [r[0] for r in rows]

    @task(max_active_tis_per_dagrun=2)
    def maintain(table: str) -> dict:
        from airflow.providers.trino.hooks.trino import TrinoHook

        hook, fq = TrinoHook(trino_conn_id="trino_default"), f"iceberg.{table}"
        schema, name = table.split(".")
        latest_snapshot = (f'SELECT snapshot_id, operation, element_at(summary, \'added-data-files\'), '
                           f'element_at(summary, \'deleted-data-files\') FROM iceberg.{schema}."{name}$snapshots" '
                           f'ORDER BY committed_at DESC LIMIT 1')
        before = hook.get_first(latest_snapshot)
        hook.run(f"ALTER TABLE {fq} EXECUTE optimize")
        after = hook.get_first(latest_snapshot)
        compacted = after is not None and before is not None and after[0] != before[0] and after[1] == "replace"
        hook.run(f"ALTER TABLE {fq} EXECUTE expire_snapshots(retention_threshold => '{RETENTION}')")
        hook.run(f"ALTER TABLE {fq} EXECUTE remove_orphan_files(retention_threshold => '{RETENTION}')")
        # optimize commits a 'replace' snapshot only when there was something to compact
        return {"table": table, "compacted": compacted,
                "files_removed": int(after[3] or 0) if compacted else 0,
                "files_added": int(after[2] or 0) if compacted else 0}

    maintain.expand(table=iceberg_tables())


px4_maintenance()
