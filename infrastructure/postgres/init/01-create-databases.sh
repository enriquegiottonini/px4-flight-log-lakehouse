#!/bin/bash
# Runs once, when the postgres-data volume is empty (official image convention).
# Creates one role + database per service so each only sees its own data.
# Changing passwords in .env later does NOT update existing roles: use ALTER ROLE, or `make reset`.
set -euo pipefail

create_db() {
  local name="$1" password="$2"
  # psql variables (:'pw') quote the password safely; it never touches the SQL text
  psql -v ON_ERROR_STOP=1 -v name="$name" -v pw="$password" \
       --username "$POSTGRES_USER" --dbname postgres <<'SQL'
CREATE ROLE :"name" LOGIN PASSWORD :'pw';
CREATE DATABASE :"name" OWNER :"name";
REVOKE ALL ON DATABASE :"name" FROM PUBLIC;
SQL
  echo "created role and database: $name"
}

create_db airflow    "$AIRFLOW_DB_PASSWORD"
create_db lakekeeper "$LAKEKEEPER_DB_PASSWORD"
