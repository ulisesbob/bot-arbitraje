# Configura y despliega el webhook de comandos en Vercel.
# Correr desde la carpeta cripto-arbitraje:  powershell -ExecutionPolicy Bypass -File deploy\vercel_setup.ps1
# Requiere: vercel CLI logueado (vercel login) y config.json con telegram_token y telegram_chat_id.

# Vercel escribe su progreso por stderr; con "Stop" PowerShell 5.1 lo toma como error fatal.
$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..")

function Fallar($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

$cfgPath = "config.json"
$cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $cfg.telegram_token -or -not $cfg.telegram_chat_id) {
    Fallar "config.json no tiene telegram_token / telegram_chat_id"
}

# Secreto del webhook: Telegram lo manda en cada request y la funcion lo verifica.
if (-not $cfg.PSObject.Properties["webhook_secret"] -or -not $cfg.webhook_secret) {
    $bytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $secreto = ([Convert]::ToBase64String($bytes)) -replace "[^A-Za-z0-9]", ""
    $cfg | Add-Member -NotePropertyName webhook_secret -NotePropertyValue $secreto -Force
    $cfg | ConvertTo-Json -Depth 5 | Set-Content $cfgPath -Encoding UTF8
    Write-Host "[1/4] webhook_secret generado y guardado en config.json"
} else {
    Write-Host "[1/4] webhook_secret ya existia en config.json"
}

Write-Host "[2/4] Vinculando proyecto bot-arbitraje en Vercel"
vercel link --yes --project bot-arbitraje
if ($LASTEXITCODE -ne 0) { Fallar "vercel link fallo" }

Write-Host "[3/4] Cargando variables de entorno (production)"
foreach ($par in @(
    @("TELEGRAM_BOT_TOKEN", $cfg.telegram_token),
    @("TELEGRAM_CHAT_ID",   [string]$cfg.telegram_chat_id),
    @("WEBHOOK_SECRET",     $cfg.webhook_secret))) {
    $nombre = $par[0]; $valor = $par[1]
    # si ya existe la borramos para reemplazarla (si no existe, falla y no importa)
    vercel env rm $nombre production --yes
    $valor | vercel env add $nombre production
    if ($LASTEXITCODE -ne 0) { Fallar "no pude cargar $nombre" }
    Write-Host "    $nombre cargada"
}

Write-Host "[4/4] Desplegando a produccion"
vercel --prod --yes
if ($LASTEXITCODE -ne 0) { Fallar "el deploy fallo" }

Write-Host ""
Write-Host "Listo. Ahora avisale a Claude que termino, para que registre el webhook en Telegram."
