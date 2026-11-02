#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

set_supabase_migrations_enabled() {
    local enabled="$1"
    local config_file="$REPO_ROOT/supabase/config.toml"
    python3 -c "
import re

with open('$config_file', 'r', encoding='utf-8') as f:
    content = f.read()

# Pattern for [db.migrations] section
pattern = r'(\[db\.migrations\]\s*\n(?:#[^\n]*\n)*enabled\s*=\s*)(true|false)'
replacement = r'\g<1>$enabled'
new_content = re.sub(pattern, replacement, content)

with open('$config_file', 'w', encoding='utf-8') as f:
    f.write(new_content)
"
}

echo "Starting the official local Supabase Docker stack..."
set_supabase_migrations_enabled false

# Ensure migrations setting is restored on exit/failure
trap 'set_supabase_migrations_enabled true' EXIT

npx supabase start -x realtime,imgproxy,postgres-meta,studio,edge-runtime,logflare,vector,supavisor,postgrest

set_supabase_migrations_enabled true
trap - EXIT

echo "Reading local Supabase credentials..."
STATUS_ENV=$(npx supabase status -o env 2>/dev/null)

get_val() {
    local key="$1"
    echo "$STATUS_ENV" | grep -E "^${key}=" | head -n1 | cut -d'=' -f2- | tr -d '"\r'
}

API_URL=$(get_val "API_URL")
[ -z "$API_URL" ] && API_URL=$(get_val "SUPABASE_URL")

PUBLISHABLE_KEY=$(get_val "PUBLISHABLE_KEY")
[ -z "$PUBLISHABLE_KEY" ] && PUBLISHABLE_KEY=$(get_val "ANON_KEY")

SECRET_KEY=$(get_val "SECRET_KEY")
[ -z "$SECRET_KEY" ] && SECRET_KEY=$(get_val "SERVICE_ROLE_KEY")

DB_URL=$(get_val "DB_URL")
MAILPIT_URL=$(get_val "INBUCKET_URL")

if [ -z "$API_URL" ] || [ -z "$PUBLISHABLE_KEY" ] || [ -z "$SECRET_KEY" ] || [ -z "$DB_URL" ]; then
    echo "Error: Supabase started, but required local API keys or database URL were not returned." >&2
    exit 1
fi

BACKEND_API_URL=$(echo "$API_URL" | sed -E 's|https?://(127\.0\.0\.1\|localhost)|http://host.docker.internal|')
BACKEND_DB_URL=$(echo "$DB_URL" | sed -E 's|^postgresql://|postgresql+psycopg://|' | sed -E 's|@(127\.0\.0\.1\|localhost):|@host.docker.internal:|')

echo "Bootstrapping backend schema (Alembic) before Supabase's own migrations..."
docker build -q -t siteops-mvp-backend-bootstrap ./backend > /dev/null
docker run --rm --add-host=host.docker.internal:host-gateway -e DATABASE_URL="$BACKEND_DB_URL" siteops-mvp-backend-bootstrap sh -c "alembic upgrade head"

echo "Applying pending Supabase migrations..."
set +e
MIGRATION_OUTPUT=$(npx supabase migration up --local 2>&1)
MIGRATION_EXIT=$?
set -e

if [ $MIGRATION_EXIT -ne 0 ]; then
    if echo "$MIGRATION_OUTPUT" | grep -q "vendor_categories"; then
        echo "Skipping 20260731_vendor_category_mapping.sql (legacy vendor_categories table dropped by Alembic)..."
        npx supabase migration repair --status applied 20260731 --local > /dev/null
        npx supabase migration up --local
    else
        echo "$MIGRATION_OUTPUT" >&2
        echo "Error: Pending Supabase migrations could not be applied." >&2
        exit 1
    fi
fi

# Read existing .env if present
BOOTSTRAP_EMAIL="superadmin@siteops.local"
BOOTSTRAP_PASSWORD="LocalSiteOps!2026"
MIGRATION_PASSWORD="LocalMigration!2026"
TELEGRAM_ACCESS_TOKEN=""
TELEGRAM_WEBHOOK_SECRET=""
WHATSAPP_ACCESS_TOKEN=""
WHATSAPP_PHONE_NUMBER_ID=""
WHATSAPP_API_VERSION="v21.0"
WHATSAPP_WEBHOOK_SECRET=""
WHATSAPP_WEBHOOK_VERIFY_TOKEN=""

if [ -f .env ]; then
    read_env_val() {
        grep -E "^$1=" .env 2>/dev/null | head -n1 | cut -d'=' -f2- | tr -d '"\r' || true
    }
    V=$(read_env_val "BOOTSTRAP_SUPER_ADMIN_EMAIL") && [ -n "$V" ] && BOOTSTRAP_EMAIL="$V"
    V=$(read_env_val "BOOTSTRAP_SUPER_ADMIN_PASSWORD") && [ -n "$V" ] && BOOTSTRAP_PASSWORD="$V"
    V=$(read_env_val "MIGRATION_TEMP_PASSWORD") && [ -n "$V" ] && MIGRATION_PASSWORD="$V"
    V=$(read_env_val "TELEGRAM_ACCESS_TOKEN") && [ -n "$V" ] && TELEGRAM_ACCESS_TOKEN="$V"
    V=$(read_env_val "TELEGRAM_WEBHOOK_SECRET") && [ -n "$V" ] && TELEGRAM_WEBHOOK_SECRET="$V"
    V=$(read_env_val "WHATSAPP_ACCESS_TOKEN") && [ -n "$V" ] && WHATSAPP_ACCESS_TOKEN="$V"
    V=$(read_env_val "WHATSAPP_PHONE_NUMBER_ID") && [ -n "$V" ] && WHATSAPP_PHONE_NUMBER_ID="$V"
    V=$(read_env_val "WHATSAPP_API_VERSION") && [ -n "$V" ] && WHATSAPP_API_VERSION="$V"
    V=$(read_env_val "WHATSAPP_WEBHOOK_SECRET") && [ -n "$V" ] && WHATSAPP_WEBHOOK_SECRET="$V"
    V=$(read_env_val "WHATSAPP_WEBHOOK_VERIFY_TOKEN") && [ -n "$V" ] && WHATSAPP_WEBHOOK_VERIFY_TOKEN="$V"
fi

cat <<EOF > .env
# Generated for the local Supabase CLI stack. Git ignored.
SUPABASE_PUBLIC_URL=$API_URL
SUPABASE_BACKEND_URL=$BACKEND_API_URL
SUPABASE_PUBLISHABLE_KEY=$PUBLISHABLE_KEY
SUPABASE_SECRET_KEY=$SECRET_KEY
FRONTEND_URL=http://localhost:3000
DATABASE_URL=$BACKEND_DB_URL

BOOTSTRAP_SUPER_ADMIN_EMAIL=$BOOTSTRAP_EMAIL
BOOTSTRAP_SUPER_ADMIN_PASSWORD=$BOOTSTRAP_PASSWORD
MIGRATION_TEMP_PASSWORD=$MIGRATION_PASSWORD

VITE_API_BASE=http://localhost:8000

TELEGRAM_ACCESS_TOKEN=$TELEGRAM_ACCESS_TOKEN
TELEGRAM_WEBHOOK_SECRET=$TELEGRAM_WEBHOOK_SECRET

WHATSAPP_ACCESS_TOKEN=$WHATSAPP_ACCESS_TOKEN
WHATSAPP_PHONE_NUMBER_ID=$WHATSAPP_PHONE_NUMBER_ID
WHATSAPP_API_VERSION=$WHATSAPP_API_VERSION
WHATSAPP_WEBHOOK_SECRET=$WHATSAPP_WEBHOOK_SECRET
WHATSAPP_WEBHOOK_VERIFY_TOKEN=$WHATSAPP_WEBHOOK_VERIFY_TOKEN
EOF

echo "Building SiteOps against local Supabase Auth and PostgreSQL..."
docker compose down --remove-orphans
docker compose up -d --build

echo ""
echo "Local SiteOps is running!"
echo "Portal: http://localhost:3000"
if [ -n "$MAILPIT_URL" ]; then
    echo "Local email inbox: $MAILPIT_URL"
fi
echo "Super Admin: $BOOTSTRAP_EMAIL"
echo "Run './tools/status-local.sh' to verify health."
