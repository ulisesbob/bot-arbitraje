"""Escaneo sin estado en disco, para dispararlo desde afuera cada minuto (Cloudflare Worker).

POST /api/scan  con header  X-Scan-Secret: <WEBHOOK_SECRET>
Body:      {"estado": {"cooldown": {...}, "rulos": {...}}}   (lo que devolvio la vez anterior, o {})
Respuesta: {"estado": {...}, "alertas": n, "mejor": "...", "ms": t}

El que llama guarda `estado` y lo manda en la proxima peticion. Asi Vercel, que no puede
escribir archivos, igual recuerda que alertas mando y que rulos estan abiertos.
"""

import io
import json
import os
import sys
import time
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import arbitraje as a  # noqa: E402


def escanear(estado: dict) -> dict:
    """Corre una pasada con el estado dado y devuelve el estado nuevo mas un resumen."""
    t0 = time.time()
    cfg = a.cargar_config(escribir=False)
    cooldown_estado = dict(estado.get("cooldown") or {})
    rulos_abiertos = dict(estado.get("rulos") or {})
    abiertas = dict(estado.get("abiertas") or {})
    cooldown = a.Cooldown(cfg["cooldown_seg"], estado=cooldown_estado)
    salida = io.StringIO()
    with redirect_stdout(salida):
        alertadas = a.pasada(cfg, cooldown, mostrar_resumen=True, rulos_abiertos=rulos_abiertos, abiertas=abiertas)
    log = salida.getvalue()
    print(log, end="")
    mejor = [l for l in log.splitlines() if "mejor spread" in l or "[rulos] mejor" in l]
    return {
        "estado": {"cooldown": cooldown.estado, "rulos": rulos_abiertos, "abiertas": abiertas},
        "alertas": len(alertadas),
        "abiertas": len(abiertas),
        "rulos_abiertos": len(rulos_abiertos),
        "resumen": mejor,
        "ms": int((time.time() - t0) * 1000),
    }


class handler(BaseHTTPRequestHandler):  # noqa: N801
    def _responder(self, codigo: int, cuerpo: dict) -> None:
        datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self) -> None:  # noqa: N802
        self._responder(200, {"ok": True, "uso": "POST con X-Scan-Secret y body {\"estado\": {...}}"})

    def do_POST(self) -> None:  # noqa: N802
        secreto = a.limpiar(os.environ.get("WEBHOOK_SECRET", ""))
        if secreto and a.limpiar(self.headers.get("X-Scan-Secret") or "") != secreto:
            self._responder(403, {"error": "secreto invalido"})
            return
        largo = int(self.headers.get("Content-Length") or 0)
        try:
            cuerpo = json.loads(self.rfile.read(largo) or b"{}")
            resultado = escanear(cuerpo.get("estado") or {})
            self._responder(200, resultado)
        except Exception as e:  # noqa: BLE001
            print(f"[scan] error: {e}")
            self._responder(500, {"error": str(e)})
