<#
.SYNOPSIS
    Ataque de stress con Vegeta contra el microservicio de auditoría (AUDA).

.DESCRIPTION
    Orquesta el ciclo completo de un ataque Vegeta:

      1. Preflight   - vegeta en el PATH, SERVICE_API_TOKEN y /readyz vivo
                       (el servicio *y* MongoDB, porque leer exige la base).
      2. Targets     - genera los tres ficheros con gen_targets.py y, si se
                       ataca `bychecksum`, siembra el set de lectura con
                       `--load` (un replay 200 no aborta la siembra).
      3. Ataque      - un ``vegeta attack`` por verbo, en el orden dado,
                       reciclando los targets a ritmo constante.
      4. Umbral      - compara el porcentaje de respuestas >= 400 o con error
                       de transporte contra el umbral del perfil; si lo supera,
                       el script sale con codigo 1.

    AUDA es append-only: no hay ``--pre-clean`` y el ciclo no borra nada. El
    ``POST`` es idempotente (mismo ``checksum`` + ``performed_at`` => ``200``),
    por eso el set de escritura (`post`) y el de lectura (`bychecksum`) son
    disjuntos y cada corrida con semilla aleatoria inserta eventos nuevos.

.PARAMETER Profile
    smoke  -   10 rps / 10 s / umbral  1%
    load   -  100 rps / 30 s / umbral  5%
    stress -  300 rps / 60 s / umbral 10%

.PARAMETER Verbs
    Subconjunto de post,list,bychecksum. Por defecto, los tres.

.PARAMETER Seed
    Semilla de los checksums. 0 (por defecto) => aleatoria: cada corrida crea
    eventos nuevos. Un valor fijo hace el ataque reproducible (los POST repiten
    los mismos eventos y miden el replay idempotente).

.PARAMETER NoSeed
    Omite la siembra del set de lectura aunque se ataque `bychecksum`.

.EXAMPLE
    ./run-vegeta.ps1 -Profile smoke

.EXAMPLE
    ./run-vegeta.ps1 -Profile stress -Verbs post,list
#>
#Requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateSet("smoke", "load", "stress")]
    [string]$Profile = "smoke",

    [ValidateSet("post", "list", "bychecksum")]
    [string[]]$Verbs = @("post", "list", "bychecksum"),

    [string]$BaseUrl = "http://localhost:8083",

    # 0 => rate x duracion x 1.1: vegeta recicla los targets cuando se acaban.
    [int]$Count = 0,

    # 0 => min(Count, 200) checksums en el set de lectura.
    [int]$Reads = 0,

    # 0 => semilla aleatoria (eventos nuevos); >0 => ataque reproducible.
    [int]$Seed = 0,

    [string]$TargetsDir = (Join-Path $PSScriptRoot ".." "targets"),
    [string]$OutDir = (Join-Path $PSScriptRoot ".." "out"),

    # Omite la siembra (--load) del set de lectura.
    [switch]$NoSeed
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Profiles = @{
    smoke  = @{ Rate = 10;   Seconds = 10; ThresholdPct = 1.0 }
    load   = @{ Rate = 100;  Seconds = 30; ThresholdPct = 5.0 }
    stress = @{ Rate = 300;  Seconds = 60; ThresholdPct = 10.0 }
}

function Fail([string]$Message) {
    Write-Host "FAIL: $Message" -ForegroundColor Red
    exit 1
}

# --- 1. Preflight -----------------------------------------------------------

$spec = $Profiles[$Profile]

if (-not (Get-Command vegeta -ErrorAction SilentlyContinue)) {
    Fail ("vegeta no esta en el PATH. Instalar con: " +
          "'go install github.com/tsenart/vegeta/v12@latest' o descargar el binario " +
          "desde https://github.com/tsenart/vegeta/releases")
}

$token = [System.Environment]::GetEnvironmentVariable("SERVICE_API_TOKEN")
if ([string]::IsNullOrWhiteSpace($token)) {
    Fail ("SERVICE_API_TOKEN no esta definida; el servicio rechaza cualquier " +
          "peticion sin ella. Exporta la variable (ver .env.example) antes de atacar.")
}

try {
    Invoke-WebRequest -Uri "$BaseUrl/readyz" -TimeoutSec 5 | Out-Null
} catch {
    Fail ("no responde $BaseUrl/readyz: hace falta el servicio Y MongoDB. " +
          "Levantarlo con 'docker compose up --build -d' o " +
          "'uv run uvicorn app.main:create_app --factory --port 8083'.")
}

# --- 2. Targets ---------------------------------------------------------------

New-Item -ItemType Directory -Force -Path $TargetsDir, $OutDir | Out-Null

if ($Count -le 0) { $Count = [math]::Ceiling($spec.Rate * $spec.Seconds * 1.1) }
if ($Reads -le 0) { $Reads = [math]::Min($Count, 200) }

$gen = Join-Path $PSScriptRoot "gen_targets.py"
$genArgs = @(
    "run", "python", $gen,
    "--count", "$Count",
    "--reads", "$Reads",
    "--base-url", $BaseUrl,
    "--out-dir", $TargetsDir
)
if ($Seed -gt 0) { $genArgs += @("--seed", "$Seed") }
if (($Verbs -contains "bychecksum") -and -not $NoSeed) { $genArgs += "--load" }

Write-Host "targets: preparando $Count escrituras y $Reads lecturas..."
& uv @genArgs
if ($LASTEXITCODE -ne 0) { Fail "gen_targets.py ha fallado (codigo $LASTEXITCODE)" }

# --- 3. Ataque + 4. Umbral ----------------------------------------------------

$failures = @()

foreach ($verb in $Verbs) {
    $targets = Join-Path $TargetsDir "$verb.txt"
    $results = Join-Path $OutDir "vegeta-$Profile-$verb.results"
    $report = Join-Path $OutDir "vegeta-$Profile-$verb.report.txt"
    $json = Join-Path $OutDir "vegeta-$Profile-$verb.report.json"

    Write-Host ""
    Write-Host "=== $verb @ $($spec.Rate) rps / $($spec.Seconds)s ===" -ForegroundColor Cyan

    # -format json: los targets los genera gen_targets.py en el formato que
    # admite cuerpos inline (el HTTP legible se come el JSON como cabecera).
    # -output escribe el gob binario sin pasar por `>` ni por cmd.
    & vegeta attack -format json -targets $targets `
        -rate $spec.Rate -duration "$($spec.Seconds)s" `
        -name $verb -output $results
    if ($LASTEXITCODE -ne 0) { Fail "vegeta attack ha fallado para '$verb' (codigo $LASTEXITCODE)" }

    & vegeta report -type=text $results | Out-File -FilePath $report -Encoding utf8
    if ($LASTEXITCODE -ne 0) { Fail "vegeta report (text) ha fallado para '$verb'" }
    Get-Content $report | Write-Host

    & vegeta report -type=json $results | Out-File -FilePath $json -Encoding utf8
    if ($LASTEXITCODE -ne 0) { Fail "vegeta report (json) ha fallado para '$verb'" }

    # `vegeta report -type=json` devuelve un unico objeto agregado (requests,
    # success, status_codes, errors). success es la fraccion con codigo en
    # [200,400); los errores de transporte quedan en 0 y por eso cuentan como fallo.
    $data = Get-Content $json -Raw | ConvertFrom-Json
    $total = [int]$data.requests
    if ($total -eq 0) { Fail "el informe de '$verb' esta vacio: nada se ataco" }

    $bad = $total - [int][Math]::Round([double]$data.success * $total)
    $pct = [math]::Round(100.0 * $bad / $total, 2)
    $verdict = if ($pct -gt $spec.ThresholdPct) { "FAIL" } else { "ok  " }
    Write-Host ("{0}  {1}: {2}% errores ({3}/{4}), umbral {5}%" -f `
        $verdict, $verb, $pct, $bad, $total, $spec.ThresholdPct) `
        -ForegroundColor $(if ($pct -gt $spec.ThresholdPct) { "Red" } else { "Green" })

    if ($pct -gt $spec.ThresholdPct) {
        $failures += "$verb=$pct%"
    }
}

Write-Host ""
Write-Host "Resultados en: $OutDir" -ForegroundColor Cyan

if ($failures) {
    Fail ("umbral superado en: " + ($failures -join ", ") +
          " (perfil '$Profile', " + $spec.ThresholdPct + "%)")
}

Write-Host "ok: todos los verbos dentro del umbral del perfil '$Profile'." -ForegroundColor Green
exit 0
