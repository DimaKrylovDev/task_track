#!/bin/sh
set -eu

psql --set=ON_ERROR_STOP=1 \
  --set=replication_user="$REPLICATION_USER" \
  --set=replication_password="$REPLICATION_PASSWORD" \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE :"replication_user"
  WITH REPLICATION LOGIN PASSWORD :'replication_password';
SQL

printf '%s\n' \
  "host replication $REPLICATION_USER 0.0.0.0/0 scram-sha-256" \
  "host replication $REPLICATION_USER ::/0 scram-sha-256" \
  >> "$PGDATA/pg_hba.conf"
