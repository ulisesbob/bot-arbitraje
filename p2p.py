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
    "MercadoPagoNew": "MP", "UalaNew": "Ualá", "UalaNewest": "Ualá", "BankArgentina": "Banco", "SantanderArgentina": "Santander",
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
    ordenes_mes: int     # 0 = la plataforma no lo publica
    tasa: float          # fraccion de ordenes completadas en el mes
    plataforma: str = "binancep2p"

    @property
    def metodos_cortos(self) -> str:
        return " ".join(METODOS_CORTOS.get(m, m) for m in self.metodos)


# ---------- descarga ----------

def _buscar(asset: str, fiat: str, trade: str, metodos: list[str], monto: float | None,
            pais: str | None = None, rows: int = 10) -> list[dict]:
    # Sin filtro de pais: con countries=["AR"] Binance esconde justamente las mejores ofertas
    # (verificado: el mejor vendedor pasaba de 1652.80 a 1655.00). CriptoYa tampoco lo usa.
    # La relevancia la dan los metodos de pago argentinos (payTypes) y el monto (transAmount).
    body = {"asset": asset.upper(), "fiat": fiat.upper(), "merchantCheck": False, "page": 1,
            "payTypes": metodos, "publisherType": None, "rows": rows, "tradeType": trade}
    if pais:
        body["countries"] = [pais]
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
    montos = montos_p2p(cfg)
    resultado = {}
    for par, cot in cotizaciones.items():
        if not cot:
            continue
        asset, fiat = par.lower().split("/")
        for plat in plataformas_para(fiat, cfg):
            if plat not in cot:
                continue
            if plat == "binancep2p" and asset not in ACTIVOS:
                continue
            if plat != "binancep2p" and asset != "usdt":
                continue  # en las otras plataformas solo consulto USDT
            try:
                if plat == "binancep2p":
                    directa = cotizacion(asset, fiat, metodos, montos.get(fiat))
                else:
                    lib = libro_plataforma(plat, asset, fiat, metodos, montos.get(fiat), rows=3)
                    directa = None
                    if lib.get("compra") and lib.get("venta"):
                        ask, bid = lib["compra"][0].precio, lib["venta"][0].precio
                        directa = {"ask": ask, "totalAsk": ask, "bid": bid, "totalBid": bid, "time": int(time.time())}
            except Exception as e:  # noqa: BLE001
                print(f"[p2p] {par} {plat}: error, uso CriptoYa: {e}")
                resultado[f"{par}:{plat}"] = "criptoya"
                continue
            if directa is None:
                del cot[plat]  # sin ofertas para tus metodos/monto: no mostrar un precio que no podes operar
                resultado[f"{par}:{plat}"] = "sin"
            else:
                cot[plat] = directa
                resultado[f"{par}:{plat}"] = "directo"
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
    ops = f"{o.ordenes_mes} ops" if o.ordenes_mes else "ops ?"
    return f"{o.nombre} ({ops}, {o.tasa * 100:.0f}%)"


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


def formatear_informe(an_ars: dict | None, an_usd: dict | None, dolar: dict | None, cfg: dict,
                      cruces: dict[str, dict | None] | None = None) -> str:
    from arbitraje import SEP
    montos = montos_p2p(cfg)
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
    for fiat, cp in (cruces or {}).items():
        if cp:
            out += [SEP, f"<b>{TITULO_FIAT.get(fiat, fiat)}</b> \u00b7 entre plataformas"] + bloque_cruce_plataformas(cp, cfg)
    out += [SEP, REGLAS]
    return "\n".join(out)


def capital_en_pesos(cfg: dict, precio_usdt: float | None = None) -> float:
    """Capital total en pesos: capital_usdt al precio dado (o dolar_aprox), o capital_ars."""
    if cfg.get("capital_usdt"):
        return cfg["capital_usdt"] * (precio_usdt or cfg.get("dolar_aprox", 1650))
    return cfg.get("capital_ars") or 0


def montos_p2p(cfg: dict, capital: float | None = None) -> dict[str, float]:
    """Monto por operacion para cada fiat. Con capital (o capital_ars en config) es la mitad del
    capital: una mitad opera en pesos, la otra en USDT. Si no hay capital, usa p2p_monto."""
    cap = capital if capital is not None else capital_en_pesos(cfg)
    if cap:
        lado = cap / 2
        return {"ars": lado, "usd": round(lado / cfg.get("dolar_aprox", 1650))}
    return dict(cfg.get("p2p_monto") or {})


def confiable(ofertas: list[Oferta], cfg: dict) -> Oferta | None:
    """Primera oferta (ya vienen ordenadas por precio) cuya contraparte tiene suficiente historial.
    Para la primera operacion importa mas que salga limpia que arañar unos pesos."""
    min_ops, min_tasa = cfg.get("p2p_min_ops", 50), cfg.get("p2p_min_tasa", 0.95)
    for o in ofertas:
        if o.ordenes_mes >= min_ops and o.tasa >= min_tasa:
            return o
    return ofertas[0] if ofertas else None


def plan_capital(capital: float, an: dict | None, cfg: dict, usdt_total: float | None = None) -> str:
    """Como arrancar: reparto, primera operacion y los dos anuncios.
    capital: pesos totales. usdt_total: si tu capital esta en USDT (entonces `capital` es su valor en pesos)."""
    from arbitraje import SEP
    titulo = f"{usdt_total:,.0f} USDT (~$ {capital:,.0f})" if usdt_total else f"$ {capital:,.0f}"
    out = [f"\U0001f4bc <b>Plan para arrancar con {titulo}</b>", SEP]
    if not an:
        out.append("No pude leer las ofertas de Binance P2P ahora; probá de nuevo en un minuto.")
        return "\n".join(out)
    ask = confiable(an["compra"], cfg) or an["ask"]
    bid = confiable(an["venta"], cfg) or an["bid"]
    if usdt_total:
        # Ya tenes el lado USDT: vendes la mitad por pesos para armar el lado Mercado Pago
        usdt = usdt_total / 2
        lado = usdt * bid.precio
        out += [
            f"<b>1. Repart\u00ed el capital</b>",
            f"\u2022 Vend\u00e9 <b>{usdt:,.0f} USDT</b> por pesos en Binance P2P ahora: <b>{bid.nombre}</b> te paga "
            f"$ {bid.precio:,.2f} por {bid.metodos_cortos} ({bid.ordenes_mes} ops, {bid.tasa * 100:.0f}%) "
            f"\u2192 te entran <b>$ {lado:,.0f}</b> a Mercado Pago.",
            f"\u2022 Los otros <b>{usdt:,.0f} USDT</b> quedan en Binance para el anuncio de venta.",
        ]
        if bid.minimo > lado or bid.maximo < lado:
            out.append(f"  \u26a0\ufe0f Ese comprador opera entre $ {bid.minimo:,.0f} y $ {bid.maximo:,.0f}: "
                       f"part\u00ed la venta en varias operaciones o eleg\u00ed otro de la lista de /p2p.")
    else:
        lado = capital / 2
        usdt = lado / ask.precio
        out += [
            f"<b>1. Repart\u00ed el capital</b>",
            f"\u2022 $ {lado:,.0f} quedan en Mercado Pago (o el banco que uses) para pagar compras.",
            f"\u2022 $ {lado:,.0f} \u2192 compr\u00e1 <b>{usdt:,.0f} USDT</b> en Binance P2P ahora: "
            f"<b>{ask.nombre}</b> a $ {ask.precio:,.2f} por {ask.metodos_cortos} ({ask.ordenes_mes} ops, {ask.tasa * 100:.0f}%).",
        ]
        if ask.minimo > lado:
            out.append(f"  \u26a0\ufe0f Ese vendedor pide m\u00ednimo $ {ask.minimo:,.0f}: eleg\u00ed otro de la lista de /p2p con m\u00ednimo menor.")
    elegido, mejor = (bid, an["bid"]) if usdt_total else (ask, an["ask"])
    if elegido is not mejor:
        out.append(f"  \u2139\ufe0f Hay mejor precio ({mejor.nombre} a $ {mejor.precio:,.2f}) pero con poco historial "
                   f"({mejor.ordenes_mes} ops, {mejor.tasa * 100:.0f}%); para la primera operaci\u00f3n conviene el de arriba.")
    minimo = round(lado * 0.25, -3)  # limite minimo de TUS anuncios: un cuarto del lado
    out += [
        "",
        f"<b>2. Public\u00e1 el anuncio de COMPRA</b>",
        f"\u2022 Precio fijo <b>$ {an['anuncio_compra']:,.2f}</b> \u00b7 cantidad {usdt:,.0f} USDT \u00b7 l\u00edmites $ {minimo:,.0f} a $ {lado:,.0f}",
        f"\u2022 Pago: Mercado Pago / los m\u00e9todos que tengas \u00b7 plazo 15 min",
        "",
        f"<b>3. Public\u00e1 el anuncio de VENTA</b>",
        f"\u2022 Precio fijo <b>$ {an['anuncio_venta']:,.2f}</b> \u00b7 cantidad {usdt:,.0f} USDT \u00b7 mismos l\u00edmites",
        "",
        f"<b>4. Qu\u00e9 esperar</b>",
        f"\u2022 Margen por vuelta hoy: <b>{an['margen_pct']:+.2f}%</b> \u2192 ~$ {lado * an['margen_pct'] / 100:,.0f} por cada vuelta completa.",
        "\u2022 Una vuelta = alguien te vende USDT por tu anuncio de compra y despu\u00e9s alguien te compra por el de venta.",
        "\u2022 Si una vuelta deja todo el capital de un lado, paus\u00e1 el anuncio que qued\u00f3 sin respaldo.",
        SEP,
        REGLAS,
    ]
    return "\n".join(out)


# ---------- otras plataformas P2P (Bybit, OKX, Bitget): buscadores publicos ----------

# Palabras con las que se reconoce cada metodo tuyo en los nombres que usan las otras plataformas
PALABRAS_METODO = {
    "MercadoPagoNew": ("mercadopago", "mercado pago"),
    "UalaNew": ("uala", "ualá"), "UalaNewest": ("uala", "ualá"),
    "BankArgentina": ("argentin", "transferencia", "cbu"),  # + los genericos de abajo, solo en pesos
    "SantanderArgentina": ("santander",),
    "BancoBrubankNew": ("brubank",),
    "NaranjaX": ("naranja",),
    "Beloapp": ("belo",), "personalpay": ("personal pay", "personalpay"),
    "LemonCash": ("lemon",), "BBVABank": ("bbva",),
}
# Nombres que parecen locales pero son de otro pais (Bybit tiene Santander Uruguay, Spain, Chile...)
OTROS_PAISES = ("uruguay", "spain", "chile", "poland", "méxico", "mexico", "perú", "peru", "brasil", "brazil",
                "colombia", "paraguay", "bolivia", "venezuela", "ecuador")
HDR = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
       "Accept": "application/json"}


GENERICOS_BANCO = ("bank transfer", "bank")  # en un libro en pesos, "bank" es un banco argentino; en dolares, cualquiera


def _coincide(nombre_metodo: str, metodos: list[str], fiat: str = "ars") -> bool:
    n = (nombre_metodo or "").lower()
    if any(p in n for p in OTROS_PAISES):
        return False
    if any(p in n for m in metodos for p in PALABRAS_METODO.get(m, (m.lower(),))):
        return True
    return fiat == "ars" and "BankArgentina" in metodos and any(p in n for p in GENERICOS_BANCO)


def _post(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=HDR)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _dentro(o: Oferta, monto: float | None) -> bool:
    return not monto or (o.minimo <= monto and (o.maximo <= 0 or monto <= o.maximo))


def _armar(ofertas: list[Oferta], metodos: list[str], monto: float | None, rows: int, fiat: str = "ars") -> list[Oferta]:
    """Filtra por tus metodos (si hay) y por monto; conserva el orden (mejor primero)."""
    out = [o for o in ofertas if _dentro(o, monto) and (not metodos or any(_coincide(m, metodos, fiat) for m in o.metodos))]
    return out[:rows]


_BYBIT_METODOS: dict[str, str] = {}


def _bybit_nombres() -> dict[str, str]:
    global _BYBIT_METODOS
    if not _BYBIT_METODOS:
        d = _post("https://api2.bybit.com/fiat/otc/configuration/queryAllPaymentList", {})
        lst = (d.get("result") or {}).get("paymentConfigVo") or []
        _BYBIT_METODOS = {str(x.get("paymentType")): str(x.get("paymentName")) for x in lst}
    return _BYBIT_METODOS


def libro_bybit(asset: str, fiat: str, metodos: list[str], monto: float | None, rows: int = 10) -> dict:
    nombres = _bybit_nombres()
    out = {}
    for side, lado in (("1", "compra"), ("0", "venta")):  # 1: anuncios de venta (vos compras); 0: de compra (vos vendes)
        d = _post("https://api2.bybit.com/fiat/otc/item/online",
                  {"userId": "", "tokenId": asset.upper(), "currencyId": fiat.upper(), "payment": [], "side": side,
                   "size": str(rows * 4), "page": "1", "amount": ""})
        ofertas = []
        for it in (d.get("result") or {}).get("items") or []:
            try:
                ofertas.append(Oferta(lado, float(it["price"]), [nombres.get(str(p), str(p)) for p in it.get("payments") or []],
                                      float(it.get("minAmount") or 0), float(it.get("maxAmount") or 0),
                                      str(it.get("nickName") or "?"), int(it.get("recentOrderNum") or 0),
                                      float(it.get("recentExecuteRate") or 0) / 100, "bybitp2p"))
            except (KeyError, TypeError, ValueError):
                continue
        out[lado] = _armar(ofertas, metodos, monto, rows, fiat.lower())
    return out


def libro_okx(asset: str, fiat: str, metodos: list[str], monto: float | None, rows: int = 10) -> dict:
    out = {}
    for side, lado in (("sell", "compra"), ("buy", "venta")):  # sell: anuncios de venta (vos compras)
        url = (f"https://www.okx.com/v3/c2c/tradingOrders/books?quoteCurrency={fiat.upper()}&baseCurrency={asset.upper()}"
               f"&side={side}&paymentMethod=all&userType=all&receivingAds=false&limit={rows * 4}&t={int(time.time() * 1000)}")
        d = _get(url)
        ofertas = []
        for it in (d.get("data") or {}).get(side) or []:
            try:
                ofertas.append(Oferta(lado, float(it["price"]), [str(m) for m in it.get("paymentMethods") or []],
                                      float(it.get("quoteMinAmountPerOrder") or 0), float(it.get("quoteMaxAmountPerOrder") or 0),
                                      str(it.get("nickName") or "?"), int(it.get("completedOrderQuantity") or 0),
                                      float(it.get("completedRate") or 0), "okexp2p"))
            except (KeyError, TypeError, ValueError):
                continue
        out[lado] = _armar(ofertas, metodos, monto, rows, fiat.lower())
    return out


def libro_bitget(asset: str, fiat: str, metodos: list[str], monto: float | None, rows: int = 10) -> dict:
    out = {}
    for side, lado in ((1, "compra"), (2, "venta")):  # 1: anuncios de venta (vos compras); 2: de compra (vos vendes)
        d = _post("https://www.bitget.com/v1/p2p/pub/adv/queryAdvList",
                  {"side": side, "pageNo": 1, "pageSize": rows * 4, "coinCode": asset.upper(), "fiatCode": fiat.upper(),
                   "languageType": 0})
        ofertas = []
        for it in (d.get("data") or {}).get("dataList") or []:
            try:
                ofertas.append(Oferta(lado, float(it["price"]), [str(m.get("paymethodName")) for m in it.get("paymethodInfo") or []],
                                      float(it.get("minAmount") or 0), float(it.get("maxAmount") or 0),
                                      str(it.get("nickName") or "?"), 0,  # Bitget no publica cantidad de ordenes
                                      float(it.get("thirtyCompletionRate") or 0), "bitgetp2p"))
            except (KeyError, TypeError, ValueError):
                continue
        out[lado] = _armar(ofertas, metodos, monto, rows, fiat.lower())
    return out


def libro_binance(asset: str, fiat: str, metodos: list[str], monto: float | None, rows: int = 10) -> dict:
    return libro(asset, fiat, metodos, monto, rows)


PLATAFORMAS = {"binancep2p": libro_binance, "bybitp2p": libro_bybit, "okexp2p": libro_okx, "bitgetp2p": libro_bitget}
NOMBRE_PLAT = {"binancep2p": "Binance", "bybitp2p": "Bybit", "okexp2p": "OKX", "bitgetp2p": "Bitget"}


def plataformas_para(fiat: str, cfg: dict) -> list[str]:
    """Que plataformas consultar para un fiat. En dolares los libros de Bybit/OKX/Bitget son globales
    (bancos de Camboya, Emiratos...) y no sirven: por defecto solo Binance."""
    if fiat.lower() != "ars":
        return [p for p in (cfg.get("p2p_plataformas_usd") or ["binancep2p"]) if p in PLATAFORMAS]
    return [p for p in (cfg.get("p2p_plataformas") or ["binancep2p"]) if p in PLATAFORMAS]


def libro_plataforma(plat: str, asset: str, fiat: str, metodos: list[str], monto: float | None, rows: int = 10) -> dict:
    return PLATAFORMAS[plat](asset, fiat, metodos, monto, rows)


def descargar_libros_plataformas(cfg: dict) -> dict[str, dict[str, dict | None]]:
    """{fiat: {plataforma: libro | None}} para USDT, en paralelo."""
    from concurrent.futures import ThreadPoolExecutor
    metodos, montos = cfg.get("p2p_metodos") or [], montos_p2p(cfg)
    fiats = cfg.get("p2p_fiats") or ["ars", "usd"]
    tareas = [(f, p) for f in fiats for p in plataformas_para(f, cfg)]

    def una(fp):
        f, p = fp
        try:
            return fp, libro_plataforma(p, "usdt", f, metodos, montos.get(f))
        except Exception as e:  # noqa: BLE001
            print(f"[p2p] {p} usdt/{f}: {e}")
            return fp, None
    out: dict[str, dict] = {f: {} for f in fiats}
    with ThreadPoolExecutor(max_workers=min(6, len(tareas))) as ex:
        for (f, p), lib in ex.map(una, tareas):
            out[f][p] = lib
    return out


def cruce_plataformas(libros: dict[str, dict | None], fiat: str, cfg: dict) -> dict | None:
    """Mejor compra en una plataforma y mejor venta en otra. Neto = bruto - costo de mover el USDT."""
    compras = [(p, lib["compra"][0]) for p, lib in libros.items() if lib and lib.get("compra")]
    ventas = [(p, lib["venta"][0]) for p, lib in libros.items() if lib and lib.get("venta")]
    mejor = None
    for pc, oc in compras:
        for pv, ov in ventas:
            if pc == pv:
                continue
            pct = (ov.precio - oc.precio) / oc.precio * 100
            if mejor is None or pct > mejor["pct"]:
                mejor = {"compra_en": pc, "compra": oc, "venta_en": pv, "venta": ov, "pct": pct}
    if mejor is None:
        return None
    monto = montos_p2p(cfg).get(fiat, 0)
    costo_usd = cfg.get("p2p_transferencia_usd", 1.0)
    usdt = monto / mejor["compra"].precio if monto else 0
    costo_pct = (costo_usd / usdt * 100) if usdt else 0
    mejor.update({"fiat": fiat, "monto": monto, "costo_pct": costo_pct, "neto_pct": mejor["pct"] - costo_pct,
                  "operable": min(mejor["compra"].maximo or monto, mejor["venta"].maximo or monto, monto or 1e18)})
    return mejor


def bloque_cruce_plataformas(cp: dict | None, cfg: dict) -> list[str]:
    if not cp:
        return []
    f = cp["fiat"]
    oc, ov = cp["compra"], cp["venta"]
    sem = "\U0001f7e2" if cp["neto_pct"] >= cfg.get("umbral_p2p_plataformas_pct", 0.7) else ("\U0001f7e1" if cp["neto_pct"] > 0 else "\U0001f534")
    out = [f"\U0001f501 <b>Cruce entre plataformas</b>  {sem} <b>{cp['neto_pct']:+.2f}%</b> neto "
           f"(bruto {cp['pct']:+.2f}%, mover USDT ~{cp['costo_pct']:.2f}%)",
           f"• Comprás en <b>{NOMBRE_PLAT.get(cp['compra_en'], cp['compra_en'])}</b> a {_fmt(oc.precio, f)}: "
           f"{oc.nombre} ({oc.metodos_cortos[:24]}, {_k(oc.minimo, f)}–{_k(oc.maximo, f)})",
           f"• Vendés en <b>{NOMBRE_PLAT.get(cp['venta_en'], cp['venta_en'])}</b> a {_fmt(ov.precio, f)}: "
           f"{ov.nombre} ({ov.metodos_cortos[:24]}, {_k(ov.minimo, f)}–{_k(ov.maximo, f)})"]
    if cp["neto_pct"] > 0:
        out.append(f"• Con USDT ya en {NOMBRE_PLAT.get(cp['venta_en'], cp['venta_en'])} lo hacés al instante; "
                   f"si no, transferí por TRC20 o Polygon (5 a 10 min).")
    return out


def formatear_alerta_plataformas(cp: dict, cfg: dict) -> str:
    from arbitraje import SEP, AVISO_P2P
    nombre = _fiat_nombre(cp["fiat"])
    titulo = f"\U0001f6a8 <b>CRUCE ENTRE P2P en {nombre}</b>   ▲ <b>{cp['neto_pct']:+.2f}%</b> neto"
    return "\n".join([titulo, SEP] + bloque_cruce_plataformas(cp, cfg) + [AVISO_P2P])


# ---------- alertas con apertura y cierre ----------

def detectar(an_por_fiat: dict[str, dict | None], cfg: dict,
             cruces: dict[str, dict | None] | None = None) -> dict[str, dict]:
    """Oportunidades P2P que superan los umbrales ahora: {clave: {"pct", "tipo", "fiat"}}."""
    actuales = {}
    for fiat, cp in (cruces or {}).items():
        if cp and cp["neto_pct"] >= cfg.get("umbral_p2p_plataformas_pct", 0.7):
            actuales[f"plataformas|{fiat}"] = {"pct": cp["neto_pct"], "tipo": "plataformas", "fiat": fiat}
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
        que = {"cruce": "cruce", "plataformas": "cruce entre plataformas"}.get(c["tipo"], "margen para anuncios")
        out.append(f"• {que} en {'pesos' if c['fiat'] == 'ars' else 'dólares'} "
                   f"(llegó a <b>{c['max']:+.2f}%</b>, duró {c['duracion_min']:.0f} min)")
    return "\n".join(out)


def descargar_libros(cfg: dict) -> dict[str, dict | None]:
    """Libros de USDT contra cada fiat configurado, en paralelo. None donde fallo."""
    from concurrent.futures import ThreadPoolExecutor
    metodos, montos = cfg.get("p2p_metodos") or [], montos_p2p(cfg)
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
    montos = montos_p2p(cfg)
    return {fiat: (analizar_fiat(lib, fiat, montos.get(fiat, 0), cfg) if lib else None) for fiat, lib in libros.items()}


def procesar(cfg: dict, abiertas: dict, ahora: float | None = None) -> tuple[list[str], list[dict], dict]:
    """Descarga, analiza, compara con el estado anterior y manda alertas. No toca el disco."""
    import arbitraje as a
    ahora = ahora or time.time()
    libros = descargar_libros_plataformas(cfg)
    analisis = analizar_todo(cfg, {f: libs.get("binancep2p") for f, libs in libros.items()})
    cruces = {f: cruce_plataformas(libs, f, cfg) for f, libs in libros.items()}
    for fiat, an in analisis.items():
        if an:
            cp = cruces.get(fiat)
            extra = f"  plataformas {cp['neto_pct']:+.2f}% neto ({NOMBRE_PLAT.get(cp['compra_en'])}\u2192{NOMBRE_PLAT.get(cp['venta_en'])})" if cp else ""
            print(f"[p2p] usdt/{fiat}: cruce {an['cruce_pct']:+.2f}%  anuncios {an['margen_pct']:+.2f}%{extra}")
    nuevas, cerradas, estado = actualizar(abiertas, detectar(analisis, cfg, cruces), ahora)
    tok, chat = cfg["telegram_token"], cfg["telegram_chat_id"]
    if cerradas:
        msg = formatear_cierres(cerradas)
        print("\n" + a.texto_plano(msg) + "\n")
        a.enviar_telegram(tok, chat, msg)
    for clave in nuevas:
        fiat = estado[clave]["fiat"]
        msg = formatear_alerta_plataformas(cruces[fiat], cfg) if clave.startswith("plataformas") else formatear_alerta(clave, analisis[fiat])
        print("\n" + a.texto_plano(msg) + "\n")
        a.enviar_telegram(tok, chat, msg)
    return nuevas, cerradas, estado
