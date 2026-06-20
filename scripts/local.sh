#!/usr/bin/env bash
# CognaSync local dev helper. Run from the repo root.
#
#   scripts/local.sh setup        # one-time: venv + python deps + build React client
#   scripts/local.sh seed         # create a dev provider + seed synthetic data
#   scripts/local.sh run          # load .env.local and start Flask on :5002
#   scripts/local.sh schema-dump  # print the pg_dump command for capturing schema.sql
#
# Requires a .env.local (copy from .env.local.example). NEVER point .env.local at
# the production Supabase project — dev project + synthetic data only.
set -euo pipefail
cd "$(dirname "$0")/.."

VENV=".venv"
PY="$VENV/bin/python"

_load_env() {
  if [ ! -f .env.local ]; then
    echo "ERROR: .env.local not found. Copy .env.local.example to .env.local and fill it in." >&2
    exit 1
  fi
  set -a; . ./.env.local; set +a
}

case "${1:-}" in
  setup)
    echo "==> Creating virtualenv ($VENV)"
    python3 -m venv "$VENV"
    echo "==> Installing Python deps"
    "$VENV/bin/pip" install --upgrade pip >/dev/null
    "$VENV/bin/pip" install -r requirements.txt
    echo "==> Building React client (vite build -> static/dist)"
    ( cd client && npm install && npm run build )
    echo "==> Done. Next: cp .env.local.example .env.local && edit, then scripts/local.sh seed"
    ;;

  seed)
    _load_env
    echo "==> Creating dev provider (provider@dev.local / DevPass123!)"
    "$PY" scripts/create_provider.py provider@dev.local 'DevPass123!' 'Dr. Dev Provider' || true
    echo "==> Seeding synthetic test data"
    "$PY" seed_test_data.py
    echo "==> Done. Log in at http://localhost:5002 with provider@dev.local / DevPass123!"
    ;;

  run)
    _load_env
    echo "==> Starting Flask on http://localhost:${FLASK_PORT:-5002}  (Ctrl-C to stop)"
    exec "$PY" app.py
    ;;

  schema-dump)
    cat <<'EOF'
To capture the authoritative schema from your LIVE project into schema.sql,
get the connection string from Supabase: Project > Settings > Database >
Connection string (URI), then:

  pg_dump --schema-only --no-owner --no-privileges \
    "postgresql://postgres:[PASSWORD]@db.[PROJECT_REF].supabase.co:5432/postgres" \
    > schema.sql

Apply it to your DEV project the same way (swap the connection string):

  psql "postgresql://postgres:[PASSWORD]@db.[DEV_PROJECT_REF].supabase.co:5432/postgres" \
    -f schema.sql

Note: pg_dump major version should be >= your Postgres major version. If the
first local boot errors on a missing table/function, the captured schema missed
something — re-dump with --no-privileges removed, or add the missing object.
EOF
    ;;

  *)
    echo "Usage: scripts/local.sh {setup|seed|run|schema-dump}" >&2
    exit 1
    ;;
esac
