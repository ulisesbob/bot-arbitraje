"""Comandos de Telegram del bot. Las funciones resp_* arman el texto a partir de
datos ya descargados (asi se pueden testear); manejar() es la que descarga."""

from __future__ import annotations

import json
import time
import urllib.request

import arbitraje as a

COMANDOS = [
    ("arbitraje", "mejores spreads entre exchanges ahora"),
    ("dolar", "la forma mas barata de comprar dolares"),
    ("btc", "donde comprar y vender Bitcoin mas barato"),
    ("eth", "donde comprar y vender Ethereum mas barato"),
    ("usdt", "donde comprar y vender USDT mas barato"),
    ("usdc", "donde comprar y vender USDC mas barato"),
    ("dai", "donde comprar y vender DAI mas barato"),
    ("umbral", "ver o cambiar el spread minimo de alerta, ej: /umbral 1.5"),
    ("ayuda", "esta lista"),
]

MONEDAS = {"btc": "Bitcoin", "eth": "Ethereum", "usdt": "USDT", "usdc": "USDC", "dai": "DAI"}


def resp_ayuda() -> str:
    lineas = [f"/{c} - {d}" for c, d in COMANDOS]
    return "<b>Comandos:</b>\n" + "\n".join(lineas)


def resp_moneda(coin: str, cot: dict, fiat: str = "ARS", ahora: float | None = None,
                max_antiguedad: int = 600, max_desvio_pct: float = 5.0, n: int = 3) -> str:
    ahora = ahora or time.time()
    validas = a.filtrar_cotizaciones(cot, max_antiguedad, ahora, max_desvio_pct=max_desvio_pct)
    if not validas:
        return f"No hay cotizaciones validas de {MONEDAS.get(coin, coin.upper())} ahora."
    compra = sorted(validas.items(), key=lambda kv: kv[1]["totalAsk"])[:n]
    venta = sorted(validas.items(), key=lambda kv: -kv[1]["totalBid"])[:n]
    nombre = MONEDAS.get(coin, coin.upper())
    out = [f"<b>{nombre} / {fiat}</b>", "", "Mas barato para <b>comprar</b>:"]
    out += [f"  {i + 1}. {ex}: {a.precio(q['totalAsk'])}" for i, (ex, q) in enumerate(compra)]
    out += ["", "Mejor para <b>vender</b>:"]
    out += [f"  {i + 1}. {ex}: {a.precio(q['totalBid'])}" for i, (ex, q) in enumerate(venta)]
    spread = (venta[0][1]["totalBid"] - compra[0][1]["totalAsk"]) / compra[0][1]["totalAsk"] * 100
    out += ["", f"Spread entre ambos: {spread:+.2f}%", "(precios con comisiones, segun CriptoYa)"]
    return "\n".join(out)


def resp_dolar(dolar: dict, stables: dict[str, dict], ahora: float | None = None,
               max_antiguedad: int = 600) -> str:
    """dolar: json de /api/dolar. stables: {"usdt": cotizaciones, "usdc": ..., "dai": ...}."""
    ahora = ahora or time.time()
    opciones = []  # (precio, etiqueta, como)

    def _get(d, *ks):
        for k in ks:
            d = d.get(k) if isinstance(d, dict) else None
            if d is None:
                return None
        return d

    if _get(dolar, "oficial", "ask"):
        opciones.append((dolar["oficial"]["ask"], "Oficial (banco)", "homebanking, con tope mensual y requisitos"))
    if _get(dolar, "blue", "ask"):
        opciones.append((dolar["blue"]["ask"], "Blue", "efectivo informal, sin registro"))
    if _get(dolar, "mep", "al30", "24hs", "price"):
        opciones.append((dolar["mep"]["al30"]["24hs"]["price"], "MEP (AL30)", "broker/bolsa, dolares en tu cuenta bancaria"))
    if _get(dolar, "ccl", "al30", "24hs", "price"):
        opciones.append((dolar["ccl"]["al30"]["24hs"]["price"], "CCL (AL30)", "broker, dolares en cuenta del exterior"))
    if _get(dolar, "tarjeta", "price"):
        opciones.append((dolar["tarjeta"]["price"], "Tarjeta", "consumos en el exterior con impuestos"))

    mejores_stable = []
    for coin, cot in stables.items():
        validas = a.filtrar_cotizaciones(cot, max_antiguedad, ahora)
        if validas:
            ex, q = min(validas.items(), key=lambda kv: kv[1]["totalAsk"])
            mejores_stable.append((q["totalAsk"], coin.upper(), ex))
    if mejores_stable:
        p, coin, ex = min(mejores_stable)
        opciones.append((p, f"Cripto ({coin} en {ex})", "compras la stablecoin en el exchange, retiro inmediato"))

    if not opciones:
        return "No pude obtener cotizaciones del dolar ahora."
    opciones.sort()
    out = ["<b>Dolar: de mas barato a mas caro</b>", ""]
    for i, (p, et, como) in enumerate(opciones):
        marca = " ⭐" if i == 0 else ""
        out.append(f"{i + 1}. <b>{et}</b>: ${p:,.0f}{marca}\n    {como}")
    if mejores_stable:
        out += ["", "Stablecoins mas baratas por exchange:"]
        for p, coin, ex in sorted(mejores_stable):
            out.append(f"  {coin}: {ex} a ${p:,.2f}")
    return "\n".join(out)


def resp_arbitraje(resultados: list[tuple[str, a.Oportunidad | None]], umbral: float) -> str:
    out = [f"<b>Mejor spread por par</b> (alerta si supera {umbral}%)", ""]
    for par, o in resultados:
        if o is None:
            out.append(f"{par.upper()}: sin datos")
            continue
        marca = " \U0001f6a8" if o.spread_pct >= umbral else ""
        out.append(f"{par.upper()}: {o.spread_pct:+.2f}%{marca}\n"
                   f"    comprar {o.comprar_en} {a.precio(o.precio_compra)} / vender {o.vender_en} {a.precio(o.precio_venta)}")
    return "\n".join(out)


def resp_umbral(cfg: dict, arg: str | None) -> str:
    if not arg:
        return f"Umbral actual: {cfg['umbral_pct']}%. Para cambiarlo: /umbral 1.5"
    try:
        nuevo = float(arg.replace(",", "."))
    except ValueError:
        return f"No entendi '{arg}'. Ejemplo: /umbral 1.5"
    if not 0 <= nuevo <= 50:
        return "Pone un valor entre 0 y 50."
    cfg["umbral_pct"] = nuevo
    a.guardar_config(cfg)
    return f"Listo, ahora aviso cuando el spread supere {nuevo}%."


# ---------- descarga + despacho ----------

def obtener_dolar() -> dict:
    req = urllib.request.Request("https://criptoya.com/api/dolar", headers={"User-Agent": "arbitraje-bot/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def manejar(texto: str, cfg: dict) -> str:
    partes = texto.strip().split()
    cmd = partes[0].lstrip("/").split("@")[0].lower()
    arg = partes[1] if len(partes) > 1 else None
    fiat = "ars"
    try:
        if cmd in ("start", "ayuda", "help"):
            return resp_ayuda()
        if cmd in MONEDAS:
            cot = a.obtener_cotizaciones(f"{cmd}/{fiat}", cfg["volumen"])
            return resp_moneda(cmd, cot, fiat.upper(), max_antiguedad=cfg["max_antiguedad_seg"],
                               max_desvio_pct=cfg["max_desvio_pct"])
        if cmd == "dolar":
            stables = {}
            for coin in ("usdt", "usdc", "dai"):
                try:
                    stables[coin] = a.obtener_cotizaciones(f"{coin}/{fiat}", cfg["volumen"])
                except Exception:  # noqa: BLE001
                    pass
            return resp_dolar(obtener_dolar(), stables, max_antiguedad=cfg["max_antiguedad_seg"])
        if cmd == "arbitraje":
            ahora = time.time()
            res = []
            for par in cfg["pares"]:
                try:
                    cot = a.obtener_cotizaciones(par, cfg["volumen"])
                    ops = a.detectar_oportunidades(cot, -100, cfg["max_antiguedad_seg"], ahora, par,
                                                   set(cfg["excluir_exchanges"]), cfg["max_desvio_pct"])
                    res.append((par, ops[0] if ops else None))
                except Exception:  # noqa: BLE001
                    res.append((par, None))
            return resp_arbitraje(res, cfg["umbral_pct"])
        if cmd == "umbral":
            return resp_umbral(cfg, arg)
    except Exception as e:  # noqa: BLE001
        return f"Error consultando CriptoYa: {e}"
    return "No conozco ese comando.\n\n" + resp_ayuda()
