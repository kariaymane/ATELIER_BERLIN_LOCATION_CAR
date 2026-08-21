-- PostgreSQL initialization script
-- This runs only on first database creation

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Note: Tables are created by Alembic migrations, not this init script.
-- This file only ensures extensions are available.
