#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "=== SiteOps Containers ==="
docker compose ps
echo ""

echo "=== Supabase Containers ==="
docker ps --filter "name=supabase_" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep "siteops-mvp" || true
echo ""

echo "=== Health Checks ==="
# Check Supabase Auth
API_URL=$(npx supabase status -o env 2>/dev/null | grep -E '^(API_URL|SUPABASE_URL)=' | head -n1 | cut -d'=' -f2 | tr -d '"')
if [ -n "$API_URL" ]; then
    AUTH_HTTP=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/auth/v1/health" || echo "failed")
    echo "Supabase Auth Health: HTTP $AUTH_HTTP"
else
    echo "Supabase API URL is unavailable."
fi

# Check Backend Health
BACKEND_HTTP=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/api/health" || echo "failed")
echo "Backend API Health: HTTP $BACKEND_HTTP"

# Check Frontend Health
FRONTEND_HTTP=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:3000" || echo "failed")
echo "Frontend Health: HTTP $FRONTEND_HTTP"
