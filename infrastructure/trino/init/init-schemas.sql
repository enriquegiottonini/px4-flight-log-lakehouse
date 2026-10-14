-- Lakehouse namespaces (Iceberg namespaces in Lakekeeper). Idempotent.
-- Explicit locations: otherwise every namespace defaults to the warehouse root (s3://lakehouse)
-- and tables of all layers end up side by side. With these, Trino places tables at
-- s3://lakehouse/<layer>/<table>-<uuid>/{data,metadata}/.
-- IF NOT EXISTS never changes an existing schema's location: use `make reset` after editing.
CREATE SCHEMA IF NOT EXISTS iceberg.bronze WITH (location = 's3://lakehouse/bronze');
CREATE SCHEMA IF NOT EXISTS iceberg.silver WITH (location = 's3://lakehouse/silver');
CREATE SCHEMA IF NOT EXISTS iceberg.gold   WITH (location = 's3://lakehouse/gold');
CREATE SCHEMA IF NOT EXISTS iceberg.audit  WITH (location = 's3://lakehouse/audit');
SHOW SCHEMAS FROM iceberg;
