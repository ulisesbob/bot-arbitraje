"""Comandos de Telegram del bot. Las funciones resp_* arman el texto a partir de
datos ya descargados (asi se pueden testear); manejar() es la que descarga.

Formato: HTML de Telegram. <pre> para tablas alineadas (monoespaciado)."""

from __future__ import annotations

import json
import time

import arbitraje as a

COMANDOS = [
    ("arbitraje", "mejores spreads entre exchanges ahora"),
    ("rulos", "mejores rulos de 3 o 4 patas (pesos > dolar/stable > pesos)"),
    ("dolar", "la forma mas barata de comprar dolares"),
    ("btc", "donde comprar y vender Bitcoin mas barato"),
    ("eth", "donde comprar y vender Ethereum mas barato"),
    ("usdt", "donde comprar y vender USDT mas barato"),
    ("usdc", "donde comprar y vender USDC mas barato"),
    ("dai", "donde comprar y vender DAI mas barato"),
    ("p2p", "arbitraje dentro de Binance P2P: puntas, cruce, anuncios sugeridos y que hacer"),
    ("capital", "con cuanta plata arrancas: reparto, compra inicial y anuncios, ej: /capital 160000"),
    ("umbral", "ver o cambiar el spread minimo de alerta, ej: /umbral 1.5"),
    ("ayuda", "esta lista"),
]

MONEDAS = {"btc": "Bitcoin", "eth": "Ethereum", "usdt": "USDT", "usdc": "USDC", "dai": "DAI"}

SEP = a.SEP


def _semaforo(spread: float, umbral: float) -> str:
    if spread >= umbral:
        return "\U0001f7e2"  # verde: alerta
    if spread > 0:
        return "\U0001f7e1"  # amarillo: positivo pero chico
    return "\U0001f534"      # rojo: negativo


def resp_ayuda() -> str:
    grupos = [
        ("\U0001f4ca Mercado", ["arbitraje", "rulos", "p2p", "capital", "dolar"]),
        ("\U0001fa99 Por moneda", ["btc", "eth", "usdt", "usdc", "dai"]),
        ("⚙️ Configuración", ["umbral", "ayuda"]),
    ]
    desc = dict(COMANDOS)
    out = ["\U0001f916 <b>Bot de arbitraje</b>", SEP]
    for titulo, cmds in grupos:
        out.append(f"<b>{titulo}</b>")
        out += [f"/{c} — {desc[c]}" for c in cmds]
        out.append("")
    extras = sorted({p.split("/")[0] for p in a.CONFIG_DEFAULT["pares"]} - set(MONEDAS))
    if extras:
        out.append("También: " + " ".join(f"/{c}" for c in extras))
        out.append("")
    out.append("<i>Las alertas automáticas llegan solas cuando un spread supera el umbral.</i>")
    return "\n".join(out)


FIATS = {"ARS": ("\U0001f1e6\U0001f1f7", "En pesos"), "USD": ("\U0001f1fa\U0001f1f8", "En dólares")}


def _bloque_fiat(fiat: str, cot: dict | None, ahora: float, max_antiguedad: int,
                 max_desvio_pct: float, n: int, excluir: set | None) -> tuple[list[str], bool]:
    """Tablas de comprar/vender de una moneda contra un fiat. Devuelve (lineas, hay_p2p)."""
    bandera, titulo = FIATS.get(fiat, ("", f"En {fiat}"))
    validas = a.filtrar_cotizaciones(cot or {}, max_antiguedad, ahora, excluir, max_desvio_pct)
    if not validas:
        return [f"{bandera} <b>{titulo} ({fiat})</b>: sin cotizaciones válidas ahora"], False
    compra = sorted(((ex, q) for ex, q in validas.items() if q["totalAsk"]), key=lambda kv: kv[1]["totalAsk"])[:n]
    venta = sorted(((ex, q) for ex, q in validas.items() if q["totalBid"]), key=lambda kv: -kv[1]["totalBid"])[:n]
    if not compra or not venta:
        return [f"{bandera} <b>{titulo} ({fiat})</b>: sin cotizaciones válidas ahora"], []
    ancho = max(len(a.marcar(ex)) for ex, _ in compra + venta)

    def tabla(filas, campo):
        return "<pre>" + "\n".join(
            f"{i + 1}. {a.marcar(ex):<{ancho}}  {a.precio(q[campo]):>14}" for i, (ex, q) in enumerate(filas)
        ) + "</pre>"

    spread = (venta[0][1]["totalBid"] - compra[0][1]["totalAsk"]) / compra[0][1]["totalAsk"] * 100
    lineas = [
        f"{bandera} <b>{titulo} ({fiat})</b>",
        "\U0001f7e2 Comprar más barato",
        tabla(compra, "totalAsk"),
        "\U0001f534 Vender mejor",
        tabla(venta, "totalBid"),
        f"↔️ Spread entre ambos: <b>{spread:+.2f}%</b>",
    ]
    return lineas, any(a.es_p2p(ex) for ex, _ in compra + venta)


def resp_moneda(coin: str, cot: dict, fiat: str = "ARS", ahora: float | None = None,
                max_antiguedad: int = 600, max_desvio_pct: float = 5.0, n: int = 3,
                excluir: set | None = None, cot_usd: dict | None = None,
                max_desvio_usd_pct: float | None = None, excluir_usd: set | None = None) -> str:
    """Una moneda contra `fiat`; si se pasa cot_usd, agrega el bloque en dólares."""
    ahora = ahora or time.time()
    nombre = MONEDAS.get(coin, coin.upper())
    icono = a.ICONO.get(coin, "\U0001fa99")
    bloques = [(fiat, cot, max_desvio_pct, excluir)]
    if cot_usd is not None and fiat != "USD":
        bloques.append(("USD", cot_usd, max_desvio_usd_pct if max_desvio_usd_pct is not None else max_desvio_pct,
                        excluir_usd if excluir_usd is not None else excluir))
    out = [f"{icono} <b>{nombre}</b>", SEP]
    hay_p2p = False
    for i, (f, c, desvio, excl) in enumerate(bloques):
        if i:
            out += ["", SEP]
        lineas, p2p = _bloque_fiat(f, c, ahora, max_antiguedad, desvio, n, excl)
        out += lineas
        hay_p2p |= p2p
    out.append("<i>Precios con comisiones, según CriptoYa.</i>")
    if hay_p2p:
        out.append(a.AVISO_P2P)
    return "\n".join(out)


def resp_dolar(dolar: dict, stables: dict[str, dict], ahora: float | None = None,
               max_antiguedad: int = 600, excluir: set | None = None) -> str:
    """dolar: json de /api/dolar. stables: {"usdt": cotizaciones, "usdc": ..., "dai": ...}."""
    ahora = ahora or time.time()
    opciones = []  # (precio, etiqueta, nota)

    def _get(d, *ks):
        for k in ks:
            d = d.get(k) if isinstance(d, dict) else None
            if d is None:
                return None
        return d

    if _get(dolar, "oficial", "ask"):
        opciones.append((dolar["oficial"]["ask"], "Oficial", "banco, con tope y requisitos"))
    if _get(dolar, "blue", "ask"):
        opciones.append((dolar["blue"]["ask"], "Blue", "efectivo informal"))
    if _get(dolar, "mep", "al30", "24hs", "price"):
        opciones.append((dolar["mep"]["al30"]["24hs"]["price"], "MEP", "broker, dólares en tu banco"))
    if _get(dolar, "ccl", "al30", "24hs", "price"):
        opciones.append((dolar["ccl"]["al30"]["24hs"]["price"], "CCL", "broker, cuenta en el exterior"))
    if _get(dolar, "tarjeta", "price"):
        opciones.append((dolar["tarjeta"]["price"], "Tarjeta", "consumos afuera, con impuestos"))

    mejores_stable = []
    for coin, cot in stables.items():
        validas = {ex: q for ex, q in a.filtrar_cotizaciones(cot, max_antiguedad, ahora, excluir).items() if q["totalAsk"]}
        if validas:
            ex, q = min(validas.items(), key=lambda kv: kv[1]["totalAsk"])
            mejores_stable.append((q["totalAsk"], coin.upper(), ex))
    if mejores_stable:
        p, coin, ex = min(mejores_stable)
        opciones.append((p, "Cripto", f"{coin} en {ex}, inmediato"))

    if not opciones:
        return "No pude obtener cotizaciones del dólar ahora."
    opciones.sort()
    ancho = max(len(et) for _, et, _ in opciones)
    filas = []
    for i, (p, et, _) in enumerate(opciones):
        marca = "⭐" if i == 0 else "  "
        filas.append(f"{marca} {et:<{ancho}}  $ {p:>6,.0f}")
    out = [
        "\U0001f4b5 <b>Dólar hoy</b> — de más barato a más caro",
        SEP,
        "<pre>" + "\n".join(filas) + "</pre>",
        "<i>" + " · ".join(f"{et}: {nota}" for _, et, nota in opciones) + "</i>",
    ]
    if mejores_stable:
        ancho_ex = max(len(ex) for _, _, ex in mejores_stable)
        out += [
            "",
            "\U0001fa99 <b>Stablecoin más barata por exchange</b>",
            "<pre>" + "\n".join(
                f"{coin:<4} {a.marcar(ex):<{ancho_ex + 2}}  $ {p:>9,.2f}" for p, coin, ex in sorted(mejores_stable)
            ) + "</pre>",
        ]
    return "\n".join(out)


def resp_arbitraje(resultados: list[tuple[str, a.Oportunidad | None]], umbral: float, n: int = 10) -> str:
    con_datos = sorted((r for r in resultados if r[1] is not None), key=lambda r: -r[1].spread_pct)
    sin_datos = [par for par, o in resultados if o is None]
    out = [f"\U0001f4ca <b>Spreads ahora</b> — alerta si supera <b>{umbral}%</b>", SEP]
    resto = con_datos[n:]
    con_datos = con_datos[:n]
    for par, o in con_datos:
        out.append(f"{_semaforo(o.spread_pct, umbral)} <b>{par.upper()}</b>  <b>{o.spread_pct:+.2f}%</b>")
        out.append(f"<pre>  comprar {a.marcar(o.comprar_en):<15} {a.precio(o.precio_compra):>14}\n"
                   f"  vender  {a.marcar(o.vender_en):<15} {a.precio(o.precio_venta):>14}</pre>")
    if resto:
        out.append("<i>" + ", ".join(f"{p.upper()} {o.spread_pct:+.2f}%" for p, o in resto) + "</i>")
    if sin_datos:
        out.append("⚪ sin datos: " + ", ".join(p.upper() for p in sin_datos))
    out.append("<i>\U0001f7e2 supera el umbral · \U0001f7e1 positivo · \U0001f534 negativo</i>")
    if any(a.es_p2p(o.comprar_en) or a.es_p2p(o.vender_en) for _, o in con_datos):
        out.append(a.AVISO_P2P)
    return "\n".join(out)


def resp_umbral(cfg: dict, arg: str | None, persistente: bool = True) -> str:
    if not arg:
        return (f"⚙️ Umbral actual: <b>{cfg['umbral_pct']}%</b>\n"
                f"Para cambiarlo: <code>/umbral 1.5</code>")
    if not persistente:
        return ("⚙️ Umbral actual: <b>{u}%</b>\n"
                "Desde acá no puedo guardarlo: cambiá <code>umbral_pct</code> en "
                "<code>CONFIG_DEFAULT</code> de arbitraje.py y hacé push.").format(u=cfg["umbral_pct"])
    try:
        nuevo = float(arg.replace(",", "."))
    except ValueError:
        return f"No entendí '{arg}'. Ejemplo: <code>/umbral 1.5</code>"
    if not 0 <= nuevo <= 50:
        return "Poné un valor entre 0 y 50."
    cfg["umbral_pct"] = nuevo
    a.guardar_config(cfg)
    return f"✅ Listo: aviso cuando el spread supere <b>{nuevo}%</b>."


# ---------- descarga + despacho ----------

obtener_dolar = a.obtener_dolar
_descargar_varios = a.descargar_varios


def resp_rulos(cfg: dict) -> str:
    import rulos
    cotizaciones = _descargar_varios(cfg["pares"], cfg["volumen"], cfg)
    try:
        dolar = obtener_dolar()
    except Exception:  # noqa: BLE001
        dolar = None
    aristas = rulos.construir_aristas(cotizaciones, dolar, cfg)
    return rulos.formatear_listado(rulos.buscar_rulos(aristas, cfg.get("max_patas", 4)), cfg["umbral_rulo_pct"])


def _monto(arg: str | None) -> float | None:
    """'160000', '160.000', '160k', '$160000' -> 160000.0"""
    if not arg:
        return None
    t = arg.lower().replace("$", "").replace(".", "").replace(",", "").strip()
    try:
        return float(t[:-1]) * 1000 if t.endswith("k") else float(t)
    except ValueError:
        return None


def manejar(texto: str, cfg: dict, persistente: bool = True) -> str:
    """persistente=False en el webhook (Vercel), donde no se puede escribir config.json."""
    partes = texto.strip().split()
    cmd = partes[0].lstrip("/").split("@")[0].lower()
    arg = partes[1] if len(partes) > 1 else None
    fiat = "ars"
    excluir = set(cfg["excluir_exchanges"])
    try:
        if cmd in ("start", "ayuda", "help"):
            return resp_ayuda()
        monedas_cfg = {p.split("/")[0] for p in cfg["pares"]}
        if cmd in MONEDAS or cmd in monedas_cfg:
            pares = [f"{cmd}/ars"] + ([f"{cmd}/usd"] if f"{cmd}/usd" in cfg["pares"] or cmd in MONEDAS else [])
            descargas = _descargar_varios(pares, cfg["volumen"], cfg)
            return resp_moneda(cmd, descargas.get(f"{cmd}/ars") or {}, "ARS",
                               max_antiguedad=cfg["max_antiguedad_seg"], max_desvio_pct=cfg["max_desvio_pct"],
                               excluir=excluir, cot_usd=descargas.get(f"{cmd}/usd") if len(pares) > 1 else None,
                               max_desvio_usd_pct=cfg.get("max_desvio_usd_pct"),
                               excluir_usd=a.excluidos_para(f"{cmd}/usd", cfg))
        if cmd == "dolar":
            descargas = _descargar_varios([f"{c}/{fiat}" for c in ("usdt", "usdc", "dai")], cfg["volumen"], cfg)
            stables = {par.split("/")[0]: cot for par, cot in descargas.items() if cot}
            return resp_dolar(obtener_dolar(), stables, max_antiguedad=cfg["max_antiguedad_seg"],
                              excluir=excluir)
        if cmd == "arbitraje":
            ahora = time.time()
            res = []
            for par, cot in _descargar_varios(cfg["pares"], cfg["volumen"], cfg).items():
                if cot is None:
                    res.append((par, None))
                    continue
                ops = a.detectar_oportunidades(cot, -100, cfg["max_antiguedad_seg"], ahora, par,
                                               a.excluidos_para(par, cfg), a.desvio_para(par, cfg))
                res.append((par, ops[0] if ops else None))
            return resp_arbitraje(res, cfg["umbral_pct"])
        if cmd == "rulos":
            return resp_rulos(cfg)
        if cmd in ("p2p", "arbitrajep2p", "capital"):
            import p2p
            capital = _monto(arg)
            if cmd == "capital" and capital is None and not cfg.get("capital_ars"):
                return "Decime con cu\u00e1nto arranc\u00e1s, en pesos: <code>/capital 160000</code>"
            cfg_p2p = dict(cfg, capital_ars=capital) if capital else cfg
            analisis = p2p.analizar_todo(cfg_p2p, p2p.descargar_libros(cfg_p2p))
            if cmd == "capital":
                return p2p.plan_capital(capital or cfg["capital_ars"], analisis.get("ars"), cfg_p2p)
            return p2p.formatear_informe(analisis.get("ars"), analisis.get("usd"), None, cfg_p2p)
        if cmd == "umbral":
            return resp_umbral(cfg, arg, persistente)
    except Exception as e:  # noqa: BLE001
        return f"Error consultando CriptoYa: {e}"
    return "No conozco ese comando.\n\n" + resp_ayuda()
