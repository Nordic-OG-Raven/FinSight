-- Cross-company standardization (PRD §2.3): store edgartools' standard concept per concept, so
-- the Data Warehouse Explorer can group/compare different filers' (and IFRS vs US-GAAP) line
-- items on a common row. NULL for concepts edgartools doesn't standardize (niche / disclosure).
ALTER TABLE dim_concepts ADD COLUMN IF NOT EXISTS standard_label TEXT;
