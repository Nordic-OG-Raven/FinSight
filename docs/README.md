# Docs index

**Start here**: [`PIPELINE_AND_VALIDATION_MAP.md`](PIPELINE_AND_VALIDATION_MAP.md) — the
canonical, verified reference for how data actually flows through the pipeline and where
each validator fires. If any other doc disagrees with it, this one is right; update the
map rather than trusting the older doc.

## Live reference docs

- [`PIPELINE_AND_VALIDATION_MAP.md`](PIPELINE_AND_VALIDATION_MAP.md) — pipeline stages,
  validator inventory, known bugs. Verified against actual code execution, 2026-08-22.
- [`NVO_GOLDEN_PATH_2026-08.md`](NVO_GOLDEN_PATH_2026-08.md) — the active plan: finish
  making Novo Nordisk (the original reference company) correct end-to-end, with a real
  test guarding it, before broadening to other companies. Update in place as items close.
- [`DATABASE.md`](DATABASE.md) — star schema overview.
- [`ERD.md`](ERD.md) — entity relationship diagram for the warehouse.
- [`ARCHITECTURE_MIGRATION.md`](ARCHITECTURE_MIGRATION.md) — ETL→ELT / template-views
  migration background.
- [`TAXONOMY_NORMALIZATION.md`](TAXONOMY_NORMALIZATION.md) — how US-GAAP/IFRS concepts get
  mapped to normalized labels.
- [`NP2SQL.md`](NP2SQL.md) — the optional natural-language-to-SQL feature (requires
  `OPENAI_API_KEY`; everything else in this project runs without it).

These four (`DATABASE.md`, `ERD.md`, `ARCHITECTURE_MIGRATION.md`, `TAXONOMY_NORMALIZATION.md`)
were carried forward as still-relevant but **not independently re-verified** in the
2026-08-22 pass the way the pipeline map was — cross-check against the schema/code before
relying on specifics.

## `archive/`

Historical record, not current truth. Kept for context, not deleted, because some of it
(especially the 2022 investigation trail) contains real technical detail that matters if
that thread gets picked back up. Organized by topic:

- `deployment-history/` — Railway → Azure → Fly.io migration docs, local testing guide.
  All moot now that the project runs local-only; kept as a record of what was tried.
- `2022-completeness-investigation/` — the full debugging trail for the still-unresolved
  Novo Nordisk 2022 balance-sheet completeness gap, including a second-opinion exchange
  with Grok. Summarized with a leading hypothesis in `PIPELINE_AND_VALIDATION_MAP.md` §8;
  read these if picking that thread back up.
- `validation-design-history/` — plans, evaluations, and "why we built X" docs for the
  validation layer, largely superseded by `PIPELINE_AND_VALIDATION_MAP.md` now that it's
  been verified against actual execution rather than described from memory.
- `erd-design-history/` — design-decision and evaluation docs from building out the star
  schema. `ERD.md` itself is the live reference; these are the reasoning trail behind it.
