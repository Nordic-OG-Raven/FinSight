{#
  Use the custom +schema value verbatim (bronze/silver/gold/seeds) instead of dbt's default
  "<target_schema>_<custom>" prefixing. We want clean, literal medallion schema names.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema | trim }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
