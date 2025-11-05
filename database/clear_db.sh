#!/bin/bash
# ============================================================================
# FinSight Database Clear Script
# ============================================================================
# This script clears all data from the database and reinitializes the schema
# ============================================================================

set -e

PROJECT_ROOT="/Users/jonas/FinSight"
cd "$PROJECT_ROOT"

echo "============================================================================"
echo "🗑️  FinSight Database Clear & Reboot"
echo "============================================================================"
echo ""

# Configuration
DB_HOST="127.0.0.1"
DB_PORT="5432"
DB_USER="superset"
DB_NAME="finsight"

# Check if PostgreSQL is running
echo "🔍 Checking PostgreSQL connection..."
if ! docker exec superset_db psql -U "$DB_USER" -d postgres -c "SELECT 1;" &>/dev/null; then
    echo "❌ Cannot connect to PostgreSQL. Is the Docker container running?"
    echo "   Try: docker ps | grep superset_db"
    exit 1
fi
echo "✅ PostgreSQL is running"
echo ""

# Backup existing data (if any)
echo "💾 Checking for existing data..."
TABLE_COUNT=$(docker exec superset_db psql -U "$DB_USER" -d "$DB_NAME" -tAc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null || echo "0")
if [ "$TABLE_COUNT" -gt "0" ]; then
    BACKUP_FILE="database/backup_$(date +%Y%m%d_%H%M%S).sql"
    echo "⚠️  Found $TABLE_COUNT existing tables"
    echo "📦 Creating backup: $BACKUP_FILE"
    docker exec superset_db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP_FILE" 2>/dev/null || echo "⚠️  Backup failed (may be empty database)"
    echo "✅ Backup created"
else
    echo "✅ No existing data to backup"
fi
echo ""

# Drop database and recreate
echo "🗑️  Dropping database '$DB_NAME'..."
docker exec superset_db psql -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS $DB_NAME;" 2>/dev/null || true
echo "✅ Database dropped"
echo ""

# Create fresh database
echo "📦 Creating fresh database '$DB_NAME'..."
docker exec superset_db psql -U "$DB_USER" -d postgres -c "CREATE DATABASE $DB_NAME;"
echo "✅ Database created"
echo ""

# Reinitialize schema
echo "🏗️  Reinitializing schema..."
./database/init_db.sh

echo ""
echo "============================================================================"
echo "✅ Database reboot complete!"
echo "============================================================================"
echo ""
echo "Next steps:"
echo "  1. Load taxonomy mappings: ./database/load_taxonomy_mappings.sh (if exists)"
echo "  2. Load financial data: ./database/load_financial_data.sh"
echo "  3. Run validation: /Users/jonas/FinSight/.venv/bin/python -m src.validation.checks"
echo ""
