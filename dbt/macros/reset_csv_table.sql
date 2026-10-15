{#
  Seeds: truncate + insert into the same table (dbt-core's default), drop and recreate only with --full-refresh.
  dbt-trino overrides this to always drop: with Lakekeeper soft delete (setup.py) every dbt run would leave
  six dropped seed tables in silver's "deleted" list. This way a seed is one table with an Iceberg history.
#}
{% macro trino__reset_csv_table(model, full_refresh, old_relation, agate_table) %}
    {{ return(default__reset_csv_table(model, full_refresh, old_relation, agate_table)) }}
{% endmacro %}
