# Despliega el "reloj" en Cloudflare Workers: cron cada minuto que dispara el escaneo en Vercel.
# Correr desde la carpeta cripto-arbitraje:
#   powershell -ExecutionPolicy Bypass -File deploy\cloudflare_setup.ps1
# Requiere: cuenta de Cloudflare y haber hecho  npx wrangler login
# Tambien redespliega Vercel para que exista /api/scan.

$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..")
function Fallar($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

$cfg = Get-Content "config.json" -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $cfg.webhook_secret) { Fallar "config.json no tiene webhook_secret (corre primero deploy\vercel_setup.ps1)" }

Write-Host "[1/5] Redesplegando Vercel (endpoint /api/scan)"
vercel --prod --yes
if ($LASTEXITCODE -ne 0) { Fallar "vercel --prod fallo" }

Set-Location "cloudflare"

Write-Host "[2/5] Verificando sesion de Cloudflare"
npx wrangler whoami
if ($LASTEXITCODE -ne 0) { Fallar "no hay sesion: corre  npx wrangler login  y volve a ejecutar este script" }

Write-Host "[3/5] Namespace KV para el estado"
$toml = Get-Content "wrangler.toml" -Raw
if ($toml -match 'id = "REEMPLAZAR_ID"') {
    $salida = npx wrangler kv namespace create ESTADO 2>&1 | Out-String
    Write-Host $salida
    if ($salida -match 'id\s*=\s*"([0-9a-f]{32})"') {
        $id = $Matches[1]
    } elseif ($salida -match '"id":\s*"([0-9a-f]{32})"') {
        $id = $Matches[1]
    } else {
        Fallar "no pude leer el id del namespace en la salida de wrangler"
    }
    $toml = $toml -replace 'id = "REEMPLAZAR_ID"', ('id = "' + $id + '"')
    Set-Content "wrangler.toml" -Value $toml -Encoding UTF8
    Write-Host "    namespace creado: $id"
} else {
    Write-Host "    ya estaba configurado"
}

Write-Host "[4/5] Secreto del escaneo (mismo que el webhook)"
$cfg.webhook_secret | npx wrangler secret put SCAN_SECRET
if ($LASTEXITCODE -ne 0) { Fallar "no pude cargar SCAN_SECRET" }

Write-Host "[5/5] Desplegando el worker"
npx wrangler deploy
if ($LASTEXITCODE -ne 0) { Fallar "wrangler deploy fallo" }

Write-Host ""
Write-Host "Listo. El reloj corre cada minuto. Avisale a Claude para que verifique y apague GitHub Actions."
