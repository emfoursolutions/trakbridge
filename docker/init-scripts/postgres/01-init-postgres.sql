-- PostgreSQL initialization script
-- This script runs when the PostgreSQL container starts for the first time

-- Create additional databases if needed
-- CREATE DATABASE trakbridge_db;

-- Create extensions if needed
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- CREATE EXTENSION IF NOT EXISTS "hstore";

-- Set up proper permissions
GRANT ALL PRIVILEGES ON DATABASE trakbridge_db TO postgres;