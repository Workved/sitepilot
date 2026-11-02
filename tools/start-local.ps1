$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Read-ExistingEnv {
    $result = @{}
    if (Test-Path ".env") {
        Get-Content ".env" | ForEach-Object {
            if ($_ -match '^([^#=]+)=(.*)$') {
                $result[$matches[1].Trim()] = $matches[2].Trim()
            }
        }
    }
    return $result
}

function First-Value {
    param([hashtable]$Values, [string[]]$Names)
    foreach ($name in $Names) {
        if ($Values.ContainsKey($name) -and -not [string]::IsNullOrWhiteSpace($Values[$name])) {
            return $Values[$name]
        }
    }
    return $null
}

function Set-SupabaseMigrationsEnabled {
    # Toggles [db.migrations] enabled in supabase/config.toml. Used to bring
    # up a brand-new local database with no Supabase SQL applied yet, so the
    # backend's Alembic migrations can bootstrap public.users/public.vendors/
    # etc. first (see the "Bootstrapping the backend schema" step below).
    param([bool]$Enabled)
    $configPath = Join-Path $repoRoot "supabase/config.toml"
    $lines = Get-Content $configPath
    $inMigrationsSection = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^\[db\.migrations\]') { $inMigrationsSection = $true; continue }
        if ($inMigrationsSection -and $lines[$i] -match '^\[') { $inMigrationsSection = $false }
        if ($inMigrationsSection -and $lines[$i] -match '^enabled\s*=') {
            $lines[$i] = "enabled = $(if ($Enabled) { 'true' } else { 'false' })"
            break
        }
    }
    [System.IO.File]::WriteAllLines($configPath, $lines, (New-Object System.Text.UTF8Encoding($false)))
}

Write-Host "Starting the official local Supabase Docker stack..."
Set-SupabaseMigrationsEnabled $false
try {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    # storage-api is NOT excluded: app.services.evidence_storage uploads
    # task/gate/vendor-activity evidence to it (bucket created by
    # supabase/migrations/202608240001_v2_evidence_storage_bucket.sql), so
    # local dev needs the real thing, not a stub.
    $supabaseStartOutput = & npx supabase start -x realtime,imgproxy,postgres-meta,studio,edge-runtime,logflare,vector,supavisor,postgrest 2>&1
    $supabaseStartExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    if ($supabaseStartExitCode -ne 0) {
        $supabaseStartOutput | ForEach-Object { Write-Host $_ -ForegroundColor Red }
        throw "Supabase local stack failed to start. Review the Supabase output above."
    }
} finally {
    Set-SupabaseMigrationsEnabled $true
}

$statusOutput = & npx supabase status -o env
if ($LASTEXITCODE -ne 0) {
    throw "Could not read local Supabase credentials."
}

$local = @{}
$statusOutput | ForEach-Object {
    if ($_ -match '^\s*([A-Z0-9_]+)\s*=\s*"?([^"]*)"?\s*$') {
        $local[$matches[1]] = $matches[2]
    }
}

$apiUrl = First-Value $local @("API_URL", "SUPABASE_URL")
$publishableKey = First-Value $local @("PUBLISHABLE_KEY", "ANON_KEY")
$secretKey = First-Value $local @("SECRET_KEY", "SERVICE_ROLE_KEY")
$dbUrl = First-Value $local @("DB_URL")
$mailpitUrl = First-Value $local @("INBUCKET_URL")

if (-not $apiUrl -or -not $publishableKey -or -not $secretKey -or -not $dbUrl) {
    throw "Supabase started, but the required local API keys or database URL were not returned."
}

$backendApiUrl = $apiUrl -replace '^https?://(127\.0\.0\.1|localhost)', 'http://host.docker.internal'
$backendDbUrl = $dbUrl -replace '^postgresql://', 'postgresql+psycopg://'
$backendDbUrl = $backendDbUrl -replace '@(127\.0\.0\.1|localhost):', '@host.docker.internal:'

# supabase/migrations/*.sql (siteops_v2 schema) has foreign keys into
# public.users, public.vendors, etc., which only exist once the backend's
# own Alembic migrations have run. Bootstrap that schema first so a
# brand-new database has those tables before Supabase's migrations need
# them - safe to re-run against an already-migrated database too, since
# Alembic no-ops when it's already at head.
Write-Host "Bootstrapping the backend schema (Alembic) before Supabase's own migrations..."
& docker build -q -t siteops-mvp-backend-bootstrap ./backend | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not build the backend image for the Alembic bootstrap." }
& docker run --rm --add-host=host.docker.internal:host-gateway -e DATABASE_URL=$backendDbUrl siteops-mvp-backend-bootstrap sh -c "alembic upgrade head"
if ($LASTEXITCODE -ne 0) { throw "Alembic could not bootstrap the local database." }

Write-Host "Applying pending Supabase migrations..."
$ErrorActionPreference = "Continue"
$migrationUpOutput = & npx supabase migration up --local 2>&1
$migrationUpExitCode = $LASTEXITCODE
$ErrorActionPreference = "Stop"

if ($migrationUpExitCode -ne 0) {
    # 20260731_vendor_category_mapping.sql creates task_vendor_category_mappings
    # referencing vendor_categories, a table Alembic's 0022_drop_legacy_tables no
    # longer creates (dropped as part of the vendor consolidation). The table it
    # creates is itself dropped four migrations later by
    # 202608040007_drop_vendor_category_mapping.sql, so on a fresh database it's
    # dead weight that fails against a table that will never exist. If that's
    # what just failed, repair its history to "applied" (skipping it) and
    # resume - otherwise this is a real migration failure, surface it.
    if (($migrationUpOutput | Out-String) -notmatch "vendor_categories.*does not exist") {
        $migrationUpOutput | ForEach-Object { Write-Host $_ -ForegroundColor Red }
        throw "Pending Supabase migrations could not be applied."
    }

    Write-Host "Skipping 20260731_vendor_category_mapping.sql (dead on a fresh database, see comment above)..."
    & npx supabase migration repair --status applied 20260731 --local | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not repair the Supabase migration history." }

    & npx supabase migration up --local
    if ($LASTEXITCODE -ne 0) {
        throw "Pending Supabase migrations could not be applied."
    }
}

$existing = Read-ExistingEnv
$bootstrapEmail = First-Value $existing @("BOOTSTRAP_SUPER_ADMIN_EMAIL")
$bootstrapPassword = First-Value $existing @("BOOTSTRAP_SUPER_ADMIN_PASSWORD")
$migrationPassword = First-Value $existing @("MIGRATION_TEMP_PASSWORD")
$telegramAccessToken = First-Value $existing @("TELEGRAM_ACCESS_TOKEN")
$telegramWebhookSecret = First-Value $existing @("TELEGRAM_WEBHOOK_SECRET")
$whatsappAccessToken = First-Value $existing @("WHATSAPP_ACCESS_TOKEN")
$whatsappPhoneNumberId = First-Value $existing @("WHATSAPP_PHONE_NUMBER_ID")
$whatsappApiVersion = First-Value $existing @("WHATSAPP_API_VERSION")
$whatsappWebhookSecret = First-Value $existing @("WHATSAPP_WEBHOOK_SECRET")
$whatsappWebhookVerifyToken = First-Value $existing @("WHATSAPP_WEBHOOK_VERIFY_TOKEN")

if (-not $bootstrapEmail) { $bootstrapEmail = "superadmin@siteops.local" }
if (-not $bootstrapPassword) { $bootstrapPassword = "LocalSiteOps!2026" }
if (-not $migrationPassword) { $migrationPassword = "LocalMigration!2026" }
if (-not $whatsappApiVersion) { $whatsappApiVersion = "v21.0" }

$envLines = @(
    "# Generated for the local Supabase CLI stack. Git ignored.",
    "SUPABASE_PUBLIC_URL=$apiUrl",
    "SUPABASE_BACKEND_URL=$backendApiUrl",
    "SUPABASE_PUBLISHABLE_KEY=$publishableKey",
    "SUPABASE_SECRET_KEY=$secretKey",
    "FRONTEND_URL=http://localhost:3000",
    "DATABASE_URL=$backendDbUrl",
    "",
    "BOOTSTRAP_SUPER_ADMIN_EMAIL=$bootstrapEmail",
    "BOOTSTRAP_SUPER_ADMIN_PASSWORD=$bootstrapPassword",
    "MIGRATION_TEMP_PASSWORD=$migrationPassword",
    "",
    "VITE_API_BASE=http://localhost:8000",
    "",
    "TELEGRAM_ACCESS_TOKEN=$telegramAccessToken",
    "TELEGRAM_WEBHOOK_SECRET=$telegramWebhookSecret",
    "",
    "WHATSAPP_ACCESS_TOKEN=$whatsappAccessToken",
    "WHATSAPP_PHONE_NUMBER_ID=$whatsappPhoneNumberId",
    "WHATSAPP_API_VERSION=$whatsappApiVersion",
    "WHATSAPP_WEBHOOK_SECRET=$whatsappWebhookSecret",
    "WHATSAPP_WEBHOOK_VERIFY_TOKEN=$whatsappWebhookVerifyToken"
)
[System.IO.File]::WriteAllLines((Join-Path $repoRoot ".env"), $envLines, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "Building SiteOps against local Supabase Auth and PostgreSQL..."
& docker compose down --remove-orphans
if ($LASTEXITCODE -ne 0) { throw "Could not stop the previous SiteOps stack." }

& docker compose up -d --build
if ($LASTEXITCODE -ne 0) { throw "SiteOps containers failed to start." }

Write-Host ""
Write-Host "Local SiteOps is starting."
Write-Host "Portal: http://localhost:3000"
if ($mailpitUrl) { Write-Host "Local email inbox: $mailpitUrl" }
Write-Host "Super Admin: $bootstrapEmail"
Write-Host "Run 'npm run local:status' to verify health."
