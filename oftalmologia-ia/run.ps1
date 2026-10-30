# Oftalmología + IA — arranque en Windows PowerShell (equivalente a run.sh).
#   .\run.ps1            levanta todo      .\run.ps1 test     pruebas
#   .\run.ps1 eval       evaluación        .\run.ps1 eval mock
#   .\run.ps1 logs | stop | reset
# Si PowerShell bloquea el script:  powershell -ExecutionPolicy Bypass -File .\run.ps1
param([string]$Accion = "up", [string]$Opcion = "")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Falla($m) { Write-Host "X $m" -ForegroundColor Red; exit 1 }
function Valor($clave) {
  $linea = Get-Content .env -ErrorAction SilentlyContinue | Where-Object { $_ -match "^$clave=" } | Select-Object -Last 1
  if ($linea) { return ($linea -split "=", 2)[1].Trim().Trim('"') } else { return "" }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Falla "Docker no está instalado (instale Docker Desktop)." }
docker info *> $null; if ($LASTEXITCODE -ne 0) { Falla "Docker Desktop no está corriendo. Ábralo y reintente." }
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "! Se creó .env a partir de .env.example" -ForegroundColor Yellow }

switch ($Accion) {
  "up" {
    $p = Valor "LLM_PROVIDER"; if (-not $p) { $p = "groq" }
    if ($p -ne "mock" -and -not (Valor "$($p.ToUpper())_API_KEY")) {
      Write-Host "! Falta $($p.ToUpper())_API_KEY en .env: la IA responderá 'falta la llave' (o use LLM_PROVIDER=mock)." -ForegroundColor Yellow
    }
    docker compose up --build -d; if ($LASTEXITCODE -ne 0) { Falla "docker compose falló." }
    Write-Host "Esperando a la API..."
    for ($i = 0; $i -lt 90; $i++) {
      docker compose exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/salud', timeout=3)" *> $null
      if ($LASTEXITCODE -eq 0) { break }; Start-Sleep 2
    }
    $web = Valor "PUERTO_WEB"; if (-not $web) { $web = "8080" }
    Write-Host "OK Web: http://localhost:$web   API: http://localhost:8000/docs" -ForegroundColor Green
  }
  "test" { docker compose build backend; docker compose run --rm --no-deps backend pytest -v; docker compose build frontend }
  "eval" {
    docker compose build backend
    $extra = @(); if ($Opcion -eq "mock") { $extra = @("--proveedor", "mock") }
    docker compose run --rm --no-deps -v "${PWD}/eval:/eval" backend python /eval/run_eval.py @extra
  }
  "logs"  { docker compose logs -f backend }
  "stop"  { docker compose down }
  "reset" { docker compose down -v }
  default { Falla "Acción desconocida: $Accion" }
}
