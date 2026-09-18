#!/bin/sh
set -eu

if [ "$(id -u)" = "0" ]; then
  mkdir -p "$PGDATA"
  chown -R postgres:postgres "$PGDATA"
  exec gosu postgres "$0" "$@"
fi

until pg_isready -h "$PRIMARY_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB"; do
  sleep 1
done

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  PGPASSWORD="$REPLICATION_PASSWORD" pg_basebackup \
    --host="$PRIMARY_HOST" \
    --username="$REPLICATION_USER" \
    --pgdata="$PGDATA" \
    --format=plain \
    --wal-method=stream \
    --checkpoint=fast

  touch "$PGDATA/standby.signal"
  cat >> "$PGDATA/postgresql.auto.conf" <<EOF
primary_conninfo = 'host=$PRIMARY_HOST port=5432 user=$REPLICATION_USER password=$REPLICATION_PASSWORD application_name=krasova-replica'
hot_standby = on
EOF
fi

exec docker-entrypoint.sh postgres
