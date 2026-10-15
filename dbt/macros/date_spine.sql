{#- One row per day between two date expressions (inclusive), using Trino's sequence(). -#}
{% macro date_spine(start_date, end_date) -%}
    select d as date_day
    from unnest(sequence({{ start_date }}, {{ end_date }}, interval '1' day)) as t(d)
{%- endmacro %}
