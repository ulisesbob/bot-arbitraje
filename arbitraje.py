"""Bot de alertas de arbitraje de criptomonedas usando la API publica de CriptoYa.

Cada N segundos consulta criptoya.com para cada par configurado, busca el
exchange mas barato para comprar (totalAsk) y el mas caro para vender
(totalBid), y si el spread supera el umbral manda una alerta por Telegram
(si esta configurado) y por consola.

Uso:
    python arbitraje.py            # corre en loop
    python arbitraje.py --once     # una sola pasada y sale
    python arbitraje.py --test-telegram
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

API = "https://criptoya.com/api/{coin}/{fiat}/{volumen}"
CONFIG_PATH = Path(__file__).with_name("config.json")

CONFIG_DEFAULT = {
    "pares": ["usdt/ars", "usdc/ars", "dai/ars", "btc/ars", "eth/ars", "usdt/usd", "usdc/usd", "btc/usd", "eth/usd"],
    "volumen": 1000,
    "umbral_pct": 1.5,
    "intervalo_seg": 60,
    "max_antiguedad_seg": 600,
    "cooldown_seg": 900,
    "excluir_exchanges": [],
    "max_desvio_pct": 5.0,
    "max_desvio_usd_pct": 3.0,
    "incluir_pasos": True,
    "rulos": True,
    "umbral_rulo_pct": 2.0,
    "volumen_rulo": 100000,
    "max_patas": 4,
    "telegram_token": "",
    "telegram_chat_id": "",
}


@dataclass
class Oportunidad:
    par: str
    comprar_en: str
    precio_compra: float
    vender_en: str
    precio_venta: float
    spread_pct: float


# ---------- logica pura ----------

def es_p2p(nombre: str) -> bool:
    """Exchanges P2P: el precio es la oferta de una persona, no una cotizacion firme."""
    return nombre.endswith("p2p") or nombre == "p2pme"


AVISO_P2P = ("\U0001f465 <b>P2P</b>: es el precio publicado por una persona, no una cotización firme. "
             "Verificá precio, monto y método de pago antes de operar.")


def marcar(nombre: str) -> str:
    return nombre + (" \U0001f465" if es_p2p(nombre) else "")


def desvio_para(par: str, cfg: dict) -> float:
    """Tolerancia de desvio respecto de la mediana segun el fiat del par. En los pares en
    dolares es mas estricta: ahi conviven dolares locales y dolares de cuentas en el exterior
    (Xapo, Astropay) que cotizan 4-6% mas bajo sin que eso sea arbitrable."""
    fiat = par.lower().split("/")[-1]
    if fiat == "usd":
        return cfg.get("max_desvio_usd_pct", cfg["max_desvio_pct"])
    return cfg["max_desvio_pct"]


def esta_excluido(nombre: str, excluir: set) -> bool:
    """Nombre exacto, o patron con comodin al principio: "*p2p" excluye todo lo que termine en p2p."""
    if nombre in excluir:
        return True
    return any(p.startswith("*") and nombre.endswith(p[1:]) for p in excluir)


def filtrar_cotizaciones(cotizaciones: dict, max_antiguedad: int, ahora: float,
                         excluir: set | None = None, max_desvio_pct: float = 5.0) -> dict:
    """Descarta exchanges con precio 0, datos viejos, excluidos por config, o con
    precios muy alejados de la mediana (tipico de P2P con ofertas basura)."""
    excluir = excluir or set()
    validas = {}
    for nombre, q in cotizaciones.items():
        if esta_excluido(nombre, excluir) or not isinstance(q, dict):
            continue
        ask = q.get("totalAsk") or 0
        bid = q.get("totalBid") or 0
        t = q.get("time") or 0
        if ask <= 0 or bid <= 0:
            continue
        if ahora - t > max_antiguedad:
            continue
        validas[nombre] = q
    if len(validas) >= 3 and max_desvio_pct > 0:
        mids = sorted((q["totalAsk"] + q["totalBid"]) / 2 for q in validas.values())
        mediana = mids[len(mids) // 2]
        lim = max_desvio_pct / 100
        validas = {n: q for n, q in validas.items()
                   if abs(q["totalAsk"] / mediana - 1) <= lim and abs(q["totalBid"] / mediana - 1) <= lim}
    return validas


def detectar_oportunidades(cotizaciones: dict, umbral_pct: float, max_antiguedad: int,
                           ahora: float, par: str = "", excluir: set | None = None,
                           max_desvio_pct: float = 5.0) -> list[Oportunidad]:
    """Devuelve todas las combinaciones comprar-en-A / vender-en-B con spread >= umbral,
    ordenadas de mayor a menor spread."""
    validas = filtrar_cotizaciones(cotizaciones, max_antiguedad, ahora, excluir, max_desvio_pct)
    ops = []
    for ex_compra, qc in validas.items():
        for ex_venta, qv in validas.items():
            if ex_compra == ex_venta:
                continue
            compra, venta = qc["totalAsk"], qv["totalBid"]
            spread = (venta - compra) / compra * 100
            if spread >= umbral_pct:
                ops.append(Oportunidad(par, ex_compra, compra, ex_venta, venta, spread))
    ops.sort(key=lambda o: o.spread_pct, reverse=True)
    return ops


class Cooldown:
    """Evita repetir la misma alerta (par + exchanges) durante N segundos.
    Si se le da un archivo, recuerda las alertas entre reinicios."""

    def __init__(self, segundos: int, archivo: Path | None = None, estado: dict | None = None):
        """archivo: persiste en disco (bot local, Actions). estado: dict en memoria que se
        modifica en el lugar (api/scan.py, donde el estado viaja en la peticion)."""
        self.segundos = segundos
        self.archivo = archivo
        self._ultimo: dict[str, float] = estado if estado is not None else {}
        if archivo and archivo.exists() and estado is None:
            try:
                self._ultimo = json.loads(archivo.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._ultimo = {}

    @property
    def estado(self) -> dict:
        return self._ultimo

    def permitir(self, par: str, comprar_en: str, vender_en: str, ahora: float) -> bool:
        clave = f"{par}|{comprar_en}|{vender_en}"
        previo = self._ultimo.get(clave)
        if previo is not None and ahora - previo < self.segundos:
            return False
        self._ultimo[clave] = ahora
        for k in [k for k, v in self._ultimo.items() if ahora - v >= self.segundos]:
            del self._ultimo[k]  # olvidar las vencidas para que el estado no crezca
        if self.archivo:
            try:
                self.archivo.write_text(json.dumps(self._ultimo), encoding="utf-8")
            except OSError as e:
                print(f"[cooldown] no pude guardar {self.archivo.name}: {e}")
        return True


# ---------- IO ----------

def limpiar(valor: str) -> str:
    """Saca lo que PowerShell agrega al cargar variables por tuberia: BOM (U+FEFF) al
    principio y salto de linea al final. str.strip() no quita el BOM."""
    return (valor or "").strip().strip("﻿").strip()


def cargar_config(escribir: bool = True) -> dict:
    """escribir=False para entornos de solo lectura (Vercel): no crea config.json."""
    cfg = dict(CONFIG_DEFAULT)
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig")))  # -sig: tolera BOM de PowerShell
    elif escribir:
        CONFIG_PATH.write_text(json.dumps(CONFIG_DEFAULT, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[info] cree {CONFIG_PATH.name} con valores por defecto, editalo a gusto")
    # el archivo manda; las variables de entorno solo rellenan campos vacios
    cfg["telegram_token"] = limpiar(cfg["telegram_token"] or os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    cfg["telegram_chat_id"] = limpiar(str(cfg["telegram_chat_id"] or os.environ.get("TELEGRAM_CHAT_ID", "")))
    return cfg


def guardar_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def obtener_cotizaciones(par: str, volumen: float, reintentos: int = 2) -> dict:
    coin, fiat = par.lower().split("/")
    url = API.format(coin=coin, fiat=fiat, volumen=volumen)
    req = urllib.request.Request(url, headers={"User-Agent": "arbitraje-bot/1.0"})
    for intento in range(reintentos + 1):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code != 429 or intento == reintentos:
                raise
            time.sleep(1.5 * (intento + 1))  # CriptoYa limita rafagas: esperar y reintentar
    raise RuntimeError("inalcanzable")


def obtener_dolar() -> dict:
    req = urllib.request.Request("https://criptoya.com/api/dolar", headers={"User-Agent": "arbitraje-bot/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def descargar_varios(pares: list[str], volumen: float) -> dict[str, dict | None]:
    """Descarga varios pares en paralelo. None donde fallo."""
    from concurrent.futures import ThreadPoolExecutor

    def uno(par):
        try:
            return par, obtener_cotizaciones(par, volumen)
        except Exception as e:  # noqa: BLE001
            print(f"[{par}] error consultando CriptoYa: {e}")
            return par, None
    # pocos hilos: CriptoYa devuelve 429 si le llegan muchas peticiones juntas
    with ThreadPoolExecutor(max_workers=min(3, max(1, len(pares)))) as ex:
        return dict(ex.map(uno, pares))


def enviar_telegram(token: str, chat_id: str, texto: str) -> bool:
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    datos = urllib.parse.urlencode({"chat_id": chat_id, "text": texto, "parse_mode": "HTML"}).encode()
    try:
        with urllib.request.urlopen(url, data=datos, timeout=20) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        print(f"[telegram] error {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"[telegram] error: {e}")
        return False


def precio(x: float) -> str:
    """4 decimales para precios chicos (pares en USD), 2 para el resto."""
    return f"{x:,.4f}" if x < 10 else f"{x:,.2f}"


SEP = "─" * 24  # linea horizontal
ICONO = {"btc": "₿", "eth": "Ξ", "usdt": "\U0001f4b5", "usdc": "\U0001f4b5", "dai": "\U0001f4b5"}


def pasos(o: Oportunidad) -> str:
    coin = o.par.upper().split("/")[0]
    return (
        f"\n\n\U0001f4cb <b>Cómo ejecutarlo</b>\n"
        f"1️⃣ En <b>{o.comprar_en}</b>: comprá {coin} con el fiat que ya tengas depositado.\n"
        f"2️⃣ En <b>{o.vender_en}</b>: Depositar {coin}, elegí una red barata (TRC20, Polygon, Solana) y copiá la dirección.\n"
        f"3️⃣ En <b>{o.comprar_en}</b>: Retirar {coin} a esa dirección por <b>la misma red</b>. Primero un monto chico de prueba.\n"
        f"4️⃣ Cuando llegue, vendé el {coin} en <b>{o.vender_en}</b>. Verificá que el precio siga antes de confirmar.\n"
        f"5️⃣ Restá comisión de red y de retiro: si queda menos que el spread, no vale la pena."
    )


def telegram_api(token: str, metodo: str, http_timeout: int = 20, **params) -> dict:
    url = f"https://api.telegram.org/bot{token}/{metodo}"
    datos = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}).encode()
    with urllib.request.urlopen(url, data=datos, timeout=http_timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def registrar_comandos(token: str) -> None:
    """Carga el menu de comandos que Telegram muestra al tipear /."""
    from comandos import COMANDOS
    try:
        telegram_api(token, "setMyCommands",
                     commands=json.dumps([{"command": c, "description": d} for c, d in COMANDOS]))
    except Exception as e:  # noqa: BLE001
        print(f"[telegram] no pude registrar el menu de comandos: {e}")


def atender_comandos(cfg: dict, offset: int | None, espera: int) -> int | None:
    """Espera hasta `espera` segundos mensajes nuevos (long polling) y responde los comandos.
    Devuelve el offset para la proxima llamada."""
    from comandos import manejar
    token, chat_id = cfg["telegram_token"], cfg["telegram_chat_id"]
    try:
        res = telegram_api(token, "getUpdates", http_timeout=espera + 10, offset=offset, timeout=espera)
    except Exception as e:  # noqa: BLE001
        print(f"[telegram] error leyendo mensajes: {e}")
        time.sleep(min(espera, 5))
        return offset
    for u in res.get("result", []):
        offset = u["update_id"] + 1
        msg = u.get("message") or {}
        texto = msg.get("text") or ""
        if str(msg.get("chat", {}).get("id")) != str(chat_id):
            continue  # solo respondo a tu chat
        if not texto.startswith("/"):
            continue
        print(f"[cmd] {texto}")
        enviar_telegram(token, chat_id, manejar(texto, cfg))
    return offset


def confirmar_mensajes(token: str, offset: int | None) -> None:
    """Le avisa a Telegram que ya procesamos hasta `offset`, para que no los vuelva a
    entregar en la proxima corrida (necesario en modo --ciclo, donde el proceso termina)."""
    if offset is None:
        return
    try:
        telegram_api(token, "getUpdates", offset=offset, timeout=0, limit=1)
    except Exception as e:  # noqa: BLE001
        print(f"[telegram] no pude confirmar mensajes: {e}")


def ciclo(cfg: dict, cooldown: Cooldown, sin_comandos: bool = False) -> None:
    """Una corrida completa para entornos sin proceso permanente (GitHub Actions, cron):
    escanea, responde los comandos que llegaron desde la ultima vez, y termina.
    sin_comandos=True cuando los comandos los atiende el webhook (api/telegram.py)."""
    pasada(cfg, cooldown)
    if not sin_comandos and cfg["telegram_token"] and cfg["telegram_chat_id"]:
        offset = atender_comandos(cfg, None, espera=0)
        confirmar_mensajes(cfg["telegram_token"], offset)


def alternativas(validas: dict, o: Oportunidad, n: int = 2) -> tuple[list, list]:
    """Otros lugares donde comprar (asks mas baratos) y vender (bids mas altos), sin los elegidos."""
    compras = sorted(((ex, q["totalAsk"]) for ex, q in validas.items() if ex != o.comprar_en), key=lambda x: x[1])[:n]
    ventas = sorted(((ex, q["totalBid"]) for ex, q in validas.items() if ex != o.vender_en), key=lambda x: -x[1])[:n]
    return compras, ventas


def formatear(o: Oportunidad, volumen: float, incluir_pasos: bool = True,
              alternativas: tuple[list, list] | None = None) -> str:
    coin, fiat = o.par.upper().split("/")
    ganancia = volumen * o.spread_pct / 100
    c, v = marcar(o.comprar_en), marcar(o.vender_en)
    ancho = max(len(c), len(v))
    msg = (
        f"\U0001f6a8 <b>ARBITRAJE {coin}/{fiat}</b>   ▲ <b>+{o.spread_pct:.2f}%</b>\n"
        f"{SEP}\n"
        f"<pre>"
        f"\U0001f7e2 Comprar  {c:<{ancho}}  {precio(o.precio_compra)}\n"
        f"\U0001f534 Vender   {v:<{ancho}}  {precio(o.precio_venta)}"
        f"</pre>\n"
        f"\U0001f4b0 Ganancia bruta: <b>~{ganancia:,.0f} {fiat}</b> por cada {volumen:,.0f} {fiat}\n"
        f"<i>Precios con comisiones de CriptoYa, sin transferencias ni retiros.</i>"
    )
    compras, ventas = alternativas or ([], [])
    if compras or ventas:
        w = max(len(marcar(ex)) for ex, _ in compras + ventas)
        filas = [f"comprar  {marcar(ex):<{w}}  {precio(p)}" for ex, p in compras]
        filas += [f"vender   {marcar(ex):<{w}}  {precio(p)}" for ex, p in ventas]
        msg += "\n\U0001f501 <b>Otras opciones</b>\n<pre>" + "\n".join(filas) + "</pre>"
    p2p = [o.comprar_en, o.vender_en] + [ex for ex, _ in compras + ventas]
    if any(es_p2p(x) for x in p2p):
        msg += "\n" + AVISO_P2P
    if incluir_pasos:
        msg += pasos(o)
    return msg


def texto_plano(html: str) -> str:
    for tag in ("<b>", "</b>", "<i>", "</i>", "<pre>", "</pre>", "<code>", "</code>"):
        html = html.replace(tag, "")
    return html


def pasada(cfg: dict, cooldown: Cooldown, mostrar_resumen: bool = True,
           rulos_abiertos: dict | None = None) -> list[Oportunidad]:
    """Una pasada completa: arbitraje simple + rulos.
    rulos_abiertos: estado de rulos en memoria (se modifica en el lugar); si es None se
    usa el archivo rulos.json."""
    ahora = time.time()
    excluir = set(cfg["excluir_exchanges"])
    alertadas = []
    cotizaciones = descargar_varios(cfg["pares"], cfg["volumen"])
    for par in cfg["pares"]:
        cot = cotizaciones.get(par)
        if cot is None:
            continue
        desvio = desvio_para(par, cfg)
        ops = detectar_oportunidades(cot, cfg["umbral_pct"], cfg["max_antiguedad_seg"], ahora, par, excluir, desvio)
        if mostrar_resumen:
            todas = detectar_oportunidades(cot, -100, cfg["max_antiguedad_seg"], ahora, par, excluir, desvio)
            if todas:
                m = todas[0]
                print(f"[{par}] mejor spread {m.spread_pct:+.2f}%  "
                      f"comprar {m.comprar_en} {precio(m.precio_compra)} / vender {m.vender_en} {precio(m.precio_venta)}")
            else:
                print(f"[{par}] sin cotizaciones validas")
        if not ops:
            continue
        o = ops[0]  # solo la mejor combinacion por par, para no spamear
        if not cooldown.permitir(par, o.comprar_en, o.vender_en, ahora):
            continue
        validas = filtrar_cotizaciones(cot, cfg["max_antiguedad_seg"], ahora, excluir, desvio)
        msg = formatear(o, cfg["volumen"], cfg["incluir_pasos"], alternativas(validas, o))
        print("\n" + texto_plano(msg) + "\n")
        enviar_telegram(cfg["telegram_token"], cfg["telegram_chat_id"], msg)
        alertadas.append(o)
    if cfg.get("rulos"):
        import rulos
        try:
            dolar = obtener_dolar()
        except Exception as e:  # noqa: BLE001
            print(f"[rulos] error consultando el dolar: {e}")
            dolar = None
        if rulos_abiertos is None:
            rulos.correr(cfg, cotizaciones, dolar, Path(__file__).with_name("rulos.json"), ahora)
        else:
            _, _, nuevo = rulos.procesar(cfg, cotizaciones, dolar, rulos_abiertos, ahora)
            rulos_abiertos.clear()
            rulos_abiertos.update(nuevo)
    return alertadas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true", help="una sola pasada y salir")
    ap.add_argument("--ciclo", action="store_true",
                    help="una pasada + responder comandos pendientes y salir (para GitHub Actions / cron)")
    ap.add_argument("--sin-comandos", action="store_true",
                    help="con --ciclo: no leer mensajes (los atiende el webhook de Vercel)")
    ap.add_argument("--test-telegram", action="store_true", help="manda un mensaje de prueba y sale")
    args = ap.parse_args()

    cfg = cargar_config()
    if args.test_telegram:
        ok = enviar_telegram(cfg["telegram_token"], cfg["telegram_chat_id"], "✅ Bot de arbitraje conectado")
        print("telegram OK" if ok else "telegram FALLO (revisa token/chat_id)")
        return 0 if ok else 1

    if not cfg["telegram_token"]:
        print("[info] sin Telegram configurado: las alertas salen solo por consola")
    cooldown = Cooldown(cfg["cooldown_seg"], Path(__file__).with_name("cooldown.json"))
    print(f"[info] pares={cfg['pares']} volumen={cfg['volumen']} umbral={cfg['umbral_pct']}% "
          f"cada {cfg['intervalo_seg']}s")
    if args.ciclo:
        if cfg["telegram_token"] and not args.sin_comandos:
            registrar_comandos(cfg["telegram_token"])
        ciclo(cfg, cooldown, sin_comandos=args.sin_comandos)
        return 0
    con_comandos = bool(cfg["telegram_token"] and cfg["telegram_chat_id"]) and not args.once
    if con_comandos:
        registrar_comandos(cfg["telegram_token"])
        print("[info] comandos de Telegram activos: /ayuda para verlos")
    offset = None
    proximo_scan = 0.0
    try:
        while True:
            if time.time() >= proximo_scan:
                pasada(cfg, cooldown)
                if args.once:
                    return 0
                proximo_scan = time.time() + cfg["intervalo_seg"]
            espera = max(1, int(proximo_scan - time.time()))
            if con_comandos:
                offset = atender_comandos(cfg, offset, min(espera, 25))
            else:
                time.sleep(espera)
    except KeyboardInterrupt:
        print("\n[info] chau")
        return 0


if __name__ == "__main__":
    sys.exit(main())
