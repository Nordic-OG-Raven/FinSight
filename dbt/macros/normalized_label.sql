{#
  Reproduce the legacy loader's normalized_label: the canonical cross-taxonomy label when a core
  line, otherwise a snake_case of the concept local-name (mirror of
  database/load_from_edgartools.py::_snake). Used by the gold serving views so the API's
  normalized_label column matches what the retired star schema served.
#}
{% macro normalized_label(concept_col, canonical_col) %}
  coalesce(
    {{ canonical_col }},
    nullif(
      trim(both '_' from lower(regexp_replace(
        regexp_replace(split_part({{ concept_col }}, ':', 2), '([a-z0-9])([A-Z])', '\1_\2', 'g'),
        '[^a-zA-Z0-9]+', '_', 'g'
      ))),
      ''
    )
  )
{% endmacro %}
