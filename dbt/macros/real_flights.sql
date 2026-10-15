{#- Gold excludes simulator (SITL) logs unless `--vars '{include_simulation: true}'`. -#}
{% macro real_flights(alias=none) -%}
    {%- if var('include_simulation') -%} true
    {%- else -%} not {{ alias ~ '.' if alias else '' }}is_simulation
    {%- endif -%}
{%- endmacro %}
