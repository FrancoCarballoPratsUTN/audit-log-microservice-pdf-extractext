<#
.SYNOPSIS
    Pipeline completo de pruebas de stress: Vegeta + k6 en un solo comando.

.DESCRIPTION
    Encadena las dos fases de ataque del plan sobre el servicio local:

      1. Preflight   - vegeta y k6 en el PATH, SERVICE_API_TOKEN definida y
                       /readyz en 200 (servicio *y* MongoDB vivos).
      2. Vegeta      - delega en run-vegeta.ps1 -Profile: genera targets
                       (gen_targets.py, con siembra del set de lectura si hay
                       bychecksum) y ataca con umbral.
      3. k6          - corre el escenario elegido con --out json=...; sus
                       thresholds deciden el exit code.
      4. Resumen     - lista los artefactos de tests/stress/out/ de esta
                       corrida y cierra con exit 0 si todo pasó.

    Cualquier fallo detiene el pipeline en el momento (fail-fast). La primera
    etapa que falla no deja continuar a la siguiente.

    Los eventos creados por los ataques se dejan en la base (decisión del
    plan): AUDA es append-only y no hay borrado; el POST idempotente convierte
    la basura de una corrida anterior en un 200, nunca en un error.

.PARAMETER Profile
    Perfil de Vegeta: smoke (10 rps/10 s), load (100 rps/30 s),
    stress (300 rps/60 s).

.PARAMETER Scenario
    Escenario de k6: smoke (1 VU/30 s), load (rampa a 100 VUs),
    stress (rampa a 500 VUs).

.PARAMETER BaseUrl
    Raíz del servicio; por defecto http://localhost:8083. Se pasa tanto a
    Vegeta como a k6 (BASE_URL).

.EXAMPLE
    ./run-stress.ps1 -Profile smoke -Scenario smoke
#>
#Requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateSet("smoke", "load", "stress")]
    [string]$Profile = "smoke",

    [ValidateSet("smoke", "load", "stress")]
    [string]$Scenario = "smoke",

    [string]$BaseUrl = "http://localhost:8083"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "FAIL: $Message" -ForegroundColor Red
    exit 1
}

# --- 1. Preflight -----------------------------------------------------------

foreach ($tool in "vegeta", "k6") {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Fail ("'$tool' no esta en el PATH. Ver la instalacion en " +
              "tests/stress/README.md (Vegeta: github.com/tsenart/vegeta/releases, " +
              "k6: grafana.com/docs/k6/latest/set-up/install-k6/).")
    }
}

$token = [System.Environment]::GetEnvironmentVariable("SERVICE_API_TOKEN")
if ([string]::IsNullOrWhiteSpace($token)) {
    Fail ("SERVICE_API_TOKEN no esta definida; sin ella todo es 401. " +
          "Exporta la variable antes de lanzar el pipeline.")
}

try {
    Invoke-WebRequest -Uri "$BaseUrl/readyz" -TimeoutSec 5 | Out-Null
} catch {
    Fail ("no responde $BaseUrl/readyz: hace falta el servicio local Y MongoDB " +
          "(curl -s http://localhost:8083/readyz debe dar mongo:ok). Levantar: " +
          "'docker compose up --build -d' o 'uv run uvicorn app.main:create_app --factory --port 8083'.")
}

# --- 2. Vegeta --------------------------------------------------------------

Write-Host "`n=== Vegeta: perfil '$Profile' ===" -ForegroundColor Cyan
& (Join-Path $PSScriptRoot "scripts" "run-vegeta.ps1") -Profile $Profile -BaseUrl $BaseUrl
if ($LASTEXITCODE -ne 0) {
    Fail ("vegeta ha fallado (codigo $LASTEXITCODE); revisa el umbral en " +
          "tests/stress/out/vegeta-$Profile-*.report.txt")
}

# --- 3. k6 ------------------------------------------------------------------

Write-Host "`n=== k6: escenario '$Scenario' ===" -ForegroundColor Cyan
$k6Script = Join-Path $PSScriptRoot "scripts" "k6" "$Scenario.js"
$k6Out = Join-Path $PSScriptRoot "out" "k6-$Scenario.json"

& k6 run `
    --env "SERVICE_API_TOKEN=$token" `
    --env "BASE_URL=$BaseUrl" `
    --out "json=$k6Out" `
    $k6Script
if ($LASTEXITCODE -ne 0) {
    Fail ("k6 ha fallado (escenario '$Scenario', codigo $LASTEXITCODE): " +
          "umbral roto o servicio caido; resumen en la salida anterior")
}

# --- 4. Resumen -------------------------------------------------------------

Write-Host "`n=== Resumen: artefactos de esta corrida ===" -ForegroundColor Cyan
$artifacts = @(
    Get-ChildItem (Join-Path $PSScriptRoot "out") -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "vegeta-$Profile-*" -or $_.Name -eq "k6-$Scenario.json" }
)
if ($artifacts) {
    $artifacts | Sort-Object Name | ForEach-Object {
        Write-Host ("  {0}  ({1:N0} bytes)" -f $_.Name, $_.Length)
    }
} else {
    Write-Host "  (sin artefactos en tests/stress/out/)" -ForegroundColor Yellow
}

Write-Host "`nok: pipeline completo (vegeta '$Profile' + k6 '$Scenario')." -ForegroundColor Green
exit 0