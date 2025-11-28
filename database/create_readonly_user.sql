-- Create read-only user for NP2SQL queries
-- Run this script as a database superuser (e.g., postgres user)

-- Create user (if not exists)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_user WHERE usename = 'finsight_readonly') THEN
        CREATE USER finsight_readonly WITH PASSWORD 'change-me-in-production';
    END IF;
END
$$;

-- Grant connect privilege
GRANT CONNECT ON DATABASE finsight TO finsight_readonly;

-- Grant usage on schema
GRANT USAGE ON SCHEMA public TO finsight_readonly;

-- Grant SELECT on all existing tables
GRANT SELECT ON ALL TABLES IN SCHEMA public TO finsight_readonly;

-- Grant SELECT on all existing sequences
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO finsight_readonly;

-- Grant SELECT on all future tables (default privileges)
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO finsight_readonly;

-- Grant SELECT on all future sequences
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON SEQUENCES TO finsight_readonly;

-- Note: For Railway, you may need to set the password via environment variable:
-- NP2SQL_DB_PASSWORD=your-secure-password

