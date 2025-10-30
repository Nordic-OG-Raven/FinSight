# FinSight - Financial Data Pipeline

Comprehensive ETL pipeline for SEC financial filings that extracts, normalizes, and validates 10,000-40,000 financial facts per company.

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

See [LOCAL_TESTING.md](./LOCAL_TESTING.md) for full instructions.

Quick start:
```bash
# Start PostgreSQL
docker-compose up postgres -d

# Install Python deps
cd api && pip install -r requirements.txt

# Pre-load sample data
python -c "from src.main import run_pipeline; run_pipeline(ticker='NVO', year=2024)"

# Start API
python main.py

# Start frontend (in /Users/jonas/Website/portfolio)
npm run dev
```

Visit: `http://localhost:3000/finsight`

## 🎬 Deployment

### Backend (Railway)

1. Create new project on Railway
2. Add PostgreSQL database
3. Deploy from GitHub (automatic on push)
4. Railway auto-provides `RAILWAY_POSTGRES_*` env vars

### Frontend (Vercel)

1. Already deployed as part of portfolio
2. Add `NEXT_PUBLIC_FINSIGHT_API` env var pointing to Railway API
3. Deploy with `vercel --prod`

See [DEPLOYMENT.md](./DEPLOYMENT.md) for detailed steps and resource management strategy.

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

```sql
CREATE TABLE financial_facts (
    id SERIAL PRIMARY KEY,
    company VARCHAR(10) NOT NULL,
    concept VARCHAR(500) NOT NULL,
    normalized_label VARCHAR(500),
    value NUMERIC,
    unit VARCHAR(50),
    period_start DATE,
    period_end DATE,
    fiscal_year_end DATE,
    instant_date DATE,
    context_id VARCHAR(500),
    decimals INTEGER,
    taxonomy VARCHAR(100),
    filing_type VARCHAR(10),
    filing_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

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
