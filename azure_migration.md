# Azure Migration Plan for FinSight

## Overview

This document outlines the migration plan for moving FinSight from Railway PostgreSQL to Azure Database for PostgreSQL Flexible Server. The migration will enable better scalability, cost predictability, and support for future data expansion (more companies, Denmark statistics, etc.).

## SSH Access in Azure

### Direct SSH to Database: **Not Available**

Azure Database for PostgreSQL **does not support direct SSH access** to the database server itself. This is by design for managed services - you connect via:
- **Connection strings** (standard PostgreSQL protocol)
- **Azure Portal** (query editor)
- **Azure CLI** (management commands)

### SSH Tunneling (If Needed)

If you need SSH tunneling for security or network restrictions, you can:

1. **Azure Bastion** (~$0.19/hour = ~$138/month)
   - Secure SSH to VMs
   - Can tunnel through a jump box VM
   - Overkill for database access

2. **Jump Box VM** (~$10-30/month)
   - Small Linux VM for SSH tunneling
   - Use `ssh -L` to tunnel database connections
   - Only needed if you have strict firewall requirements

**Recommendation:** You don't need SSH tunneling. Azure Database for PostgreSQL uses standard PostgreSQL connection strings (same as Railway), so your existing code will work without changes.

## Cost Estimation

### Current State (Railway)
- **Free tier**: Limited storage (~1GB)
- **Paid**: ~$5-20/month for small databases
- **At scale (100GB+)**: Would be expensive

### Azure Database for PostgreSQL Flexible Server

**Pricing Structure:**
- **Compute**: Billed per hour, charged monthly
- **Storage**: Billed separately based on provisioned storage
- **Backups**: Free backup storage = 100% of provisioned storage (additional backups charged)

#### Option 1: Burstable Tier (Recommended for Start)
- **B1ms** (1 vCore, 2GB RAM): **~$0.008/hour = ~$5.76/month**
- **B2s** (2 vCores, 4GB RAM): **~$0.016/hour = ~$11.52/month**
- **Storage**: $0.115/GB/month (provisioned storage, minimum 32GB included)
- **Best for**: Development, small production workloads, low-traffic sites
- **Limitations**: CPU throttling under sustained load (burst credits)

#### Option 2: General Purpose Tier (For Production Scale)
- **D2s_v3** (2 vCores, 8GB RAM): **~$0.12/hour = ~$86/month**
- **D4s_v3** (4 vCores, 16GB RAM): **~$0.24/hour = ~$172/month**
- **Storage**: $0.115/GB/month
- **Best for**: Production workloads, high query volume, consistent performance
- **No CPU throttling**: Consistent performance

#### Option 3: Memory Optimized (For Analytics)
- **E2s_v3** (2 vCores, 16GB RAM): **~$0.24/hour = ~$172/month**
- **Best for**: Large datasets, complex queries, analytics, in-memory operations

### Storage Costs (Beyond Included 32GB)
- **Storage pricing**: **$0.115/GB/month** (provisioned, not pay-per-use)
- **50GB total**: ~$5.75/month (50GB × $0.115)
- **100GB total**: ~$11.50/month
- **200GB total**: ~$23/month
- **500GB total**: ~$57.50/month
- **1TB total**: ~$115/month

**Note**: Storage is provisioned (you pay for what you allocate), not pay-per-use. You can scale up but not down.

### Estimated Monthly Costs

| Scenario | Database Tier | Storage | Compute | Storage Cost | **Total** |
|----------|--------------|---------|---------|--------------|-----------|
| **Current (small)** | B1ms | 32GB (included) | $5.76 | $0 | **~$6/month** |
| **Medium (50 companies)** | B2s | 50GB | $11.52 | $2.07 (18GB extra) | **~$14/month** |
| **Large (200 companies)** | D2s_v3 | 200GB | $86 | $19.32 (168GB extra) | **~$105/month** |
| **Very Large (1000+ companies + Denmark stats)** | D4s_v3 | 1TB | $172 | $111.32 (968GB extra) | **~$283/month** |

**Breakdown:**
- **Compute**: Hourly rate × 730 hours/month
- **Storage**: (Provisioned GB - 32GB) × $0.115/GB/month
- **Backups**: Free (100% of provisioned storage included)

### Additional Azure Services (Optional)

- **Azure App Service** (for Flask API): ~$13-55/month (Basic tier)
- **Azure Storage** (for file backups): ~$0.02/GB/month
- **Azure Monitor** (logging/metrics): Free tier available, then ~$2-10/month

### Cost Comparison Summary

| Provider | Small (32GB) | Medium (50GB) | Large (200GB) | Very Large (1TB) |
|----------|-------------|---------------|---------------|------------------|
| **Railway** | $5-20 | $50-100 | $200-400 | $500-1000+ |
| **Azure (Burstable B1ms)** | **~$6/month** | **~$8/month** | **~$25/month** | **~$118/month** |
| **Azure (Burstable B2s)** | **~$12/month** | **~$14/month** | **~$31/month** | **~$124/month** |
| **Azure (General Purpose D2s_v3)** | **~$86/month** | **~$88/month** | **~$105/month** | **~$198/month** |
| **Azure (General Purpose D4s_v3)** | **~$172/month** | **~$174/month** | **~$191/month** | **~$283/month** |
| **Supabase** | Free (500MB) | $25/month | $25/month | $25-100/month |
| **Neon** | Free (3GB) | Free-10/month | $20-50/month | $100-200/month |

**Key Insights:**
- **Azure Burstable is VERY cheap** for small-to-medium workloads (~$6-14/month)
- **Storage is the main cost driver** at scale ($0.115/GB/month)
- **General Purpose tier** is more expensive but provides consistent performance
- **Azure is competitive** especially at small scale (cheaper than Railway)
- **At very large scale (1TB)**, Azure becomes more expensive than Supabase/Neon

**Verdict:** Azure Burstable (B1ms/B2s) is excellent for small-to-medium workloads. For very large datasets (500GB+), consider Supabase or Neon for better cost efficiency.

## Migration Plan

### Phase 1: Preparation (Week 1)

#### 1.1 Azure Account Setup
- [ ] Create Azure account (free $200 credit for 30 days)
- [ ] Set up Azure subscription
- [ ] Install Azure CLI: `brew install azure-cli` (macOS) or download from Azure
- [ ] Login: `az login`

#### 1.2 Resource Planning
- [ ] Estimate current database size: `SELECT pg_database_size('finsight');`
- [ ] Choose Azure region (closest to users, e.g., `West Europe` or `East US`)
- [ ] Decide on tier: Start with **B2s Burstable** (~$30/month for 50GB)
- [ ] Plan for growth: Can scale up later without downtime

#### 1.3 Backup Current Database
```bash
# From Railway or local
pg_dump -h $RAILWAY_HOST -U $RAILWAY_USER -d $RAILWAY_DB -F c -f finsight_backup.dump
```

### Phase 2: Azure Database Creation (Week 1)

#### 2.1 Create Resource Group
```bash
az group create --name finsight-rg --location westeurope
```

#### 2.2 Create PostgreSQL Flexible Server
```bash
# Create server (B2s tier, 50GB storage)
az postgres flexible-server create \
  --resource-group finsight-rg \
  --name finsight-db \
  --location westeurope \
  --admin-user finsight_admin \
  --admin-password <secure-password> \
  --sku-name Standard_B2s \
  --tier Burstable \
  --storage-size 50 \
  --version 15 \
  --public-access 0.0.0.0-255.255.255.255  # Or restrict to specific IPs
```

#### 2.3 Configure Firewall Rules
```bash
# Allow your current IP (for migration)
az postgres flexible-server firewall-rule create \
  --resource-group finsight-rg \
  --name finsight-db \
  --rule-name AllowMyIP \
  --start-ip-address <YOUR_IP> \
  --end-ip-address <YOUR_IP>

# Allow Azure services (for App Service if you migrate API)
az postgres flexible-server firewall-rule create \
  --resource-group finsight-rg \
  --name finsight-db \
  --rule-name AllowAzureServices \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0
```

#### 2.4 Create Database
```bash
az postgres flexible-server db create \
  --resource-group finsight-rg \
  --server-name finsight-db \
  --database-name finsight
```

### Phase 3: Data Migration (Week 1-2)

#### 3.1 Test Connection
```bash
# Test connection from local machine
psql "host=finsight-db.postgres.database.azure.com port=5432 dbname=finsight user=finsight_admin password=<password> sslmode=require"
```

#### 3.2 Restore Database
```bash
# Restore from backup
pg_restore -h finsight-db.postgres.database.azure.com \
  -U finsight_admin \
  -d finsight \
  --no-owner \
  --no-privileges \
  -v finsight_backup.dump
```

#### 3.3 Verify Data
```sql
-- Check table counts
SELECT 
  'dim_companies' as table_name, COUNT(*) as count FROM dim_companies
UNION ALL
SELECT 'fact_financial_metrics', COUNT(*) FROM fact_financial_metrics
UNION ALL
SELECT 'dim_filings', COUNT(*) FROM dim_filings;
-- ... verify all tables
```

#### 3.4 Create Read-Only User (for NP2SQL)
```sql
-- Connect as admin
CREATE USER finsight_readonly WITH PASSWORD 'secure_readonly_password';
GRANT CONNECT ON DATABASE finsight TO finsight_readonly;
GRANT USAGE ON SCHEMA public TO finsight_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO finsight_readonly;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO finsight_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO finsight_readonly;
```

### Phase 4: Application Updates (Week 2)

#### 4.1 Update Environment Variables

**Railway Environment Variables (to replace):**
```bash
RAILWAY_POSTGRES_HOST=...
RAILWAY_POSTGRES_PORT=...
RAILWAY_POSTGRES_USER=...
RAILWAY_POSTGRES_PASSWORD=...
RAILWAY_POSTGRES_DB=...
```

**New Azure Connection String:**
```bash
# Option 1: Connection string (recommended)
DATABASE_URL=postgresql://finsight_admin:<password>@finsight-db.postgres.database.azure.com:5432/finsight?sslmode=require

# Option 2: Individual components (for backward compatibility)
POSTGRES_HOST=finsight-db.postgres.database.azure.com
POSTGRES_PORT=5432
POSTGRES_USER=finsight_admin
POSTGRES_PASSWORD=<password>
POSTGRES_DB=finsight
```

#### 4.2 Update `config.py`

The existing `config.py` already supports `DATABASE_URL`, so minimal changes needed:

```python
# config.py already handles DATABASE_URL - just update env vars
# No code changes required!
```

#### 4.3 Update Railway Environment Variables

In Railway dashboard:
1. Go to your project → Variables
2. Update `DATABASE_URL` to Azure connection string
3. Or update individual `RAILWAY_POSTGRES_*` vars (if using that path)
4. Redeploy service

#### 4.4 Test Application
- [ ] Test API endpoints: `/api/companies`, `/api/analyze`
- [ ] Test NP2SQL queries
- [ ] Verify all queries work correctly
- [ ] Check performance (should be similar or better)

### Phase 5: Cutover & Validation (Week 2)

#### 5.1 Final Data Sync (If Needed)
```bash
# If there were updates during migration, sync again
pg_dump -h $RAILWAY_HOST ... | pg_restore -h finsight-db.postgres.database.azure.com ...
```

#### 5.2 Update DNS/Connection Strings
- [ ] Update Railway `DATABASE_URL` to point to Azure
- [ ] Deploy updated backend
- [ ] Monitor for errors

#### 5.3 Validation Checklist
- [ ] All API endpoints respond correctly
- [ ] Natural language queries work
- [ ] Company analysis works
- [ ] Data warehouse explorer works
- [ ] No connection errors in logs
- [ ] Performance is acceptable (<2s for typical queries)

#### 5.4 Rollback Plan
- Keep Railway database running for 1 week
- If issues occur, revert `DATABASE_URL` in Railway
- Can switch back instantly

### Phase 6: Cleanup (Week 3)

#### 6.1 Decommission Railway Database
- [ ] Verify Azure migration is stable (1 week)
- [ ] Export final backup from Railway (safety)
- [ ] Delete Railway PostgreSQL service
- [ ] Update documentation

#### 6.2 Cost Optimization
- [ ] Monitor Azure costs for first month
- [ ] Adjust tier if needed (can scale up/down)
- [ ] Set up cost alerts in Azure Portal

## Connection String Format

### Azure PostgreSQL Connection String
```
postgresql://<admin-user>:<password>@<server-name>.postgres.database.azure.com:5432/<database-name>?sslmode=require
```

**Example:**
```
postgresql://finsight_admin:MySecurePass123@finsight-db.postgres.database.azure.com:5432/finsight?sslmode=require
```

### SSL Requirement
Azure requires SSL connections. Your existing PostgreSQL client libraries (psycopg2, SQLAlchemy) support this automatically when `sslmode=require` is in the connection string.

## Security Considerations

### 1. Firewall Rules
- Restrict to specific IPs (your deployment IPs)
- Use Azure Private Link for production (extra cost, better security)
- Remove public access if using Private Link

### 2. Authentication
- Use strong passwords (Azure enforces complexity)
- Consider Azure AD authentication (advanced)
- Rotate passwords regularly

### 3. Encryption
- Data encrypted at rest (automatic)
- Data encrypted in transit (SSL required)
- Backups encrypted automatically

## Monitoring & Maintenance

### Azure Portal Monitoring
- Database metrics: CPU, memory, storage, connections
- Query performance insights
- Slow query logs
- Cost tracking

### Alerts
Set up alerts for:
- High CPU usage (>80%)
- Storage approaching limit (>80%)
- Connection count high
- Cost threshold

### Backups
- **Automatic backups**: 7 days retention (included)
- **Point-in-time restore**: Available
- **Manual backups**: Use `pg_dump` or Azure Portal

## Scaling Strategy

### Vertical Scaling (Bigger Instance)
```bash
# Scale up (can be done with minimal downtime)
az postgres flexible-server update \
  --resource-group finsight-rg \
  --name finsight-db \
  --sku-name Standard_D2s_v3
```

### Horizontal Scaling (Read Replicas)
- Create read replicas for read-heavy workloads
- Cost: ~same as primary server
- Useful for: Analytics queries, NP2SQL (can route to replica)

### Storage Scaling
- Storage can be increased (but not decreased)
- Plan for growth: Start with 50GB, scale to 100GB, 200GB, etc.
- Cost: ~$0.10-0.15/GB/month

## Future Enhancements

### 1. Azure App Service (Optional)
- Migrate Flask API to Azure App Service
- Better integration with Azure Database
- Auto-scaling, deployment slots
- Cost: ~$13-55/month (Basic tier)

### 2. Azure Blob Storage (For File Storage)
- Store raw XBRL files, backups
- Cost: ~$0.02/GB/month
- Can integrate with pipeline

### 3. Azure Data Factory (For ETL)
- Orchestrate pipeline runs
- Schedule data loads
- Cost: Pay-per-use (~$1-5/month for small workloads)

### 4. Private Endpoint (For Production)
- Private network connection (no public IP)
- Better security
- Cost: ~$7/month per endpoint

## Migration Timeline

| Phase | Duration | Tasks |
|-------|----------|-------|
| **Phase 1: Preparation** | 1-2 days | Azure setup, backups, planning |
| **Phase 2: Database Creation** | 1 day | Create Azure database, configure |
| **Phase 3: Data Migration** | 1-2 days | Restore data, verify |
| **Phase 4: Application Updates** | 1 day | Update config, test |
| **Phase 5: Cutover** | 1 day | Switch connection, validate |
| **Phase 6: Cleanup** | 1 week | Monitor, then decommission Railway |
| **Total** | **~1-2 weeks** | Including testing and validation |

## Risk Mitigation

### Risks
1. **Data loss during migration**: Mitigated by backups and validation
2. **Downtime**: Minimal (just connection string update)
3. **Performance issues**: Test thoroughly before cutover
4. **Cost overruns**: Monitor costs, set alerts

### Rollback Plan
- Keep Railway database for 1 week post-migration
- Can revert connection string instantly
- No data loss risk (read-only during migration)

## Cost Optimization Tips

1. **Start with Burstable tier**: B2s is sufficient for most workloads
2. **Monitor storage growth**: Set alerts at 80% capacity
3. **Use reserved capacity**: 1-3 year commitments save 30-60%
4. **Scale down during low usage**: Can change tier (with brief downtime)
5. **Delete unused resources**: Clean up test databases

## Next Steps

1. **Review this plan** and adjust for your specific needs
2. **Create Azure account** and get $200 free credit
3. **Start with Phase 1** (preparation and backups)
4. **Test migration** in a non-production environment first
5. **Schedule cutover** during low-traffic period

## Support Resources

- **Azure Documentation**: https://docs.microsoft.com/azure/postgresql/
- **Azure Pricing Calculator**: https://azure.microsoft.com/pricing/calculator/
- **Azure Support**: Free tier includes community support
- **Migration Assistance**: Azure Database Migration Service (optional, paid)

## Questions to Consider

1. **Region**: Which Azure region is closest to your users?
2. **Tier**: Start with Burstable (B2s) or General Purpose (D2s_v3)?
3. **Storage**: How much storage do you need initially? (Can scale up)
4. **Backup retention**: 7 days (free) or longer (paid)?
5. **High availability**: Single server or high-availability setup? (+$100-200/month)

---

**Estimated Total Migration Cost**: $0 (using free Azure credit for first month)
**Estimated Monthly Cost After Migration**: 
- **Small scale**: ~$6/month (B1ms, 32GB)
- **Medium scale**: ~$14/month (B2s, 50GB)
- **Large scale**: ~$105/month (D2s_v3, 200GB)
- **Very large scale**: ~$283/month (D4s_v3, 1TB)

**Recommendation**: 
- **Start with B1ms Burstable** (~$6/month) - extremely cost-effective for small workloads
- **Scale to B2s** (~$14/month) when you need more CPU/memory
- **Scale to D2s_v3 General Purpose** (~$105/month) when you reach 100+ companies or need consistent performance
- **Consider Supabase/Neon** for very large datasets (500GB+) as they may be more cost-effective

**Cost Breakdown Example (B2s, 50GB):**
- Compute: $11.52/month (2 vCores, 4GB RAM)
- Storage: $2.07/month (18GB extra beyond 32GB included)
- **Total: ~$14/month** (much cheaper than initial estimate!)

