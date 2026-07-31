#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
data_dir="$project_root/.postgres-data"

if [ ! -f "$data_dir/PG_VERSION" ]; then
  echo "PostgreSQL has not been initialized for this project."
  exit 1
fi

pg_ctl --pgdata="$data_dir" status
