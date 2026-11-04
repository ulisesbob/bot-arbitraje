#!/usr/bin/env bash
# Instala el bot como servicio en un servidor Ubuntu/Debian (VPS, Oracle Free Tier, Raspberry Pi).
# Uso, desde la carpeta del bot ya copiada al servidor:
#   sudo bash deploy/instalar_servidor.sh
# Requiere que config.json ya tenga telegram_token y telegram_chat_id.
set -euo pipefail

ORIGEN="$(cd "$(dirname "$0")/.." && pwd)"
DESTINO=/opt/bot-arbitraje

if [[ ! -f "$ORIGEN/config.json" ]]; then
  echo "Falta $ORIGEN/config.json con telegram_token y telegram_chat_id" >&2
  exit 1
fi

echo "[1/4] Python"
apt-get update -qq
apt-get install -y -qq python3 >/dev/null

echo "[2/4] Usuario y carpeta"
id -u bot >/dev/null 2>&1 || useradd --system --home "$DESTINO" --shell /usr/sbin/nologin bot
mkdir -p "$DESTINO"
cp "$ORIGEN/arbitraje.py" "$ORIGEN/comandos.py" "$ORIGEN/config.json" "$DESTINO/"
[[ -f "$ORIGEN/cooldown.json" ]] && cp "$ORIGEN/cooldown.json" "$DESTINO/" || true
chown -R bot:bot "$DESTINO"
chmod 600 "$DESTINO/config.json"

echo "[3/4] Servicio systemd"
cp "$ORIGEN/deploy/bot-arbitraje.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable bot-arbitraje >/dev/null
systemctl restart bot-arbitraje

echo "[4/4] Estado"
sleep 3
systemctl --no-pager --lines=8 status bot-arbitraje || true
echo
echo "Listo. Ver logs en vivo:  journalctl -u bot-arbitraje -f"
