#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PRIMARY_SERVICE="postgres-primary"
REPLICA_SERVICE="postgres-replica"
DATABASE_USER="tracker"
DATABASE_NAME="tracker"
REPLICATION_USER="replicator"
REPLICATION_PASSWORD="replicator-password"
WAIT_ATTEMPTS=30

cd "$PROJECT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: Docker is not installed or is not available in PATH." >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Error: Docker Compose v2 is not available." >&2
  exit 1
fi

wait_for_primary() {
  local attempt

  for ((attempt = 1; attempt <= WAIT_ATTEMPTS; attempt++)); do
    if docker compose exec -T "$PRIMARY_SERVICE" \
      pg_isready -U "$DATABASE_USER" -d "$DATABASE_NAME" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done

  echo "Error: Primary did not become ready." >&2
  docker compose logs --tail=50 "$PRIMARY_SERVICE" >&2
  return 1
}

wait_for_replica() {
  local attempt
  local recovery_status

  for ((attempt = 1; attempt <= WAIT_ATTEMPTS; attempt++)); do
    recovery_status="$(
      docker compose exec -T "$REPLICA_SERVICE" \
        psql -U "$DATABASE_USER" -d "$DATABASE_NAME" -Atqc \
        "SELECT pg_is_in_recovery()" 2>/dev/null || true
    )"
    if [[ "$recovery_status" == "t" ]]; then
      return 0
    fi
    sleep 2
  done

  echo "Error: Replica did not become ready." >&2
  docker compose logs --tail=100 "$REPLICA_SERVICE" >&2
  return 1
}

echo "Starting PostgreSQL Primary..."
docker compose up -d "$PRIMARY_SERVICE"
wait_for_primary

echo "Ensuring that the replication role exists..."
docker compose exec -T "$PRIMARY_SERVICE" \
  psql -v ON_ERROR_STOP=1 -U "$DATABASE_USER" -d "$DATABASE_NAME" <<SQL
DO \$do\$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$REPLICATION_USER') THEN
    ALTER ROLE $REPLICATION_USER WITH REPLICATION LOGIN PASSWORD '$REPLICATION_PASSWORD';
  ELSE
    CREATE ROLE $REPLICATION_USER WITH REPLICATION LOGIN PASSWORD '$REPLICATION_PASSWORD';
  END IF;
END
\$do\$;
SQL

echo "Allowing replication connections in pg_hba.conf..."
docker compose exec -T "$PRIMARY_SERVICE" sh -eu -c '
  ipv4_rule="host replication replicator 0.0.0.0/0 scram-sha-256"
  ipv6_rule="host replication replicator ::/0 scram-sha-256"
  grep -Fqx "$ipv4_rule" "$PGDATA/pg_hba.conf" || printf "%s\n" "$ipv4_rule" >> "$PGDATA/pg_hba.conf"
  grep -Fqx "$ipv6_rule" "$PGDATA/pg_hba.conf" || printf "%s\n" "$ipv6_rule" >> "$PGDATA/pg_hba.conf"
'
docker compose exec -T "$PRIMARY_SERVICE" \
  psql -v ON_ERROR_STOP=1 -U "$DATABASE_USER" -d "$DATABASE_NAME" \
  -c "SELECT pg_reload_conf();" >/dev/null

echo "Creating and starting PostgreSQL Replica..."
docker compose up -d "$REPLICA_SERVICE"
wait_for_replica

echo "Waiting for the streaming connection..."
streaming_state=""
for ((attempt = 1; attempt <= WAIT_ATTEMPTS; attempt++)); do
  streaming_state="$(
    docker compose exec -T "$PRIMARY_SERVICE" \
      psql -U "$DATABASE_USER" -d "$DATABASE_NAME" -Atqc \
      "SELECT state FROM pg_stat_replication WHERE application_name = 'krasova-replica' LIMIT 1"
  )"
  if [[ "$streaming_state" == "streaming" ]]; then
    break
  fi
  sleep 2
done

if [[ "$streaming_state" != "streaming" ]]; then
  echo "Error: Replica is running, but the WAL connection is not streaming." >&2
  docker compose logs --tail=100 "$REPLICA_SERVICE" >&2
  exit 1
fi

echo
echo "Replica was created successfully."
docker compose exec -T "$PRIMARY_SERVICE" \
  psql -U "$DATABASE_USER" -d "$DATABASE_NAME" -c \
  "SELECT application_name, state, sync_state, sent_lsn, replay_lsn FROM pg_stat_replication;"
docker compose exec -T "$REPLICA_SERVICE" \
  psql -U "$DATABASE_USER" -d "$DATABASE_NAME" -c \
  "SELECT pg_is_in_recovery() AS is_replica, current_setting('transaction_read_only') AS read_only;"
