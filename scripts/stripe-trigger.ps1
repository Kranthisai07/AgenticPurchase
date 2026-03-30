<#
.SYNOPSIS
    Trigger test Stripe webhook events against the local backend.

.DESCRIPTION
    Uses the Stripe CLI inside Docker to fire test events so you can verify
    your webhook handler end-to-end without making real payments.

    Available event shortcuts:
      succeeded   → payment_intent.succeeded
      failed      → payment_intent.payment_failed
      canceled    → payment_intent.canceled
      dispute     → charge.dispute.created
      refunded    → charge.refunded
      all         → fires all five events above

.PARAMETER Event
    The event shortcut to trigger (see list above). Defaults to "succeeded".

.PARAMETER SagaId
    Optional saga_id to inject into PaymentIntent metadata (for tracing in logs).

.EXAMPLE
    .\scripts\stripe-trigger.ps1
    .\scripts\stripe-trigger.ps1 -Event failed
    .\scripts\stripe-trigger.ps1 -Event all
    .\scripts\stripe-trigger.ps1 -Event succeeded -SagaId "my-saga-uuid"
#>
param(
    [ValidateSet("succeeded","failed","canceled","dispute","refunded","all")]
    [string]$Event = "succeeded",

    [string]$SagaId = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ComposeFile = Join-Path $PSScriptRoot "..\docker-compose.dev.yml"

# Map shortcut → Stripe event type
$EventMap = @{
    "succeeded" = "payment_intent.succeeded"
    "failed"    = "payment_intent.payment_failed"
    "canceled"  = "payment_intent.canceled"
    "dispute"   = "charge.dispute.created"
    "refunded"  = "charge.refunded"
}

function Invoke-StripeEvent([string]$StripeEventType) {
    Write-Host ""
    Write-Host "  Triggering: $StripeEventType" -ForegroundColor Yellow

    $args = @("trigger", $StripeEventType)

    # Inject saga_id into metadata if provided (best-effort; not all events accept it)
    if ($SagaId -ne "") {
        $args += "--add"
        $args += "payment_intent:metadata[saga_id]=$SagaId"
    }

    docker compose -f $ComposeFile run --rm `
        -e STRIPE_API_KEY=$env:STRIPE_SECRET_KEY `
        stripe-cli stripe @args 2>&1

    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] $StripeEventType" -ForegroundColor Green
    } else {
        Write-Host "  [WARN] $StripeEventType exited with code $LASTEXITCODE" -ForegroundColor DarkYellow
    }
}

# ── Load .env so STRIPE_SECRET_KEY is available ───────────────────────────────
$EnvFile = Join-Path $PSScriptRoot "..\.env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match "^\s*([^#][^=]+)=(.*)$") {
            $name  = $Matches[1].Trim()
            $value = $Matches[2].Trim()
            [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Stripe CLI — Event Trigger" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

if ($Event -eq "all") {
    foreach ($key in $EventMap.Keys) {
        Invoke-StripeEvent $EventMap[$key]
        Start-Sleep -Milliseconds 500
    }
} else {
    Invoke-StripeEvent $EventMap[$Event]
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Check backend logs:" -ForegroundColor White
Write-Host "    docker compose -f docker-compose.dev.yml logs -f backend" -ForegroundColor White
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
