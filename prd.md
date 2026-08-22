# 📘 Product Requirements Document (PRD)
## Project: FinSight - Automated Financial Report Extraction & Analysis Pipeline

**Author:** Jonas  
**Date:** 2025-10-29 (last aligned to actual code: 2026-08-22)  
**Version:** v2.1  
**Status:** Active Development, local-only  
**Primary Goal:** Create an open-source, low-cost data pipeline that extracts, validates, and standardizes financial metrics from public company filings (XBRL & PDFs) for analysis and YouTube content generation.

> **Alignment note (2026-08-22)**: Sections 6, 7, and 13 below described an earlier flat-table
> schema and a simplified validation-rules list that no longer match the code. They've been
> corrected to point at the current, verified sources of truth instead of duplicating (and
> re-drifting from) that detail:
> - Schema & data model: [`docs/DATABASE.md`](docs/DATABASE.md), [`docs/ERD.md`](docs/ERD.md)
> - Pipeline stages & validation: [`docs/PIPELINE_AND_VALIDATION_MAP.md`](docs/PIPELINE_AND_VALIDATION_MAP.md)
>
> The project also went through a Railway → Azure hosting detour (§14 principle 2 originally
> called for local-first/API-optional) before Azure was shut down. It's back to local-only
> now, which is actually a return to this document's original intent, not a new direction.

---

## 1. 🎯 Goal & Motivation

Build an **end-to-end, low-cost, open-source data pipeline** that automatically extracts **comprehensive financial and operational data** from public company annual reports (10-K, 20-F, ESEF filings) into a structured data warehouse.

### Primary Goal: Data Extraction & Warehousing

This is a **DATA PIPELINE PROJECT** focused on:
- **Extracting ALL available data points** from financial reports (1000s of facts per filing)
- **Building a comprehensive data warehouse** for multi-dimensional financial analysis
- **Ensuring data quality, completeness, and provenance** for every extracted fact
- **Making data available** for any future analysis (forecasting, peer comparison, time-series, etc.)

### Three-Phase Approach:

**Phase 1: Deterministic Quantitative Extraction**
- Extract **all structured data** from XBRL filings (not just key KPIs)
- Comprehensive coverage: income statement, balance sheet, cash flow, segment data, footnotes
- 100% reproducible, auditable extraction

**Phase 2: LLM-Based Qualitative Extraction**
- Extract unstructured data: ESG metrics, strategy statements, risk factors
- Management commentary, forward-looking statements
- Board composition, governance metrics

**Phase 3: Automated Visualization Templates**
- Standardized but flexible analysis templates
- Quick-start dashboards for common analyses
- Focus on enabling analysis, not prescriptive visualizations

### Why This Project?

This is a **portfolio project** showcasing:
- **Data engineering** (robust ETL pipeline for complex documents)
- **Document intelligence** (XBRL parsing, schema normalization)
- **Data warehousing** (PostgreSQL design for financial time-series)
- **ML/NLP integration** (LLM-based text extraction)
- **Data quality engineering** (validation, provenance, completeness tracking)

---

## 2. 🧭 Scope

### In Scope (MVP - Phase 1)

1. **Ingestion & Document Management**
   - Parse **SEC** and **EU ESEF** filings (10-K, 20-F, ESEF ZIPs)
   - Download filings via **sec-api** or direct URLs
   - Auto-detect document type (XBRL vs PDF)
   - Cache downloaded filings for reproducibility

2. **Comprehensive XBRL Extraction**
   - Parse **ALL facts** from Inline XBRL using **Arelle**
   - Extract complete financial statements:
     - **Income Statement**: All line items (revenue, COGS, expenses, taxes, etc.)
     - **Balance Sheet**: All assets, liabilities, equity line items
     - **Cash Flow Statement**: All operating, investing, financing activities
     - **Segment Data**: Geographic and business segment breakdowns
     - **Footnotes & Disclosures**: Significant accounting policies, commitments
     - **Per-share Data**: EPS, dividends, shares outstanding
     - **Ratios & Metrics**: As reported by company
   - Extract temporal data: quarterly, annual, year-to-date
   - Capture **ALL contexts** (dimensions: segments, currencies, scenarios)
   - Target: **Extract 500-2000+ facts per filing** (vs selective 10-15)

3. **Data Normalization & Standardization**
   - Normalize units (thousands/millions) and currency across periods
   - Standardize concept labels across US-GAAP, IFRS, local taxonomies
   - **Taxonomy-Driven Normalization:**
     - Download official taxonomies (US-GAAP, IFRS, ESEF) with calculation and label linkbases
     - Extract concept synonyms from taxonomy labels (concepts with identical labels)
     - Use taxonomy-defined calculation relationships for component-to-total mapping
     - Manual curation of universal metrics (revenue, equity, liabilities) with accounting standards verification
     - Deterministic and auditable - every mapping documented and verified
   - Fiscal period alignment (calendar vs fiscal year end)
   - Handle scale conversions and unit consistency
   - **Financial Statement Ordering Strategy:**
     - **Primary Source**: XBRL `order_index` from presentation hierarchy (company's actual filing order)
       - Reflects the exact order as filed by the company according to their accounting standard
       - Works universally across IFRS, US-GAAP, and other standards
       - Respects company-specific and industry-specific ordering variations
     - **Fallback 1**: Infer `order_index` from other years (same company/statement/concept)
       - When XBRL extraction fails for a specific year (e.g., 2022), infer order from successful years (2023, 2024)
       - Maintains consistency across years while preserving company-specific structure
       - Flagged with `inferred_order=TRUE` for monitoring
     - **Fallback 2**: Standard accounting templates (IFRS/US-GAAP) when XBRL unavailable
       - Only used when XBRL data is completely missing or broken
       - Hardcoded ordering functions are fallback-only, not primary
     - **Balance Sheet Special Handling**: Sort by `side` (assets → liabilities_equity), then `order_index` within each side
       - Ensures assets appear before liabilities/equity regardless of XBRL order_index values
   - **Financial Statement Header Strategy:**
     - **Primary Source**: XBRL parent-child relationships (parent concepts with children but no facts)
       - Parent concepts in the presentation hierarchy that have child items but no numeric values serve as headers
       - Most authoritative - reflects the company's actual filing structure as defined in XBRL
       - Automatically works for all companies without hardcoding
     - **Secondary Source**: XBRL label roles (documentation role indicates headers)
       - Concepts with "documentation" label role in the XBRL label linkbase are treated as headers
       - Standard XBRL mechanism for identifying structural elements
       - Used when parent-child relationships don't provide headers
     - **Tertiary Source**: Standard accounting templates (IFRS/US-GAAP header patterns)
       - Industry-standard header patterns defined per accounting standard
       - Only used when XBRL doesn't provide headers
       - Configurable and maintainable (not hardcoded in application logic)
     - **Fallback**: Synthetic headers (only when XBRL unavailable and templates don't apply)
       - Created only when absolutely necessary for readability
       - Logged for monitoring to assess XBRL extraction quality
       - Flagged with `header_source='synthetic'` for tracking
     - **Header Characteristics**: Headers are structural elements with no numeric values
       - `value_numeric=NULL` in fact tables
       - Appear before their child items in display order
       - Used for grouping and readability (e.g., "Earnings per share", "Transactions with owners")
       - Maintains standard balance sheet presentation format

4. **Validation & Quality Assurance**
   - Validate **accounting identities** (Assets = Liabilities + Equity)
   - **Cross-statement validation** (net income → cash flow, etc.)
   - Detect duplicate or conflicting facts (user-facing duplicates flagged for manual review)
   - **Universal Metrics Completeness Check:**
     - Verify all companies have critical metrics (revenue, equity, liabilities, etc.)
     - Automatically suggest missing mappings from taxonomy labels (development tool)
     - Flag missing metrics for manual curation (not auto-fixed)
   - Calculate **completeness score** per filing (% of expected facts extracted)
   - Flag anomalies and outliers for review
   - Generate **data quality report** per filing
   - **Pipeline Integration:** Validation runs automatically after data loading

5. **Data Warehouse (PostgreSQL) - Hybrid ETL/ELT Architecture**
   - **ELT Staging Layer**: Raw extracted facts stored in `staging_facts` table
     - Enables debugging: Query raw data directly
     - Enables reprocessing: Re-run transformations without re-extracting
     - Preserves provenance: Original extraction method and metadata
   - **Transformation Layer**: Normalized facts in `fact_financial_metrics` (star schema)
     - Single source of truth for all financial data
     - Relational schema: facts, contexts, dimensions, provenance
     - Indexed for fast querying (company, period, concept)
   - **Presentation Layer**: Template-based views replace denormalized fact tables
     - `dim_statement_templates`: Canonical templates (80-90% standard items)
     - `rel_statement_overrides`: Filing-specific custom items (10-20%)
     - SQL functions: `get_income_statement()`, `get_balance_sheet()`, etc.
     - Benefits: No data duplication, no sync issues, headers in templates (not facts)
   - Support time-series analysis and cross-company comparison
   - Optional: Export to **Parquet** for portability/backup

6. **Provenance & Lineage Tracking**
   - Record source for **every fact**: concept ID, context, period, units
   - Document extraction method and confidence
   - Enable drill-down from any data point to source filing
   - Store document hash for version control

7. **CLI & Orchestration**
   - Scriptable **CLI**: `python src/main.py --ticker NVO --year 2024`
   - Batch mode for multiple companies
   - Progress tracking and logging
   - Error handling and retry logic

8. **Basic Data Viewer (Streamlit)**
   - Simple interface to browse extracted data
   - Filter by company, period, statement type
   - View provenance and validation results
   - Export to CSV/Excel
   - **Not a full dashboard** - just data exploration tool

---

### Optional (Phase 2)

1. **LLM-Based ESG Extraction**
   - Extract ESG & narrative metrics:
     - Scope 1/2/3 emissions
     - Gender diversity ratios
     - Sustainability targets
   - Use LLM-based document parser (Ollama + Mistral 7B / Claude / GPT API)
   - Apply to MD&A sections and sustainability reports

2. **PDF Fallback**
   - Handle **non-XBRL annual reports**
   - Use **PyMuPDF + Camelot + docTR** for table extraction
   - Target ≥90% accuracy for key KPIs (vs ≥98% for XBRL)

3. **Content Generation**
   - Generate **natural language summaries** (e.g., "Revenue grew 12% YoY...")
   - Auto-render charts for YouTube videos
   - Templated insight generation for video scripts

---

### Out of Scope (for MVP)
- Private company data
- Paid APIs (cloud OCR, commercial LLMs in Phase 1)
- Multi-language reports (English only in Phase 1)
- OCR for scanned PDFs (Phase 2 feature)
- Real-time market data integration
- **Pure EU companies filing only with ESMA** (not SEC-listed)
  - ESMA filings are distributed across 27+ national competent authority (NCA) websites
  - No centralized API like SEC EDGAR
  - Would require building/maintaining 27+ separate downloaders
  - Current solution: EU companies listed on US exchanges (20-F filers) work via SEC pipeline
  - **Future**: European Single Access Point (ESAP) launching 2026 will provide unified access

---

## 3. 👥 Users & Use Cases

### Primary User
**You** (Jonas) - BI/ML Engineer / Data Automation Developer

### End Goals
1. **Build a portfolio showcase** proving end-to-end automation & validation skills
2. **Generate YouTube videos** summarizing company performance automatically
3. **Demonstrate cross-company comparability** and data trustworthiness
4. **Showcase technical depth** in data engineering, document intelligence, and AI integration

### Potential Future Users
- **Financial Analysts**: Seeking automated, auditable KPI feeds
- **Retail Investors**: Wanting transparent financial comparisons
- **Data Journalists**: Needing reliable data for stories
- **Financial Content Creators**: Automating research for videos/articles

---

## 4. 🧱 System Architecture

### 🧩 High-Level Pipeline Flow (Hybrid ETL/ELT)

```
[1] Ingestion
    ↓
[2] Document Classification (detect XBRL / PDF)
    ↓
[3] XBRL Parser (Arelle) / PDF Parser (PyMuPDF + Camelot)
    ↓
[4] ELT Staging: Load raw facts to staging_facts
    ↓
[5] Transform: Normalize units, map concepts, create periods
    ↓
[6] Load: Store normalized facts in fact_financial_metrics (star schema)
    ↓
[7] Validation: Accounting identities, completeness checks
    ↓
[8] Presentation: Template-based views (get_income_statement(), etc.)
    ↓
[9] Visualization & Reporting (Streamlit / Superset)
    ↓
[10] Optional: LLM ESG Extractor (PDF or MD&A text)
```

**Key Architecture Features:**
- **ELT Staging**: Raw data preserved in `staging_facts` for debugging/reprocessing
- **Single Source of Truth**: All normalized data in `fact_financial_metrics`
- **Template-Based Presentation**: Headers/structure in templates, not fact tables
- **No Data Duplication**: Views query from `fact_financial_metrics`, not separate tables

### 🔧 Component Breakdown

| Step | Purpose | Tools / Libraries |
|------|---------|-------------------|
| **Ingestion** | Download filing (SEC API / ESEF URL) | `sec-api`, `requests`, `zipfile`, `beautifulsoup4` |
| **Classification** | Detect document type (XBRL vs PDF) | `mimetypes`, `magic`, simple filename regex |
| **XBRL Parsing** | Extract financial facts by tag | `Arelle` (CLI or Python API) |
| **PDF Parsing** | Fallback for non-XBRL reports | `PyMuPDF`, `Camelot`, `docTR`, `Tesseract` |
| **Normalization** | Currency, scale, fiscal period standardization | `pandas`, `decimal`, `pydantic` |
| **Validation** | Accounting and cross-statement checks | Custom Python functions + `pytest` |
| **Provenance** | Record source concept, taxonomy, period, units | Integrated metadata dictionary |
| **Storage (Structured)** | Financial facts database | `DuckDB`, `SQLite`, `Parquet` |
| **Visualization** | Dashboard & review UI | `Streamlit`, `Plotly`, `Altair` |
| **LLM Extraction** | ESG/narrative text extraction | `Ollama`, `OpenAI API`, `Claude`, `LlamaIndex` |
| **Automation** | Scheduled runs for new filings | `GitHub Actions`, `Prefect`, `cron` |

---

## 5. 🛠️ Technology Stack

| Layer | Technology | Reason | Cost |
|-------|------------|--------|------|
| **Language** | Python 3.10+ | Broad ecosystem, great for ETL + ML | Free |
| **Core ETL** | `Arelle`, `pandas`, `SQLAlchemy` | Reliable XBRL parsing, ORM for database | Free |
| **Ingestion** | `sec-api`, `requests`, `zipfile`, `beautifulsoup4` | Fetch & parse XBRL filings | Free |
| **Parsing (XBRL)** | `Arelle` (primary), `xmltodict` | Read ALL tagged facts from XBRL | Free |
| **Parsing (PDF)** | `PyMuPDF`, `Camelot`, `docTR`, `Tesseract` | Fallback for non-XBRL reports | Free |
| **Validation** | `pydantic`, `decimal`, `pytest` | Enforce schemas & numerical integrity | Free |
| **Data Warehouse** | **PostgreSQL** (Docker) | Primary storage, time-series analytics, Superset integration | Free |
| **Export Formats** | `Parquet`, `JSON`, `CSV` | Portable backups and data exchange | Free |
| **Data Viewer** | `Streamlit` (simple), `Plotly` | Quick data exploration during development | Free |
| **Production BI** | **Apache Superset** (Docker) | Professional dashboards, SQL interface | Free |
| **Automation** | `GitHub Actions`, `cron`, `run_pipeline.sh` | Scheduled extraction, orchestration | Free |
| **Testing** | `pytest`, `tox` | Ensure data quality and consistency | Free |
| **LLM (Phase 2)** | `Ollama` + Mistral 7B / `Claude` / `GPT API` | ESG/narrative extraction | $0–$20/month (optional) |

### Why These Tools?

- **PostgreSQL as data warehouse**: Relational database for complex queries, time-series, Superset integration
- **Comprehensive extraction**: Arelle extracts ALL XBRL facts, not selective parsing
- **Deterministic > Probabilistic**: Rule-based extraction for quantitative data, LLM only for qualitative
- **Production-ready**: PostgreSQL + Superset pattern proven in your other projects (chess_dashboard, business_analysis)
- **Data-first**: Storage and quality prioritized over visualization

---

## 6. 📊 Data Model

The data model evolved from an early flat `financial_facts` table into a proper star
schema (ELT staging → `fact_financial_metrics` as single source of truth → statement-specific
fact tables + template-based presentation views). That evolution is documented in
[`docs/ARCHITECTURE_MIGRATION.md`](docs/ARCHITECTURE_MIGRATION.md); the current schema
itself is documented in [`docs/DATABASE.md`](docs/DATABASE.md) and
[`docs/ERD.md`](docs/ERD.md) — 32 tables (dimension, fact, and relationship tables), not
reproduced here to avoid a second copy drifting out of sync with the schema again.

Provenance is still a first-class concern: every fact traces back to its filing, concept,
context, and extraction source (XBRL vs. SEC-API gap-fill) via `dim_filings`,
`dim_concepts`, and the `source` column on `fact_financial_metrics` — the JSON-blob
`provenance` field originally sketched below was superseded by this relational approach,
which is more queryable.

---

## 7. ✅ Validation Rules

The validation layer grew well beyond the 9-rule sketch originally in this section — it's
now ~24 distinct rules across 7 pipeline stages (in-memory pre-load checks, post-load
concept-mapping checks, cross-period consistency checks, and a final database-wide pass),
plus a UI-level test that verifies statements render correctly via the live API. Rather
than maintain a second, simplified description here that will drift out of sync the way
the old one did, the full accounting logic (balance check, cash flow reconciliation, EPS,
gross margin reasonableness, unit consistency, etc.), exactly where each check runs, and
its enforcement level (hard-fail vs. warning) are documented in
[`docs/PIPELINE_AND_VALIDATION_MAP.md`](docs/PIPELINE_AND_VALIDATION_MAP.md) — verified
against actual code execution, not just described from memory.

That document also tracks known open issues in the validation/loading layer (e.g. the
hard-fail gate not being fully transactional yet), which this PRD intentionally doesn't
duplicate — check there for current status rather than assuming everything below is live.

---

## 8. 🎯 Success Criteria

| Category | Metric | Target |
|-----------|---------|---------|
| **Extraction Completeness** | % of available XBRL facts extracted | ≥ 95% |
| **Data Volume** | Facts extracted per filing | 500-2000+ facts |
| **Accuracy (XBRL)** | Field-level precision vs source | ≥ 98% |
| **Accuracy (PDF)** | Field-level precision (Phase 2) | ≥ 90% |
| **Validation Coverage** | All facts have units, period, currency | 100% |
| **Provenance Coverage** | All facts traceable to source | 100% |
| **Data Quality Score** | Per-filing quality report | ≥ 0.90 |
| **Processing Speed** | Time per 10-K filing | < 2 minutes |
| **Database Coverage** | Companies with complete data | Broadened beyond the original pharma-peer focus — README lists 11 pre-loaded companies across sectors (tech, pharma, consumer). Revisit this target if pharma peer comparison is still the intended demo. |
| **Cost per Company** | Infrastructure + processing | $0 (free tools) |
| **Usability** | One-command extraction | ✅ CLI working |
| **Reproducibility** | Same input → same output | 100% |
| **Portfolio Value** | Demonstrates data engineering depth | ✅ |

---

## 9. 🚀 Timeline & Milestones

*(Historical — this was the original Week 1-5 MVP plan from Oct 2025. Actual development
ran well past this timeline and into deployment/debugging cycles not captured here; see
`docs/archive/` for that history. Kept below for the original scope breakdown, not as a
current schedule.)*

| Week | Goal | Deliverables |
|------|------|---------------|
| **Week 1** | **XBRL Ingestion & Parsing** | CLI + first JSON/Parquet dataset from Novo Nordisk (NVO) |
| **Week 2** | **Validation + Normalization** | Accounting checks, currency scaling, pydantic models |
| **Week 3** | **Dashboard & Provenance** | Streamlit app + provenance links, multi-company support |
| **Week 4** | **Automation + Demo Content** | Scheduled updates + auto summary generation |
| **Week 5+** | **ESG / AI Extension** | LLM-based ESG extraction & cross-company comparison |

### Detailed Milestone Breakdown

#### Week 1: Comprehensive XBRL Extraction
- Set up Python 3.10+ virtual environment (`/Users/jonas/FinSight/.venv`)
- Install and configure Arelle
- Extract **ALL facts** from Novo Nordisk 10-K (target: 500-2000 facts)
- Set up PostgreSQL database (`finsight` database)
- Store extracted facts with full provenance
- **Success**: Extract 500+ facts from single filing, stored in PostgreSQL

#### Week 2: Validation & Data Quality
- Build `pydantic` models for comprehensive fact schema
- Implement validation rules (balance check, cross-statement, completeness)
- Calculate data quality score per filing
- Add completeness tracking (% of available facts extracted)
- Unit tests for validation logic
- **Success**: Data quality score ≥ 0.90 for test filing

#### Week 3: Multi-company & Taxonomy Normalization
- Batch extract 6 pharma peers (NVO, LLY, SNY, PFE, MRNA, AZN)
- Handle US-GAAP vs IFRS taxonomy differences
- Normalize concept labels across taxonomies
- Build concept mapping dictionary
- **Success**: All 6 companies in PostgreSQL with normalized labels

#### Week 4: Data Viewer & Export
- Build simple Streamlit data viewer (filter, search, explore)
- Add export functionality (CSV, Parquet)
- Display data quality and provenance information
- Create `run_pipeline.sh` orchestration script
- **Success**: Easy data exploration and export

#### Week 5: Automation & Documentation
- GitHub Actions workflow for weekly filing checks
- Comprehensive documentation (README, architecture docs)
- Performance optimization (indexing, caching)
- **Success**: Automated weekly updates running

---

## 10. 🔮 Future Extensions (Phase 2+)

1. **LLM-Based ESG Extraction**
   - Use small local LLM (Llama 3.1 8B / Mistral 7B via Ollama) or Claude/GPT API
   - Target data:
     - CO₂ emissions (Scope 1/2/3)
     - Gender diversity metrics
     - Sustainability targets and commitments
     - Board composition
   - Apply to MD&A sections and standalone sustainability reports

2. **PDF Extraction Fallback**
   - Handle non-XBRL annual reports using:
     - PyMuPDF (text extraction)
     - Camelot (table parsing)
     - docTR (OCR for scanned pages)
     - Tesseract (backup OCR)
   - Target ≥90% accuracy for key KPIs

3. **YouTube Automation**
   - Generate natural language summaries ("Revenue grew 12% YoY...")
   - Auto-render charts and graphics
   - Generate video scripts with narration text
   - Optional: TTS integration (ElevenLabs, Azure Speech)
   - Optional: Auto-video creation (Lumen5 / ffmpeg)

4. **Advanced Analytics**
   - Time-series forecasting (ARIMA, Prophet)
   - Peer benchmarking and ranking
   - Margin analysis and trend detection
   - Anomaly detection for unusual financial patterns

5. **Multi-language Support**
   - Handle EU filings in German, French, Italian
   - Handle Asian filings (Chinese, Japanese)
   - Use translation APIs or multilingual LLMs

6. **Cloud Deployment**
   - Dockerized service for scalability
   - Deploy to Streamlit Cloud / Hugging Face Spaces
   - Optional: AWS Lambda for serverless extraction
   - Database backend (PostgreSQL, MongoDB)

7. **Fine-tuned LLM for Finance**
   - Train a small model specifically for financial entity extraction
   - Domain-specific ESG tagging
   - Custom NER for financial metrics

8. **API & Integration**
   - REST API for programmatic access
   - Webhook notifications for new filings
   - Integration with BI tools (Tableau, Power BI, Superset)

---

## 11. 💰 Cost Estimate

| Resource | Tool | Monthly Cost |
|-----------|------|---------------|
| **XBRL Parsing** | Arelle / sec-api | $0 |
| **Storage** | Local / DuckDB / Parquet | $0 |
| **Dashboard** | Streamlit (local or Streamlit Cloud) | $0 |
| **Automation** | GitHub Actions (2,000 free minutes/month) | $0 |
| **LLM (optional)** | Claude/GPT-4 for ESG | $5–20 (optional) |
| **OCR (optional)** | Tesseract / docTR | $0 |
| **Total (MVP)** | | **$0/month** |
| **Total (with LLM)** | | **$5–20/month** |

---

## 12. ⚠️ Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Filings change structure or taxonomy** | Medium | Maintain a small mapping dictionary for key concepts; monitor SEC taxonomy updates |
| **Inconsistent units/scales** | Medium | Parse "in thousands/millions" text explicitly; validate against expected ranges |
| **OCR errors on scanned PDFs** | Low (Phase 1 excludes scans) | Fallback to docTR or mark as "unverified"; manual review for critical data |
| **LLM hallucination (if used)** | Medium | Use constrained schema outputs + validation; require high confidence scores (≥0.8) |
| **API rate limits** | Low | Cache downloaded filings locally; implement exponential backoff |
| **XBRL tag variations** | Medium | Build canonical tag mappings (us-gaap, ifrs-full, dei); test across multiple companies |
| **Missing data fields** | High | Implement graceful fallbacks; flag missing fields in validation report |
| **Timezone/date parsing errors** | Low | Use ISO 8601 format; validate against fiscal year calendars |

---

## 13. 🧩 Repository Layout (Actual Structure)

The layout below reflects the real repo, not the originally-sketched one — it grew a
`database/` layer (the star schema loader) and an `api/` layer (Flask) that weren't in the
original plan. `src/storage/save_to_parquet.py` and `src/ui/dashboard.py` from the earlier
version of this section were never built as named; Parquet export lives at
`src/storage/export_queries.py` and the Streamlit viewer is `src/ui/data_viewer_v2.py`.

```
/FinSight
│
├── data/
│   ├── raw/                       # Downloaded XBRL files (cached per company/year)
│   └── processed/                 # Extracted facts as JSON, pre-load
│
├── src/
│   ├── ingestion/fetch_sec.py     # SEC filing downloader
│   ├── parsing/parse_xbrl.py      # XBRL extraction (Arelle wrapper)
│   ├── validation/                # 19 files — see docs/PIPELINE_AND_VALIDATION_MAP.md
│   ├── storage/export_queries.py  # Parquet/CSV export from the warehouse
│   ├── ui/data_viewer_v2.py       # Streamlit data viewer (local dev only)
│   ├── np2sql/                    # Optional natural-language-to-SQL (needs OPENAI_API_KEY)
│   ├── utils/                     # Normalization, taxonomy mapping, gap-filling, etc.
│   └── main.py                    # Two entrypoints — see map doc §1 for why that matters
│
├── database/
│   ├── schema.sql                 # Star schema DDL
│   ├── load_financial_data.py     # StarSchemaLoader — actual DB write path
│   └── migrations/                # Incremental schema changes
│
├── api/
│   └── main.py                    # Flask API — statements endpoints, pipeline trigger, NP2SQL
│
├── config/
│   ├── companies.yaml             # Tracked tickers
│   └── validation_rules.yaml      # Validation thresholds
│
├── tests/                         # Currently near-empty — see map doc §7 (no working suite)
│
├── docs/
│   ├── README.md                  # Docs index
│   ├── PIPELINE_AND_VALIDATION_MAP.md   # Canonical: pipeline stages + validator inventory
│   ├── DATABASE.md, ERD.md        # Schema reference
│   └── archive/                   # Historical design/debugging docs, not current truth
│
├── requirements.txt
├── run_pipeline.sh                # Shell orchestration (extract → load → API → UI test)
├── README.md
└── prd.md
```

---

## 14. 🧠 Key Design Principles

1. **Deterministic > Probabilistic**  
   Prioritize rule-based, auditable extraction over AI magic. XBRL parsing should be 100% reproducible.

2. **Local-first, API-optional**  
   Everything runs offline with open-source tools. APIs (sec-api, LLMs) are optional enhancements, not dependencies.
   *(This drifted for a while — a separately-hosted Next.js frontend and Railway→Azure
   paid hosting got added without ever being written into this PRD, then Azure was shut
   down. The project is local-only again as of 2026-08-22, which is a return to this
   principle, not a new decision. The only feature that needs a paid API is NP2SQL
   (`OPENAI_API_KEY`) — everything else, including the core extraction/validation/warehouse
   pipeline, runs with zero external cost.)*

3. **Provenance for Trust**  
   Every value must trace back to an identifiable source (XBRL concept, PDF page, LLM extraction). No "magic numbers."

4. **Validation by Default**  
   All extracted data goes through accounting checks. Flag anomalies, don't silently fail.

5. **Extendable Architecture**  
   ESG/LLM modules can slot in later without refactoring core logic. Clean separation of concerns.

6. **Reproducibility**  
   Same input → same output. Cache filings locally. Version all dependencies.

7. **Fail Gracefully**  
   Missing fields shouldn't crash the pipeline. Return partial results with confidence scores.

8. **Human-Readable Outputs**  
   JSON and Parquet should be directly inspectable. Include human-readable labels alongside technical tags.

---

## 15. 🏁 Deliverables (MVP Completion)

### MVP Deliverables (Phase 1)

- ✅ **Comprehensive data pipeline** extracting 500-2000+ facts per filing
- ✅ **PostgreSQL data warehouse** (`finsight` database) with complete schema
- ✅ **Command-line interface (CLI)**: `python src/main.py --ticker NVO --year 2024`
- ✅ **Batch processing**: `./run_pipeline.sh` for all companies
- ✅ **Data quality reports** with completeness and validation scores
- ✅ **Provenance tracking** for every extracted fact
- ✅ **Simple Streamlit data viewer** for exploration and export
- ✅ **Export functionality** (CSV, Parquet, JSON)
- ✅ **GitHub repo** with comprehensive documentation

### Phase 2 Deliverables (LLM Text Extraction)

- ⬜ LLM-based ESG metric extraction
- ⬜ Strategy statement and risk factor extraction
- ⬜ Management commentary analysis
- ⬜ PDF extraction fallback for non-XBRL reports

### Phase 3 Deliverables (Visualization Templates)

- ⬜ Superset dashboard templates for common analyses
- ⬜ Automated insight generation (YoY growth, peer comparison)
- ⬜ Standardized visualization templates
- ⬜ Export-ready analysis reports

### NP2SQL Feature (Natural Language to SQL)

- ✅ Natural language query interface
- ✅ OpenAI GPT-3.5 integration for SQL generation
- ✅ Auto-detection of company mentions and result types
- ✅ Multiple display formats (table, chart, number, list)
- ✅ SQL validation and read-only database access
- ✅ Comprehensive schema metadata for LLM context

---

## 16. 📝 Example MVP CLI Flow

Here's how the end-to-end pipeline works from the command line:

### Step 1: Fetch Filing

```bash
# Download SEC 10-K or 20-F filing
python src/ingestion/fetch_sec.py --ticker NVO --year 2024
```

**Output**: `data/raw/NVO_2024_10K.zip`

### Step 2: Parse XBRL (Extract ALL Facts)

```bash
# Extract ALL financial facts from XBRL (500-2000+ facts)
python src/parsing/parse_xbrl.py --input data/raw/NVO_2024_10K.zip
```

**Output**: Intermediate JSON with all extracted facts

### Step 3: Validate & Load to PostgreSQL

```bash
# Validate data and load to the star schema warehouse
python database/load_financial_data.py data/processed/NVO_2024_20F_facts.json
```

**Output**: 
- Data loaded to PostgreSQL (`finsight` database, `fact_financial_metrics` +
  statement-specific fact tables — see `docs/DATABASE.md`)
- Validation runs automatically as part of this step (hard-fails on critical issues —
  see `docs/PIPELINE_AND_VALIDATION_MAP.md` §3-4 for current caveats)

### Step 4: Explore Data (Optional)

```bash
# Launch simple Streamlit data viewer
streamlit run src/ui/data_viewer.py
```

**Output**: Browse extracted data at `http://localhost:8501`

### One-Command Pipeline

```bash
# Run entire pipeline with single command
python src/main.py --ticker NVO --year 2024

# Or batch process all companies
./run_pipeline.sh
```

**Output**: All data in PostgreSQL, ready for Superset analysis

### Query Data from PostgreSQL

```bash
# Check extraction results (local Postgres runs inside the existing superset_db
# container — see docs/PIPELINE_AND_VALIDATION_MAP.md for why that's the target
# rather than a dedicated container)
docker exec superset_db psql -U superset -d finsight -c \
  "SELECT c.ticker, COUNT(*) as fact_count
   FROM fact_financial_metrics f
   JOIN dim_filings fi ON f.filing_id = fi.filing_id
   JOIN dim_companies c ON fi.company_id = c.company_id
   GROUP BY c.ticker;"
```

---

## 17. 📋 Deliverable Summary

✅ **Deterministic, reproducible, and explainable pipeline**  
✅ **Free / open-source tooling only**  
✅ **Modular structure for Cursor-based development**  
✅ **Clean validation & provenance layer**  
✅ **Strong BI/ML portfolio project** (shows data, automation, AI versatility)

---

**End of Document**