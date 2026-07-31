#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
data_dir="$project_root/.postgres-data"

if [ ! -f "$data_dir/PG_VERSION" ]; then
  echo "PostgreSQL has not been initialized for this project."
  exit 0
fi

if pg_ctl --pgdata="$data_dir" status >/dev/null 2>&1; then
  pg_ctl --pgdata="$data_dir" stop --mode=fast
else
  echo "PostgreSQL is not running."
fi
