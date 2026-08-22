# FinSight - Financial Data Pipeline

Comprehensive ETL pipeline for SEC financial filings that extracts, normalizes, and validates 10,000-40,000 financial facts per company.

> **Status (2026-08-22)**: Local-only. The Railway/Azure hosting described further down was
> shut down (cost, not a technical failure) — the pipeline, database, and API all run
> entirely on your machine now via Docker. See [`docs/PIPELINE_AND_VALIDATION_MAP.md`](docs/PIPELINE_AND_VALIDATION_MAP.md)
> for the verified, current pipeline/validator reference — it supersedes some of the detail
> below where they disagree. The "Live Demo" section describes a deployment that's no
> longer running; treat it as aspirational/historical, not a working link.

## 🎯 Project Goals

1. **Automate XBRL extraction** from SEC 10-K/20-F filings
2. **Normalize heterogeneous taxonomies** (US-GAAP, IFRS, company extensions)
3. **Validate accounting identities** across balance sheet, income statement, cash flow
4. **Build a data warehouse** for financial analysis and visualization
5. **Demonstrate production ETL** with quality assurance and observability

## 🏗️ Architecture

```
SEC EDGAR → XBRL Parser → Normalizer → Validator → PostgreSQL → Visualization
   (Arelle)     (Custom)     (Custom)   (SQLAlchemy)   (Superset)
```

### Pipeline Stages

1. **Ingestion**: Download filings from SEC EDGAR API
2. **Parsing**: Extract ALL XBRL facts using Arelle library
3. **Normalization**: 
   - Standardize units (millions, billions, shares)
   - Convert currencies to USD
   - Map concepts to normalized labels
   - Handle negative values and sign conventions
4. **Validation**:
   - Verify accounting identities (Assets = Liabilities + Equity)
   - Cross-statement consistency checks
   - Detect outliers and anomalies
5. **Storage**: Load into PostgreSQL with full provenance
6. **Query & Viz**: Apache Superset dashboards

## 📊 Data Scale

- **10,000-40,000** financial facts per company per year
- **~30 MB** per company in database
- **50+ companies** pre-loaded in dataset
- **Multiple taxonomies**: US-GAAP, IFRS, ESEF, company-specific extensions

## 🚀 Live Demo

- **Pre-loaded companies**: Instant analysis (<1s)
- **Custom analysis**: Full ETL pipeline (5-10 minutes)
- **Quota system**: 10 custom requests/month (free tier resources)
- **Visualization**: Interactive charts with Recharts
- **Superset**: Full BI dashboard for Novo Nordisk analysis

[**Try it live →**](https://jonashaahr.com/finsight)

## 🛠️ Tech Stack

- **Python 3.11**: Core pipeline
- **Arelle**: Industry-standard XBRL parser
- **PostgreSQL**: Data warehouse
- **Flask**: REST API
- **Next.js + Recharts**: Frontend visualization
- **Docker**: Local development
- **Railway**: Backend deployment (free tier)
- **Vercel**: Frontend deployment
- **Apache Superset**: BI dashboards

## 📦 Installation & Local Testing

Quick start (verified working 2026-08-22):
```bash
# Docker Desktop must be running first

# Postgres: this project shares the `superset_db` container (used by other local
# dashboard projects too) rather than running its own — it already has a `finsight`
# database with the star schema deployed. Check it's up:
docker ps | grep superset_db

# .env should point at it (already the default in .env.template):
# DATABASE_URL=postgresql://superset:superset@localhost:5432/finsight

# Python deps are in .venv already if you're picking this repo back up;
# otherwise: python3 -m venv .venv && .venv/bin/pip install -r api/requirements.txt

# Run the full pipeline for one company (extract → load → API → UI test)
./run_pipeline.sh AAPL 2024 10-K
```

The frontend (`Website/portfolio/app/finsight`) is a separate Next.js app that expects a
deployed backend URL — not part of local pipeline testing. Use the Streamlit viewer
(`./start_viewer.sh`) or query Postgres directly for local data exploration instead.

## 🎬 Deployment

Not currently deployed anywhere — running locally only (see status note at top). The
Railway → Azure → Fly.io hosting history is archived in
[`docs/archive/deployment-history/`](docs/archive/deployment-history/) if picking that back
up; `config.py`'s `DATABASE_URL` fallback chain still supports a Railway-style env var
setup without code changes if that path is revisited.

## 📈 Sample Companies

Pre-loaded companies (instant analysis):
- Novo Nordisk (NVO)
- NVIDIA (NVDA)
- Apple (AAPL)
- Alphabet (GOOGL)
- Microsoft (MSFT)
- Johnson & Johnson (JNJ)
- Pfizer (PFE)
- Eli Lilly (LLY)
- Moderna (MRNA)
- Sanofi (SNY)
- Coca-Cola (KO)

## 🔬 Key Features

### XBRL Extraction
- Parses Instance Documents (`.xml`)
- Handles Calculation and Presentation Linkbases
- Extracts ALL contexts (instant, duration, segments)
- Full provenance tracking (filing date, CIK, accession number)

### Normalization
- Maps 40,000+ unique concepts → ~200 normalized labels
- Handles unit conversions: shares, USD, percentages
- Resolves sign conventions (debits/credits)
- Taxonomy-agnostic: works with US-GAAP, IFRS, ESEF

### Validation
```python
# Balance Sheet Identity
assert total_assets == total_liabilities + total_equity

# Cash Flow Check
assert operating_cf + investing_cf + financing_cf == net_change_in_cash

# Income Statement
assert revenue - expenses == net_income
```

### Quality Assurance
- Automated validation on every load
- Logging with traceability
- Error handling and retry logic
- Database integrity constraints

## 📊 Database Schema

The schema is a 32-table star schema (dimension, fact, and relationship tables) — the flat
`financial_facts` table this section used to show was an early design that's since been
superseded. See [`docs/DATABASE.md`](docs/DATABASE.md) and [`docs/ERD.md`](docs/ERD.md) for
the current schema rather than duplicating it here.

## 🤝 API Endpoints

```bash
# Health check
GET /health

# List companies and quota status
GET /api/companies

# Get pre-loaded data (instant)
GET /api/analyze/{ticker}/{year}

# Custom analysis (5-10 min)
POST /api/analyze/custom
Body: {"ticker": "TSLA", "year": 2024}

# Natural language query (NP2SQL)
POST /api/query
Body: {"query": "Show me Apple's revenue in 2024"}

# Check quota
GET /api/quota
```

## 🎓 Learning Outcomes

This project demonstrates:
- End-to-end data engineering
- ETL pipeline design
- Data normalization across heterogeneous sources
- Quality assurance and validation
- REST API design
- Resource management (quota system)
- Full-stack deployment (Railway + Vercel)
- Documentation and testing

## 📝 Future Enhancements

- [ ] Multi-year comparative analysis
- [ ] Ratio calculations (P/E, ROE, debt-to-equity)
- [ ] Peer comparison module
- [ ] Excel export
- [ ] GraphQL API
- [ ] Real-time streaming (WebSockets)
- [ ] ML models for anomaly detection

## 🙏 Credits

- **Arelle**: David vun Kannon and contributors
- **US-GAAP Taxonomy**: FASB
- **IFRS Taxonomy**: IFRS Foundation
- **SEC EDGAR**: U.S. Securities and Exchange Commission

## 📧 Contact

**Jonas Haahr**  
[jonas.haahr@aol.com](mailto:jonas.haahr@aol.com)  
[Portfolio](https://jonashaahr.com)

---

*This project is part of my data engineering portfolio showcasing real-world ETL pipelines with quality assurance.*
