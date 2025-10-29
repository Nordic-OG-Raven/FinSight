# FinSight - Financial Data Warehouse Pipeline

**Comprehensive XBRL extraction pipeline for building a financial data warehouse from public company filings.**

## 🎯 Project Goals

FinSight is a data-first pipeline that:
- Extracts **ALL facts** (500-2000+ per filing) from XBRL financial reports
- Builds a **PostgreSQL data warehouse** for time-series analysis
- Ensures **100% provenance** and data quality tracking
- Supports multi-company, multi-taxonomy (US-GAAP, IFRS) analysis
- Enables downstream analysis in Superset, Python, or any SQL tool

**This is NOT a dashboard project** - visualization is secondary to comprehensive, high-quality data extraction.

## 📊 Current Status

**Phase 0: Project Setup** - ✅ IN PROGRESS

- [x] Virtual environment created
- [x] Dependencies installed
- [x] PostgreSQL database (`finsight`) created
- [x] Configuration files created
- [ ] Initial commit to Git

## 🏗️ Architecture

```
Raw XBRL Files
    ↓
Comprehensive Extraction (500-2000+ facts)
    ↓
Validation & Quality Checks
    ↓
PostgreSQL Data Warehouse
    ↓
Analysis (Superset, SQL, Python, Exports)
```

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- Docker Desktop (for PostgreSQL)
- Superset container running (`superset_db`)

### Installation

```bash
# 1. Navigate to project
cd /Users/jonas/FinSight

# 2. Activate virtual environment
source .venv/bin/activate

# 3. Verify installation
python -c "import arelle; print('Arelle installed successfully!')"

# 4. Verify database connection
docker exec superset_db psql -U superset -d finsight -c "SELECT 1;"
```

### Usage (Coming Soon)

```bash
# Extract single company
python src/main.py --ticker NVO --year 2024

# Batch extract all companies
./run_pipeline.sh

# View data
streamlit run src/ui/data_viewer.py
```

## 📁 Project Structure

```
FinSight/
├── data/
│   ├── raw/              # Downloaded XBRL files
│   ├── processed/        # Intermediate processing
│   └── reports/          # Quality reports
├── src/
│   ├── ingestion/        # SEC filing download
│   ├── parsing/          # XBRL extraction (ALL facts)
│   ├── validation/       # Data quality checks
│   ├── storage/          # PostgreSQL loading
│   ├── ui/               # Simple data viewer
│   └── utils/            # Helper functions
├── config/
│   ├── companies.yaml    # Target companies
│   └── validation_rules.yaml
├── tests/
├── config.py
├── requirements.txt
└── README.md
```

## 🎯 Success Criteria (MVP)

- Extract **500-2000+ facts** per filing
- Data quality score **≥ 0.85**
- **100% provenance** tracking
- **6+ companies** in data warehouse
- Processing time **< 2 minutes** per filing

## 📚 Documentation

- [PRD.md](./prd.md) - Product Requirements Document
- [IMPLEMENTATION.md](./IMPLEMENTATION.md) - Detailed implementation plan
- [docs/QUICKSTART.md](./docs/QUICKSTART.md) - Coming soon
- [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) - Coming soon

## 🗄️ Database

**PostgreSQL Database:** `finsight`  
**Connection (from Mac):** `postgresql://superset:superset@localhost:5432/finsight`  
**Connection (from Superset):** `postgresql://superset:superset@superset_db:5432/finsight`

## 🧪 Testing

```bash
# Run tests
pytest tests/

# With coverage
pytest --cov=src tests/
```

## 📦 Dependencies

- **Arelle** - XBRL parsing
- **PostgreSQL** - Data warehouse
- **SQLAlchemy** - Database ORM
- **Pandas** - Data manipulation
- **Pydantic** - Data validation
- **Streamlit** - Simple data viewer

## 📝 License

TBD

## 👤 Author

Jonas - [Portfolio](https://yourwebsite.com)

---

**Status:** 🚧 Under Active Development | **Phase:** Setup Complete | **Next:** Week 1 - XBRL Extraction

