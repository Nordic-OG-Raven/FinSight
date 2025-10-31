#!/bin/bash
# ============================================================================
# FinSight Database Initialization Script
# ============================================================================
# This script initializes the PostgreSQL data warehouse with proper schema
# ============================================================================

set -e

PROJECT_ROOT="/Users/jonas/FinSight"
cd "$PROJECT_ROOT"

echo "============================================================================"
echo "🏗️  FinSight Database Initialization"
echo "============================================================================"
echo ""

# Configuration
DB_HOST="127.0.0.1"
DB_PORT="5432"
DB_USER="superset"
DB_NAME="finsight"
SCHEMA_FILE="database/schema.sql"

echo "📋 Configuration:"
echo "  Database: $DB_NAME"
echo "  Host: $DB_HOST:$DB_PORT"
echo "  User: $DB_USER"
echo "  Schema: $SCHEMA_FILE"
echo ""

# Check if PostgreSQL is running
echo "🔍 Checking PostgreSQL connection..."
if ! docker exec superset_db psql -U "$DB_USER" -d postgres -c "SELECT 1;" &>/dev/null; then
    echo "❌ Cannot connect to PostgreSQL. Is the Docker container running?"
    echo "   Try: docker ps | grep superset_db"
    exit 1
fi
echo "✅ PostgreSQL is running"
echo ""

# Check if database exists, create if not
echo "🔍 Checking if database '$DB_NAME' exists..."
DB_EXISTS=$(docker exec superset_db psql -U "$DB_USER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME';")
if [ "$DB_EXISTS" != "1" ]; then
    echo "📦 Creating database '$DB_NAME'..."
    docker exec superset_db psql -U "$DB_USER" -d postgres -c "CREATE DATABASE $DB_NAME;"
    echo "✅ Database created"
else
    echo "✅ Database already exists"
fi
echo ""

# Backup existing data (if any)
echo "💾 Checking for existing data..."
TABLE_COUNT=$(docker exec superset_db psql -U "$DB_USER" -d "$DB_NAME" -tAc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';")
if [ "$TABLE_COUNT" -gt "0" ]; then
    BACKUP_FILE="database/backup_$(date +%Y%m%d_%H%M%S).sql"
    echo "⚠️  Found $TABLE_COUNT existing tables"
    echo "📦 Creating backup: $BACKUP_FILE"
    docker exec superset_db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP_FILE"
    echo "✅ Backup created"
else
    echo "✅ No existing data to backup"
fi
echo ""

# Apply schema
echo "🏗️  Applying database schema..."
if [ ! -f "$SCHEMA_FILE" ]; then
    echo "❌ Schema file not found: $SCHEMA_FILE"
    exit 1
fi

docker exec -i superset_db psql -U "$DB_USER" -d "$DB_NAME" < "$SCHEMA_FILE"
echo "✅ Schema applied successfully"
echo ""

# Verify schema
echo "🔍 Verifying schema..."
TABLE_COUNT=$(docker exec superset_db psql -U "$DB_USER" -d "$DB_NAME" -tAc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';")
VIEW_COUNT=$(docker exec superset_db psql -U "$DB_USER" -d "$DB_NAME" -tAc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='VIEW';")
echo "  Tables created: $TABLE_COUNT"
echo "  Views created: $VIEW_COUNT"
echo ""

# List all tables
echo "📊 Database structure:"
docker exec superset_db psql -U "$DB_USER" -d "$DB_NAME" -c "
SELECT 
    schemaname,
    tablename,
    CASE 
        WHEN tablename LIKE 'dim_%' THEN 'Dimension'
        WHEN tablename LIKE 'fact_%' THEN 'Fact'
        WHEN tablename LIKE 'v_%' THEN 'View'
        ELSE 'Metadata'
    END as table_type
FROM pg_tables 
WHERE schemaname='public'
ORDER BY table_type, tablename;
"
echo ""

# Show indexes
echo "🔍 Indexes created:"
docker exec superset_db psql -U "$DB_USER" -d "$DB_NAME" -c "
SELECT 
    tablename,
    indexname
FROM pg_indexes 
WHERE schemaname='public' 
ORDER BY tablename, indexname
LIMIT 20;
"
echo ""

echo "============================================================================"
echo "✅ Database initialization complete!"
echo "============================================================================"
echo ""
echo "Next steps:"
echo "  1. Load taxonomy mappings: ./database/load_taxonomy_mappings.sh"
echo "  2. Load financial data: ./database/load_financial_data.sh"
echo "  3. Validate data quality: /Users/jonas/FinSight/.venv/bin/python -m src.validation.checks"
echo ""

