"""Binance P2P: cotizacion directa filtrada por metodos de pago, libro de ofertas, y
analisis de arbitraje DENTRO de Binance P2P (comprar a una persona y vender a otra, sin
transferir nada a ningun lado).

CriptoYa publica para binancep2p el mejor precio entre TODAS las ofertas, y en los pares en
dolares la mejor suele pedir un banco de Panama o Wise. Consultando Binance directo con los
metodos de pago que uno realmente tiene (Mercado Pago, Uala, banco argentino) el precio es el
que de verdad se puede operar.

Endpoint publico (el mismo que usa la web de Binance), sin login.

Vocabulario:
  - lista "compra": anuncios de gente que VENDE USDT; vos les compras. Ordenada de mas barata a mas cara.
  - lista "venta":  anuncios de gente que COMPRA USDT; vos les vendes. Ordenada de la que mas paga a la que menos.
  - cruce (taker): la mejor venta paga mas que lo que cuesta la mejor compra -> comprar y vender ya.
  - anuncios (maker): publicar tu propio anuncio de compra y de venta y cobrar la diferencia.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass

URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"

# Activos que Binance P2P opera contra ARS y USD
ACTIVOS = {"usdt", "usdc", "btc", "eth", "bnb"}

METODOS_CORTOS = {
    "MercadoPagoNew": "MP", "UalaNew": "Ualá", "BankArgentina": "Banco", "SantanderArgentina": "Santander",
    "BancoBrubankNew": "Brubank", "NaranjaX": "NaranjaX", "Beloapp": "Belo", "personalpay": "PersonalPay",
    "BBVABank": "BBVA", "BankTransferArgentina": "Transf", "Lemoncash": "Lemon",
}


@dataclass
class Oferta:
    lado: str            # "compra" (vos compras) / "venta" (vos vendes)
    precio: float
    metodos: list[str]
    minimo: float        # en fiat
    maximo: float        # en fiat (dinamico: lo que el anunciante puede cubrir ahora)
    nombre: str
    ordenes_mes: int
    tasa: float          # fraccion de ordenes completadas en el mes

    @property
    def metodos_cortos(self) -> str:
        return " ".join(METODOS_CORTOS.get(m, m) for m in self.metodos)


# ---------- descarga ----------

def _buscar(asset: str, fiat: str, trade: str, metodos: list[str], monto: float | None,
            pais: str = "AR", rows: int = 10) -> list[dict]:
    body = {"asset": asset.upper(), "fiat": fiat.upper(), "merchantCheck": False, "page": 1,
            "payTypes": metodos, "publisherType": None, "rows": rows, "tradeType": trade,
            "countries": [pais]}
    if monto:
        body["transAmount"] = str(monto)
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0",
                                          "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8")).get("data") or []


def _parsear(datos: list[dict], lado: str) -> list[Oferta]:
    out = []
    for d in datos:
        try:
            adv, av = d["adv"], d.get("advertiser") or {}
            out.append(Oferta(lado, float(adv["price"]), [m["identifier"] for m in adv.get("tradeMethods") or []],
                              float(adv.get("minSingleTransAmount") or 0),
                              float(adv.get("dynamicMaxSingleTransAmount") or adv.get("maxSingleTransAmount") or 0),
                              str(av.get("nickName") or "?"), int(av.get("monthOrderCount") or 0),
                              float(av.get("monthFinishRate") or 0)))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def libro(asset: str, fiat: str, metodos: list[str], monto: float | None, rows: int = 10) -> dict:
    """{"compra": [Oferta...], "venta": [Oferta...]} ya ordenadas por Binance (mejor primero)."""
    return {"compra": _parsear(_buscar(asset, fiat, "BUY", metodos, monto, rows=rows), "compra"),
            "venta": _parsear(_buscar(asset, fiat, "SELL", metodos, monto, rows=rows), "venta")}


def mejor_precio(ofertas: list[dict]) -> float | None:
    precios = []
    for of in ofertas:
        try:
            precios.append(float(of["adv"]["price"]))
        except (KeyError, TypeError, ValueError):
            continue
    return precios[0] if precios else None  # Binance ya las devuelve ordenadas de mejor a peor


def cotizacion(asset: str, fiat: str, metodos: list[str], monto: float | None) -> dict | None:
    """Devuelve {"ask", "totalAsk", "bid", "totalBid", "time"} con el formato de CriptoYa, o None.
    ask = lo que pagas por comprar (ofertas de venta, tradeType BUY desde tu lado)."""
    if asset.lower() not in ACTIVOS:
        return None
    ask = mejor_precio(_buscar(asset, fiat, "BUY", metodos, monto))
    bid = mejor_precio(_buscar(asset, fiat, "SELL", metodos, monto))
    if not ask or not bid:
        return None
    return {"ask": ask, "totalAsk": ask, "bid": bid, "totalBid": bid, "time": int(time.time())}


def aplicar(cotizaciones: dict[str, dict | None], cfg: dict) -> dict[str, str]:
    """Reemplaza la entrada 'binancep2p' de cada par por la cotizacion directa filtrada.
    Si la consulta falla, deja la de CriptoYa. Devuelve {par: "directo" | "criptoya" | "sin"}."""
    if not cfg.get("p2p_binance_directo"):
        return {}
    metodos = cfg.get("p2p_metodos") or []
    montos = cfg.get("p2p_monto") or {}
    resultado = {}
    for par, cot in cotizaciones.items():
        if not cot or "binancep2p" not in cot:
            continue
        asset, fiat = par.lower().split("/")
        if asset not in ACTIVOS:
            continue
        try:
            directa = cotizacion(asset, fiat, metodos, montos.get(fiat))
        except Exception as e:  # noqa: BLE001
            print(f"[p2p] {par}: error consultando Binance, uso CriptoYa: {e}")
            resultado[par] = "criptoya"
            continue
        if directa is None:
            # sin ofertas para tus metodos/monto: mejor no mostrar un precio que no podes operar
            del cot["binancep2p"]
            resultado[par] = "sin"
        else:
            cot["binancep2p"] = directa
            resultado[par] = "directo"
    return resultado


# ---------- analisis (puro: recibe libros ya descargados) ----------

def _fmt(x: float, fiat: str) -> str:
    """Precio unitario: 3 decimales en dolares, 2 en pesos."""
    return f"US$ {x:,.3f}" if fiat == "usd" else f"$ {x:,.2f}"


def _monto(x: float, fiat: str) -> str:
    """Montos y ganancias: sin decimales."""
    return f"US$ {x:,.0f}" if fiat == "usd" else f"$ {x:,.0f}"


def _k(x: float, fiat: str) -> str:
    """Limites compactos: 201k, 1.2M, US$ 500."""
    if fiat == "usd":
        return f"{x:,.0f}"
    return f"{x / 1e6:.1f}M" if x >= 1e6 else f"{x / 1e3:.0f}k"


def analizar_fiat(lib: dict, fiat: str, monto: float, cfg: dict) -> dict | None:
    """Cruce taker y anuncios maker para un fiat. None si falta un lado."""
    compra, venta = lib.get("compra") or [], lib.get("venta") or []
    if not compra or not venta:
        return None
    ask, bid = compra[0], venta[0]
    cruce_pct = (bid.precio - ask.precio) / ask.precio * 100
    operable = min(ask.maximo, bid.maximo)
    minimo = max(ask.minimo, bid.minimo)
    tick = ask.precio * cfg.get("p2p_tick_pct", 0.05) / 100  # cuanto mejorar la punta para quedar primero
    anuncio_compra = bid.precio + tick   # tu anuncio de compra: pagas un poco mas que el mejor comprador
    anuncio_venta = ask.precio - tick    # tu anuncio de venta: cobras un poco menos que el mejor vendedor
    comision = cfg.get("p2p_comision_anuncio_pct", 0.0)  # Binance cobra al que publica el anuncio, por cada lado
    margen_bruto_pct = (anuncio_venta - anuncio_compra) / anuncio_compra * 100
    margen_pct = margen_bruto_pct - 2 * comision
    return {
        "margen_bruto_pct": margen_bruto_pct, "comision_pct": comision,
        "fiat": fiat, "ask": ask, "bid": bid, "compra": compra[:3], "venta": venta[:3],
        "cruce_pct": cruce_pct, "cruce_operable": operable, "cruce_minimo": minimo,
        "cruce_viable": cruce_pct > 0 and operable >= minimo,
        "anuncio_compra": anuncio_compra, "anuncio_venta": anuncio_venta, "margen_pct": margen_pct,
        "monto": monto,
    }


def dolar_implicito(an_ars: dict | None, an_usd: dict | None) -> dict:
    """Que dolar te queda cruzando los dos libros, en pesos por dolar."""
    out = {}
    if an_ars and an_usd:
        # compras USDT con pesos, lo vendes por dolares: pesos que pagaste por cada dolar obtenido
        out["comprar_usd"] = an_ars["ask"].precio / an_usd["bid"].precio
        # compras USDT con dolares, lo vendes por pesos: pesos que recibis por cada dolar puesto
        out["vender_usd"] = an_ars["bid"].precio / an_usd["ask"].precio
    return out


def _metodos(ofertas: list[Oferta], n: int = 3) -> str:
    vistos: list[str] = []
    for o in ofertas[:n]:
        for m in o.metodos:
            c = METODOS_CORTOS.get(m, m)
            if c not in vistos:
                vistos.append(c)
    return "/".join(vistos[:4]) or "-"


def _rep(o: Oferta) -> str:
    return f"{o.nombre} ({o.ordenes_mes} ops, {o.tasa * 100:.0f}%)"


def _fiat_nombre(fiat: str) -> str:
    return "pesos" if fiat == "ars" else "dólares"


def bloque_accion(an: dict) -> list[str]:
    """Lo primero que se lee: que hacer, donde y a que precio."""
    f = an["fiat"]
    if an["cruce_viable"]:
        monto = min(an["cruce_operable"], an["monto"])
        usdt = monto / an["ask"].precio
        gan = monto * an["cruce_pct"] / 100
        return [
            f"\U0001f4cc <b>QUÉ HACER: comprar y vender ya</b>  (cruce <b>{an['cruce_pct']:+.2f}%</b>)",
            f"1. Comprale a <b>{an['ask'].nombre}</b> {usdt:,.0f} USDT a <b>{_fmt(an['ask'].precio, f)}</b> "
            f"— pagás por {an['ask'].metodos_cortos}",
            f"2. Vendele a <b>{an['bid'].nombre}</b> esos USDT a <b>{_fmt(an['bid'].precio, f)}</b> "
            f"— te paga por {an['bid'].metodos_cortos}",
            f"3. Ganás <b>~{_monto(gan, f)}</b> sobre {_monto(monto, f)}. Liberá el USDT solo con la plata acreditada.",
        ]
    if an["margen_pct"] > 0:
        gan = an["monto"] * an["margen_pct"] / 100
        com = f" (ya descontada la comisión de anuncio de {an['comision_pct']}%)" if an.get("comision_pct") else ""
        return [
            "\U0001f4cc <b>QUÉ HACER: publicar anuncios</b>  (no hay cruce)",
            f"• Anuncio de <b>COMPRA</b> a <b>{_fmt(an['anuncio_compra'], f)}</b> → quedás primero entre los compradores",
            f"• Anuncio de <b>VENTA</b> a <b>{_fmt(an['anuncio_venta'], f)}</b> → quedás primero entre los vendedores",
            f"• Margen por vuelta: <b>{an['margen_pct']:+.2f}%</b> → ~{_monto(gan, f)} cada {_monto(an['monto'], f)}{com}",
            f"• Necesitás: {_fiat_nombre(f)} en {_metodos(an['compra'] + an['venta'])} para comprar, y USDT en Binance para vender",
        ]
    return [f"\U0001f4cc <b>QUÉ HACER: nada por ahora</b>  (sin cruce y sin margen para anuncios: {an['margen_pct']:+.2f}%)"]


def bloque_mercado(an: dict) -> list[str]:
    f = an["fiat"]
    a_, b_ = an["ask"], an["bid"]
    filas = [
        f"vende  {_fmt(a_.precio, f):>12}  {a_.metodos_cortos[:14]:<14} {_k(a_.minimo, f)}–{_k(a_.maximo, f)}",
        f"compra {_fmt(b_.precio, f):>12}  {b_.metodos_cortos[:14]:<14} {_k(b_.minimo, f)}–{_k(b_.maximo, f)}",
    ]
    return [
        "\U0001f4ca <b>Mercado ahora</b> (mejor de cada lado, con tus métodos)",
        "<pre>" + "\n".join(filas) + "</pre>",
        f"<i>vende: {_rep(a_)} · compra: {_rep(b_)} · spread entre puntas {-an['cruce_pct']:+.2f}%</i>",
    ]


REGLAS = ("<i>Reglas: liberá el USDT solo con la plata acreditada · los precios P2P cambian rápido, "
          "revisá antes de publicar · elegí contrapartes con muchas ops y 100%.</i>")

TITULO_FIAT = {"ars": "\U0001f1e6\U0001f1f7 PESOS", "usd": "\U0001f1fa\U0001f1f8 DÓLARES"}


def formatear_informe(an_ars: dict | None, an_usd: dict | None, dolar: dict | None, cfg: dict) -> str:
    from arbitraje import SEP
    montos = cfg.get("p2p_monto") or {}
    out = [f"\U0001f465 <b>Binance P2P — USDT</b>  <i>tus métodos · "
           f"{_monto(montos.get('ars', 0), 'ars')} / {_monto(montos.get('usd', 0), 'usd')}</i>"]
    for an in (an_ars, an_usd):
        if not an:
            continue
        out += [SEP, f"<b>{TITULO_FIAT[an['fiat']]}</b>"]
        out += bloque_accion(an)
        out += bloque_mercado(an)
    if not an_ars and not an_usd:
        out.append("No pude leer las ofertas de Binance P2P ahora.")
    out += [SEP, REGLAS]
    return "\n".join(out)


# ---------- alertas con apertura y cierre ----------

def detectar(an_por_fiat: dict[str, dict | None], cfg: dict) -> dict[str, dict]:
    """Oportunidades P2P que superan los umbrales ahora: {clave: {"pct", "tipo", "fiat"}}."""
    actuales = {}
    for fiat, an in an_por_fiat.items():
        if not an:
            continue
        if an["cruce_viable"] and an["cruce_pct"] >= cfg.get("umbral_p2p_cruce_pct", 0.3):
            actuales[f"cruce|{fiat}"] = {"pct": an["cruce_pct"], "tipo": "cruce", "fiat": fiat}
        if an["margen_pct"] >= cfg.get("umbral_p2p_anuncio_pct", 1.0):
            actuales[f"anuncio|{fiat}"] = {"pct": an["margen_pct"], "tipo": "anuncio", "fiat": fiat}
    return actuales


def actualizar(abiertas: dict, actuales: dict, ahora: float) -> tuple[list[str], list[dict], dict]:
    nuevo, nuevas, cerradas = {}, [], []
    for clave, info in actuales.items():
        previo = abiertas.get(clave)
        if previo is None:
            nuevas.append(clave)
            nuevo[clave] = dict(info, max=info["pct"], desde=ahora)
        else:
            nuevo[clave] = dict(previo, max=max(previo["max"], info["pct"]))
    for clave, previo in abiertas.items():
        if clave not in actuales:
            cerradas.append(dict(previo, duracion_min=(ahora - previo.get("desde", ahora)) / 60))
    return nuevas, cerradas, nuevo


def formatear_alerta(clave: str, an: dict) -> str:
    from arbitraje import SEP
    nombre = _fiat_nombre(an["fiat"])
    if clave.startswith("cruce"):
        titulo = f"\U0001f6a8 <b>CRUCE P2P en {nombre}</b>   ▲ <b>{an['cruce_pct']:+.2f}%</b>"
    else:
        titulo = f"\U0001f4e3 <b>MARGEN PARA ANUNCIOS P2P en {nombre}</b>   ▲ <b>{an['margen_pct']:+.2f}%</b>"
    return "\n".join([titulo, SEP] + bloque_accion(an) + bloque_mercado(an) + [REGLAS])


def formatear_cierres(cerradas: list[dict]) -> str:
    from arbitraje import SEP
    out = ["✅ <b>SE CERRÓ EN P2P</b>", SEP]
    for c in cerradas:
        que = "cruce" if c["tipo"] == "cruce" else "margen para anuncios"
        out.append(f"• {que} en {'pesos' if c['fiat'] == 'ars' else 'dólares'} "
                   f"(llegó a <b>{c['max']:+.2f}%</b>, duró {c['duracion_min']:.0f} min)")
    return "\n".join(out)


def descargar_libros(cfg: dict) -> dict[str, dict | None]:
    """Libros de USDT contra cada fiat configurado, en paralelo. None donde fallo."""
    from concurrent.futures import ThreadPoolExecutor
    metodos, montos = cfg.get("p2p_metodos") or [], cfg.get("p2p_monto") or {}
    fiats = cfg.get("p2p_fiats") or ["ars", "usd"]

    def uno(fiat):
        try:
            return fiat, libro("usdt", fiat, metodos, montos.get(fiat))
        except Exception as e:  # noqa: BLE001
            print(f"[p2p] libro usdt/{fiat}: {e}")
            return fiat, None
    with ThreadPoolExecutor(max_workers=len(fiats)) as ex:
        return dict(ex.map(uno, fiats))


def analizar_todo(cfg: dict, libros: dict[str, dict | None]) -> dict[str, dict | None]:
    montos = cfg.get("p2p_monto") or {}
    return {fiat: (analizar_fiat(lib, fiat, montos.get(fiat, 0), cfg) if lib else None) for fiat, lib in libros.items()}


def procesar(cfg: dict, abiertas: dict, ahora: float | None = None) -> tuple[list[str], list[dict], dict]:
    """Descarga, analiza, compara con el estado anterior y manda alertas. No toca el disco."""
    import arbitraje as a
    ahora = ahora or time.time()
    analisis = analizar_todo(cfg, descargar_libros(cfg))
    for fiat, an in analisis.items():
        if an:
            print(f"[p2p] usdt/{fiat}: cruce {an['cruce_pct']:+.2f}%  anuncios {an['margen_pct']:+.2f}%")
    nuevas, cerradas, estado = actualizar(abiertas, detectar(analisis, cfg), ahora)
    tok, chat = cfg["telegram_token"], cfg["telegram_chat_id"]
    if cerradas:
        msg = formatear_cierres(cerradas)
        print("\n" + a.texto_plano(msg) + "\n")
        a.enviar_telegram(tok, chat, msg)
    for clave in nuevas:
        msg = formatear_alerta(clave, analisis[estado[clave]["fiat"]])
        print("\n" + a.texto_plano(msg) + "\n")
        a.enviar_telegram(tok, chat, msg)
    return nuevas, cerradas, estado
