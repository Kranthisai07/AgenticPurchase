param(
    [string]$BindHost = "127.0.0.1",
    [switch]$NoReload
)

$ErrorActionPreference = 'Stop'

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$PROJECT_ROOT = Resolve-Path (Join-Path $SCRIPT_DIR '..')
$BACKEND = Join-Path $PROJECT_ROOT 'Agentic_AI'
$VENV_ACT = Join-Path $BACKEND '.venv\Scripts\Activate.ps1'

if (-not (Test-Path $BACKEND)) {
    throw "Backend path not found: $BACKEND"
}
if (-not (Test-Path $VENV_ACT)) {
    Write-Host "[!] Virtualenv not found. Create one and install deps:" -ForegroundColor Yellow
    Write-Host "    cd $BACKEND; python -m venv .venv; . .venv\Scripts\activate; pip install -r requirements-agentic.txt"
    throw "Missing venv"
}

$reload = if ($NoReload) { "" } else { " --reload" }

function New-AgentWindow {
    param(
        [string]$Title,
        [string]$UvicornApp,
        [int]$Port,
        [hashtable]$ExtraEnv
    )

    $prologue = "cd `"$BACKEND`"`n"
    $envLoader = @'
. .\.venv\Scripts\Activate.ps1
if (Test-Path .env) {
  Get-Content .env | ForEach-Object {
    if ($_ -and ($_ -notmatch '^[\s#]')) {
      $kv = $_ -split '=', 2
      if ($kv.Count -eq 2) {
        $name = $kv[0].Trim()
        $value = $kv[1].Trim()
        if ($value.StartsWith('"') -and $value.EndsWith('"') -and $value.Length -ge 2) { $value = $value.Substring(1, $value.Length-2) }
        if ($value.StartsWith("'") -and $value.EndsWith("'") -and $value.Length -ge 2) { $value = $value.Substring(1, $value.Length-2) }
        if ($name) { Set-Item -Path Env:$name -Value $value }
      }
    }
  }
}
'@

    if ($ExtraEnv) {
        foreach ($k in $ExtraEnv.Keys) {
            $v = $ExtraEnv[$k]
            $envLoader += "`n`$env:$k = '$v'"
        }
    }

    $cmd = $prologue + $envLoader + "`nuvicorn $UvicornApp --host $BindHost --port $Port$reload"
    Start-Process -FilePath "powershell.exe" -ArgumentList "-NoExit", "-Command", $cmd -WindowStyle Normal | Out-Null
    Write-Host ("[+] Started {0} on {1}:{2}" -f $Title, $BindHost, $Port) -ForegroundColor Green
}

New-AgentWindow -Title "Agent 1 - Vision"   -UvicornApp "apps.agent1_vision.service:app"  -Port 8101 -ExtraEnv @{}
New-AgentWindow -Title "Agent 2 - Intent"   -UvicornApp "apps.agent2_intent.service:app"  -Port 8102 -ExtraEnv @{}
New-AgentWindow -Title "Agent 3 - Sourcing" -UvicornApp "apps.agent3_sourcing.service:app" -Port 8103 -ExtraEnv @{}
New-AgentWindow -Title "Agent 4 - Trust"    -UvicornApp "apps.agent4_trust.service:app"   -Port 8104 -ExtraEnv @{}
New-AgentWindow -Title "Agent 5 - Checkout" -UvicornApp "apps.agent5_checkout.service:app" -Port 8105 -ExtraEnv @{}

$agentEnv = @{
    "AGENT_VISION_URL"   = "http://$($BindHost):8101"
    "AGENT_INTENT_URL"   = "http://$($BindHost):8102"
    "AGENT_SOURCING_URL" = "http://$($BindHost):8103"
    "AGENT_TRUST_URL"    = "http://$($BindHost):8104"
    "AGENT_CHECKOUT_URL" = "http://$($BindHost):8105"
}
New-AgentWindow -Title "Coordinator" -UvicornApp "apps.coordinator.main:app" -Port 8000 -ExtraEnv $agentEnv

Write-Host "`nAll services launched. Endpoints:" -ForegroundColor Cyan
Write-Host ("  Coordinator: http://{0}:8000" -f $BindHost)
Write-Host ("  Vision:      http://{0}:8101" -f $BindHost)
Write-Host ("  Intent:      http://{0}:8102" -f $BindHost)
Write-Host ("  Sourcing:    http://{0}:8103" -f $BindHost)
Write-Host ("  Trust:       http://{0}:8104" -f $BindHost)
Write-Host ("  Checkout:    http://{0}:8105" -f $BindHost)
