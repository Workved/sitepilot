#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "Stopping SiteOps containers..."
docker compose down

echo "Stopping local Supabase stack..."
npx supabase stop

echo "SiteOps local stack stopped."
