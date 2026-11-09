"""Rulos: ciclos de 3 o 4 patas que empiezan y terminan en pesos, combinando
stablecoins, dolares de exchange y dolar bancario (oficial / MEP).

Ejemplo: ARS -> USD (oficial en banco) -> USDT (en un exchange, pagando con dolares)
         -> ARS (vendiendo el USDT por pesos en otro exchange).

Modelo: un grafo donde los nodos son activos (ARS, USD, USDT, USDC, DAI) y cada
arista es "en el exchange X convertis A en B a tal tasa". Para cada secuencia de
activos se elige la mejor arista por pata y se calcula el rendimiento del ciclo.

Las funciones son puras (reciben cotizaciones ya descargadas) para poder testearlas.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from itertools import permutations
from pathlib import Path

import arbitraje as a

STABLES = ("usdt", "usdc", "dai")
INTERMEDIOS = ("USD", "USDT", "USDC", "DAI")
NODOS = ("ARS", "USD", "USDT", "USDC", "DAI")
BANCARIOS = ("banco", "broker")


@dataclass
class Arista:
    origen: str        # activo que entregas
    destino: str       # activo que recibis
    tasa: float        # unidades de destino por unidad de origen
    exchange: str
    precio: float      # precio mostrado al usuario
    moneda_precio: str  # en que esta expresado el precio ("$" pesos o "US$")
    accion: str        # texto: "Compras USDT con pesos", etc.

    @property
    def p2p(self) -> bool:
        return a.es_p2p(self.exchange)


@dataclass
class Rulo:
    patas: list[Arista]
    rendimiento_pct: float          # bruto
    neto_pct: float = 0.0           # bruto menos el costo de mover la plata entre plataformas
    movimientos: int = 0            # cuantas veces hay que transferir entre una pata y la siguiente

    @property
    def inicio(self) -> str:
        return self.patas[0].origen

    @property
    def clave(self) -> str:
        return " > ".join([self.patas[0].origen] + [p.destino for p in self.patas])

    @property
    def ruta(self) -> str:
        return " → ".join([self.patas[0].origen] + [p.destino for p in self.patas])


# ---------- grafo ----------

def construir_aristas(cotizaciones: dict[str, dict | None], dolar: dict | None, cfg: dict,
                      ahora: float | None = None) -> list[Arista]:
    """cotizaciones: {"usdt/ars": {...}, "usdt/usd": {...}, ...} tal como las da CriptoYa.
    dolar: json de /api/dolar (puede ser None)."""
    ahora = ahora or time.time()
    excluir = set(cfg["excluir_exchanges"])  # las exclusiones por fiat se agregan por par
    aristas: list[Arista] = []

    for par, cot in cotizaciones.items():
        if not cot:
            continue
        coin, fiat = par.lower().split("/")
        if coin not in STABLES or fiat not in ("ars", "usd"):
            continue
        COIN, FIAT = coin.upper(), fiat.upper()
        simbolo = "$" if fiat == "ars" else "US$"
        con = "pesos" if fiat == "ars" else "dólares"
        validas = a.filtrar_cotizaciones(cot, cfg["max_antiguedad_seg"], ahora, a.excluidos_para(par, cfg),
                                         a.desvio_para(par, cfg))
        for ex, q in validas.items():
            ask, bid = q["totalAsk"], q["totalBid"]
            if ask:
                aristas.append(Arista(FIAT, COIN, 1 / ask, ex, ask, simbolo,
                                      f"Comprás {COIN} con {con}"))
            if bid:
                aristas.append(Arista(COIN, FIAT, bid, ex, bid, simbolo,
                                      f"Vendés {COIN} por {con}"))

    if dolar:
        of = dolar.get("oficial") or {}
        if of.get("ask"):
            aristas.append(Arista("ARS", "USD", 1 / of["ask"], "banco", of["ask"], "$",
                                  "Comprás dólar oficial"))
        if of.get("bid"):
            aristas.append(Arista("USD", "ARS", of["bid"], "banco", of["bid"], "$",
                                  "Vendés dólares oficial"))
        mep = ((dolar.get("mep") or {}).get("al30") or {}).get("24hs") or {}
        if mep.get("price"):
            # El MEP de CriptoYa es la referencia del mercado (punto medio del AL30). El broker te lo
            # opera peor en las dos direcciones: mep_spread_pct es ese castigo, ajustalo con lo que
            # te muestre tu broker al comprar y al vender.
            s = cfg.get("mep_spread_pct", 0.0) / 100
            ref = mep["price"]
            compra, venta = ref * (1 + s), ref * (1 - s)
            nota = f" (ref. $ {ref:,.0f} ±{s * 100:.1f}%)" if s else ""
            aristas.append(Arista("ARS", "USD", 1 / compra, "broker", compra, "$",
                                  "Comprás dólar MEP" + nota))
            aristas.append(Arista("USD", "ARS", venta, "broker", venta, "$",
                                  "Vendés dólar MEP" + nota))
    return aristas


def mejores_por_tramo(aristas: list[Arista]) -> dict[tuple[str, str], Arista]:
    mejores: dict[tuple[str, str], Arista] = {}
    for ar in aristas:
        k = (ar.origen, ar.destino)
        if k not in mejores or ar.tasa > mejores[k].tasa:
            mejores[k] = ar
    return mejores


def movimientos(patas: list[Arista]) -> int:
    """Cada vez que la pata siguiente esta en otra plataforma hay que transferir (cripto o dolares)."""
    return sum(1 for i in range(1, len(patas)) if patas[i].exchange != patas[i - 1].exchange)


def buscar_rulos(aristas: list[Arista], max_patas: int = 4, min_patas: int = 3, cfg: dict | None = None,
                 inicio: str = "ARS") -> list[Rulo]:
    """Todas las secuencias inicio -> (intermedios distintos) -> inicio, con la mejor arista por
    pata, ordenadas por rendimiento NETO. inicio: ARS, USD o USDT (en que moneda empezas y terminas).
    Las de 2 patas son el arbitraje simple y se excluyen."""
    costo = (cfg or {}).get("costo_movimiento_pct", 0.15)
    mejores = mejores_por_tramo(aristas)
    intermedios = [n for n in NODOS if n != inicio]
    rulos = []
    for n in range(min_patas - 1, max_patas):  # cantidad de intermedios
        for medio in permutations(intermedios, n):
            secuencia = [inicio, *medio, inicio]
            patas = []
            for o, d in zip(secuencia, secuencia[1:]):
                ar = mejores.get((o, d))
                if ar is None:
                    break
                patas.append(ar)
            else:
                producto = 1.0
                for pt in patas:
                    producto *= pt.tasa
                bruto = (producto - 1) * 100
                mov = movimientos(patas)
                rulos.append(Rulo(patas, bruto, bruto - mov * costo, mov))
    rulos.sort(key=lambda r: -r.neto_pct)
    return rulos


def buscar_todos(aristas: list[Arista], cfg: dict) -> list[Rulo]:
    """Rulos desde cada moneda de inicio configurada (rulos_inicios), juntos y ordenados por neto.
    Un mismo ciclo rotado (ARS→USD→USDT→ARS y USDT→ARS→USD→USDT) es la misma oportunidad: se
    cuenta una vez, prefiriendo que empiece en la moneda en que tenes el capital."""
    preferido = "USDT" if cfg.get("capital_usdt") else "ARS"
    inicios = cfg.get("rulos_inicios", ["ARS"])
    orden = [preferido] + [i for i in inicios if i != preferido]
    vistos: dict[frozenset, Rulo] = {}
    for inicio in orden:
        if inicio not in inicios:
            continue
        for r in buscar_rulos(aristas, cfg.get("max_patas", 4), cfg=cfg, inicio=inicio):
            firma = frozenset((p.origen, p.destino, p.exchange) for p in r.patas)
            vistos.setdefault(firma, r)
    todos = list(vistos.values())
    todos.sort(key=lambda r: -r.neto_pct)
    return todos


# ---------- estado: aperturas y cierres ----------

def detectar_cambios(abiertos: dict, rulos: list[Rulo], umbral: float, ahora: float) -> tuple[list, list, dict]:
    """abiertos: {clave: {"max": pct, "desde": ts, "ruta": str}} de la corrida anterior. Compara el NETO.
    Devuelve (nuevos, cerrados, abiertos_actualizados)."""
    actuales = {r.clave: r for r in rulos if r.neto_pct >= umbral}
    nuevo_estado: dict = {}
    nuevos, cerrados = [], []
    for clave, r in actuales.items():
        previo = abiertos.get(clave)
        if previo is None:
            nuevos.append(r)
            nuevo_estado[clave] = {"max": r.neto_pct, "desde": ahora, "ruta": r.ruta}
        else:
            nuevo_estado[clave] = dict(previo, max=max(previo["max"], r.neto_pct))
    por_clave = {r.clave: r for r in rulos}
    for clave, previo in abiertos.items():
        if clave not in actuales:
            actual = por_clave.get(clave)
            cerrados.append({"ruta": previo.get("ruta", clave), "max": previo["max"],
                             "ahora": actual.neto_pct if actual else None,
                             "duracion_min": (ahora - previo.get("desde", ahora)) / 60})
    return nuevos, cerrados, nuevo_estado


def cargar_estado(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        return {}


def guardar_estado(path: Path, estado: dict) -> None:
    try:
        path.write_text(json.dumps(estado), encoding="utf-8")
    except OSError as e:
        print(f"[rulos] no pude guardar {path.name}: {e}")


# ---------- formato ----------

NUM = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]


def _precio(ar: Arista) -> str:
    return f"{ar.moneda_precio} {a.precio(ar.precio)}"


def _lugar(ar: Arista) -> str:
    return {"banco": "el banco", "broker": "el broker (MEP)"}.get(ar.exchange, a.marcar(ar.exchange))


def pasos_rulo(r: Rulo) -> list[str]:
    """Una linea por pata, con la transferencia entre medio cuando cambia de plataforma."""
    out = []
    for i, p in enumerate(r.patas):
        if i and p.exchange != r.patas[i - 1].exchange:
            activo = p.origen
            que = "los d\u00f3lares" if activo == "USD" else f"el {activo}"
            desde = "del banco" if r.patas[i - 1].exchange == "banco" else f"de {_lugar(r.patas[i - 1])}"
            hasta = "al banco" if p.exchange == "banco" else f"a {_lugar(p)}"
            out.append(f"   \u2194\ufe0f mand\u00e1s {que} {desde} {hasta}"
                       + (" (red barata: TRC20 o Polygon)" if activo != "USD" else ""))
        out.append(f"{i + 1}. {p.accion} en <b>{_lugar(p)}</b> a {_precio(p)}")
    return out


def notas_rulo(r: Rulo, cfg: dict | None = None) -> list[str]:
    costo = (cfg or {}).get("costo_movimiento_pct", 0.15)
    notas = []
    if r.movimientos:
        notas.append(f"{r.movimientos} transferencia{'s' if r.movimientos > 1 else ''} \u2248 {r.movimientos * costo:.2f}%")
    if any(p.exchange == "broker" for p in r.patas):
        notas.append("el MEP liquida al d\u00eda siguiente")
    if any(p.exchange == "banco" for p in r.patas):
        notas.append("la pata del banco tiene l\u00edmites propios")
    if any(p.p2p for p in r.patas):
        notas.append("\U0001f465 P2P: precio de una persona, verific\u00e1")
    return notas


def monto_inicio(r: Rulo, monto_pesos: float, cfg: dict | None = None) -> tuple[float, str]:
    """El monto de referencia expresado en la moneda en que empieza el rulo."""
    if r.inicio == "ARS":
        return monto_pesos, "$"
    dolar = (cfg or {}).get("dolar_aprox", 1650)
    return round(monto_pesos / dolar, -1) or 100, ("US$" if r.inicio == "USD" else r.inicio)


def _sem(neto: float, umbral: float) -> str:
    return "\U0001f7e2" if neto >= umbral else ("\U0001f7e1" if neto > 0 else "\U0001f534")


def formatear_rulo(r: Rulo, monto: float = 100_000, cfg: dict | None = None) -> str:
    umbral = (cfg or {}).get("umbral_rulo_pct", 2.0)
    out = [f"{_sem(r.neto_pct, umbral)} <b>{r.ruta}</b>   neto <b>{r.neto_pct:+.2f}%</b> <i>(bruto {r.rendimiento_pct:+.2f}%)</i>"]
    out += pasos_rulo(r)
    m, sim = monto_inicio(r, monto, cfg)
    out.append(f"\U0001f4b0 Por cada {sim} {m:,.0f}: <b>~{sim} {m * r.neto_pct / 100:,.0f}</b> netos")
    notas = notas_rulo(r, cfg)
    if notas:
        out.append("<i>" + " \u00b7 ".join(notas) + "</i>")
    return "\n".join(out)


def formatear_nuevos(rulos: list[Rulo], monto: float = 100_000, maximo: int = 3, cfg: dict | None = None) -> str:
    bloques = [formatear_rulo(r, monto, cfg) for r in rulos[:maximo]]
    titulo = "\U0001f6a8 <b>OPORTUNIDAD DE RULO</b>" if len(bloques) == 1 else f"\U0001f6a8 <b>{len(bloques)} OPORTUNIDADES DE RULO</b>"
    return titulo + "\n" + a.SEP + "\n" + ("\n" + a.SEP + "\n").join(bloques)


def formatear_cerrados(cerrados: list[dict]) -> str:
    out = ["\u2705 <b>SE CERR\u00d3 LA OPORTUNIDAD</b>", a.SEP]
    for c in cerrados:
        ahora = f", ahora {c['ahora']:+.2f}%" if c.get("ahora") is not None else ""
        dur = f", dur\u00f3 {c['duracion_min']:.0f} min" if c.get("duracion_min") else ""
        out.append(f"\u2022 {c['ruta']}  (lleg\u00f3 a <b>{c['max']:+.2f}%</b> neto{ahora}{dur})")
    return "\n".join(out)


def formatear_listado(rulos: list[Rulo], umbral: float, n: int = 3, monto: float = 100_000,
                      cfg: dict | None = None) -> str:
    """Para el comando /rulos: veredicto arriba, despues los mejores n con pasos."""
    if not rulos:
        return "No pude armar ning\u00fan rulo con las cotizaciones de ahora."
    mejor = rulos[0]
    out = [f"\U0001f501 <b>Rulos ahora</b> \u2014 alerta si el neto supera <b>{umbral}%</b>", a.SEP]
    if mejor.neto_pct >= umbral:
        out.append(f"\U0001f4cc <b>HAY RULO:</b> {mejor.ruta} deja <b>{mejor.neto_pct:+.2f}%</b> neto. Pasos abajo.")
    elif mejor.neto_pct > 0:
        out.append(f"\U0001f4cc <b>Hoy no:</b> el mejor deja {mejor.neto_pct:+.2f}% neto, por debajo del umbral. "
                   f"Esper\u00e1 la alerta.")
    else:
        out.append("\U0001f4cc <b>Hoy no:</b> ning\u00fan rulo queda positivo despu\u00e9s de costos.")
    for r in rulos[:n]:
        out += [a.SEP, formatear_rulo(r, monto, cfg)]
    out += [a.SEP, "<i>Neto = bruto menos transferencias entre plataformas. El MEP ya incluye el castigo del broker. "
                   "Los precios son de este momento.</i>"]
    return "\n".join(out)


# ---------- orquestacion ----------

def procesar(cfg: dict, cotizaciones: dict[str, dict | None], dolar: dict | None, abiertos: dict,
             ahora: float | None = None) -> tuple[list[Rulo], list[dict], dict]:
    """Calcula rulos, compara con `abiertos` (estado anterior), manda alertas.
    Devuelve (nuevos, cerrados, estado_nuevo). No toca el disco."""
    ahora = ahora or time.time()
    aristas = construir_aristas(cotizaciones, dolar, cfg, ahora)
    rulos = buscar_todos(aristas, cfg)
    if rulos:
        m = rulos[0]
        print(f"[rulos] mejor: {m.ruta} {m.neto_pct:+.2f}% neto (bruto {m.rendimiento_pct:+.2f}%)")
    nuevos, cerrados, estado = detectar_cambios(abiertos, rulos, cfg["umbral_rulo_pct"], ahora)
    tok, chat = cfg["telegram_token"], cfg["telegram_chat_id"]
    if cerrados:
        msg = formatear_cerrados(cerrados)
        print("\n" + a.texto_plano(msg) + "\n")
        a.enviar_telegram(tok, chat, msg)
    if nuevos:
        msg = formatear_nuevos(nuevos, cfg["volumen_rulo"], cfg=cfg)
        print("\n" + a.texto_plano(msg) + "\n")
        a.enviar_telegram(tok, chat, msg)
    return nuevos, cerrados, estado


def correr(cfg: dict, cotizaciones: dict[str, dict | None], dolar: dict | None, estado_path: Path,
           ahora: float | None = None) -> tuple[list[Rulo], list[dict]]:
    """Como procesar(), pero leyendo y guardando el estado en un archivo (bot local, Actions)."""
    nuevos, cerrados, estado = procesar(cfg, cotizaciones, dolar, cargar_estado(estado_path), ahora)
    guardar_estado(estado_path, estado)
    return nuevos, cerrados
