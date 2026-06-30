CREATE TABLE IF NOT EXISTS agent_platform.coverage_model (
  name string COMMENT 'Name',
  count bigint COMMENT 'Count',
  score double COMMENT 'Score',
  active boolean COMMENT 'Active',
  event_date date COMMENT 'Event date',
  tags array<string> COMMENT 'Tags',
  category string COMMENT 'Category',
  optional_note string COMMENT 'Optional note',
  required_field string COMMENT 'Required [NOT NULL]',
  created_timestamp timestamp COMMENT 'SCD2 created',
  last_updated_timestamp timestamp COMMENT 'SCD2 last updated'
)
PARTITIONED BY (day(last_updated_timestamp))
LOCATION 's3://agent-platform-data-lake/iceberg/coverage_model/'
TBLPROPERTIES (
  'table_type'='ICEBERG',
  'format'='parquet',
  'write_compression'='gzip'
)
