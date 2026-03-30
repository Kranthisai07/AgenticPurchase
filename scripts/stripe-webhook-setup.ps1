<#
.SYNOPSIS
    One-time setup: retrieves the Stripe CLI webhook signing secret and writes
    it into .env as STRIPE_WEBHOOK_SECRET.

.DESCRIPTION
    Stripe CLI generates a unique whsec_... signing secret that your backend
    must use to verify webhook payloads. This secret changes if you log in with
    a different account or device name, so always run this script after cloning
    the repo or rotating API keys.

.EXAMPLE
    .\scripts\stripe-webhook-setup.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ComposeFile = Join-Path $PSScriptRoot "..\docker-compose.dev.yml"
$EnvFile     = Join-Path $PSScriptRoot "..\.env"

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Stripe CLI — Webhook Secret Setup" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Ensure Docker is reachable ─────────────────────────────────────────────
try {
    docker info | Out-Null
} catch {
    Write-Host "[ERROR] Docker is not running. Start Docker Desktop and try again." -ForegroundColor Red
    exit 1
}

# ── 2. Pull the stripe-cli image if needed ────────────────────────────────────
Write-Host "Pulling stripe/stripe-cli image..." -ForegroundColor Yellow
docker compose -f $ComposeFile pull stripe-cli-setup 2>&1 | Out-Null

# ── 3. Run stripe listen --print-secret ───────────────────────────────────────
Write-Host "Fetching webhook signing secret from Stripe CLI..." -ForegroundColor Yellow

$secret = docker compose -f $ComposeFile `
    --profile setup `
    run --rm stripe-cli-setup 2>&1 |
    Select-String -Pattern "whsec_[A-Za-z0-9]+" |
    ForEach-Object { $_.Matches[0].Value } |
    Select-Object -First 1

if (-not $secret) {
    Write-Host ""
    Write-Host "[ERROR] Could not retrieve webhook signing secret." -ForegroundColor Red
    Write-Host "  Check that STRIPE_SECRET_KEY is set correctly in .env" -ForegroundColor Red
    Write-Host "  and that your Stripe test-mode API key is valid." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "  Signing secret: $secret" -ForegroundColor Green

# ── 4. Write into .env ────────────────────────────────────────────────────────
if (-not (Test-Path $EnvFile)) {
    Write-Host "[ERROR] .env file not found at: $EnvFile" -ForegroundColor Red
    exit 1
}

$content = Get-Content $EnvFile -Raw

if ($content -match "STRIPE_WEBHOOK_SECRET=.*") {
    $content = $content -replace "STRIPE_WEBHOOK_SECRET=.*", "STRIPE_WEBHOOK_SECRET=$secret"
} else {
    $content += "`nSTRIPE_WEBHOOK_SECRET=$secret"
}

Set-Content -Path $EnvFile -Value $content -NoNewline
Write-Host "  Written to .env as STRIPE_WEBHOOK_SECRET" -ForegroundColor Green

# ── 5. Restart backend so it picks up the new secret ─────────────────────────
Write-Host ""
Write-Host "Restarting backend container to apply new secret..." -ForegroundColor Yellow
docker compose -f $ComposeFile restart backend 2>&1 | Out-Null
Write-Host "  Backend restarted." -ForegroundColor Green

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Next: start the webhook listener:" -ForegroundColor White
Write-Host "    docker compose -f docker-compose.dev.yml up stripe-cli" -ForegroundColor White
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
