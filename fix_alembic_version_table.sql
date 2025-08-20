-- Drop the table if it exists
DROP TABLE IF EXISTS alembic_version;

-- Create with proper size
CREATE TABLE alembic_version (
    version_num VARCHAR(255) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);