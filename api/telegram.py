"""Webhook de Telegram en Vercel: responde los comandos al instante.

Telegram manda un POST aca por cada mensaje. Se valida el secreto del webhook,
se verifica que el chat sea el configurado, y se responde con comandos.manejar().
Las alertas automaticas siguen corriendo en GitHub Actions (arbitraje.py --ciclo --sin-comandos).

Variables de entorno necesarias en Vercel:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, WEBHOOK_SECRET
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import arbitraje as a  # noqa: E402
import comandos as c  # noqa: E402


def procesar(update: dict) -> str:
    """Devuelve una descripcion de lo que hizo (para el log)."""
    cfg = a.cargar_config(escribir=False)
    msg = update.get("message") or update.get("edited_message") or {}
    chat_id = str(msg.get("chat", {}).get("id", ""))
    texto = msg.get("text") or ""
    if chat_id != str(cfg["telegram_chat_id"]):
        return f"ignorado: chat {chat_id}"
    if not texto.startswith("/"):
        return "ignorado: no es comando"
    respuesta = c.manejar(texto, cfg, persistente=False)
    ok = a.enviar_telegram(cfg["telegram_token"], chat_id, respuesta)
    return f"{texto} -> {'ok' if ok else 'fallo al enviar'}"


class handler(BaseHTTPRequestHandler):  # noqa: N801  (nombre que exige Vercel)
    def _responder(self, codigo: int, cuerpo: str) -> None:
        datos = cuerpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self) -> None:  # noqa: N802
        self._responder(200, "bot arbitraje: webhook activo")

    def do_POST(self) -> None:  # noqa: N802
        secreto = os.environ.get("WEBHOOK_SECRET", "").strip()
        if secreto and self.headers.get("X-Telegram-Bot-Api-Secret-Token") != secreto:
            self._responder(403, "secreto invalido")
            return
        largo = int(self.headers.get("Content-Length") or 0)
        try:
            update = json.loads(self.rfile.read(largo) or b"{}")
            resultado = procesar(update)
        except Exception as e:  # noqa: BLE001
            resultado = f"error: {e}"
        print(f"[webhook] {resultado}")
        # Siempre 200: si devolvemos error, Telegram reintenta el mismo mensaje una y otra vez
        self._responder(200, resultado)
