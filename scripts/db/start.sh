#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
data_dir="$project_root/.postgres-data"
socket_dir="$project_root/.postgres-socket"
log_file="$project_root/.postgres.log"
database_name="health_guard"
database_user="health_guard"

mkdir -p "$socket_dir"

if [ ! -f "$data_dir/PG_VERSION" ]; then
  initdb --pgdata="$data_dir" --username="$database_user" --auth-local=trust --auth-host=trust \
    --encoding=UTF8 --no-locale >/dev/null
fi

if ! pg_ctl --pgdata="$data_dir" status >/dev/null 2>&1; then
  pg_ctl --pgdata="$data_dir" --log="$log_file" start \
    --options="-c listen_addresses='' -k $socket_dir" >/dev/null
fi

until pg_isready --host="$socket_dir" --username="$database_user" >/dev/null 2>&1; do
  sleep 1
done

if ! psql --host="$socket_dir" --username="$database_user" --dbname=postgres \
  --tuples-only --no-align --command="SELECT 1 FROM pg_database WHERE datname = '$database_name'" \
  | grep --quiet '^1$'; then
  createdb --host="$socket_dir" --username="$database_user" "$database_name"
fi

printf 'PostgreSQL is ready on the project Unix socket for database %s\n' "$database_name"
