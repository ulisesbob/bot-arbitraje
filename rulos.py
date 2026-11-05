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
    rendimiento_pct: float

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
            aristas.append(Arista(FIAT, COIN, 1 / ask, ex, ask, simbolo,
                                  f"Comprás {COIN} con {con}"))
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
            aristas.append(Arista("ARS", "USD", 1 / mep["price"], "broker", mep["price"], "$",
                                  "Comprás dólar MEP"))
            aristas.append(Arista("USD", "ARS", mep["price"], "broker", mep["price"], "$",
                                  "Vendés dólar MEP"))
    return aristas


def mejores_por_tramo(aristas: list[Arista]) -> dict[tuple[str, str], Arista]:
    mejores: dict[tuple[str, str], Arista] = {}
    for ar in aristas:
        k = (ar.origen, ar.destino)
        if k not in mejores or ar.tasa > mejores[k].tasa:
            mejores[k] = ar
    return mejores


def buscar_rulos(aristas: list[Arista], max_patas: int = 4, min_patas: int = 3) -> list[Rulo]:
    """Todas las secuencias ARS -> (intermedios distintos) -> ARS, con la mejor arista por
    pata, ordenadas por rendimiento. Las de 2 patas son el arbitraje simple y se excluyen."""
    mejores = mejores_por_tramo(aristas)
    rulos = []
    for n in range(min_patas - 1, max_patas):  # cantidad de intermedios
        for medio in permutations(INTERMEDIOS, n):
            secuencia = ["ARS", *medio, "ARS"]
            patas = []
            for o, d in zip(secuencia, secuencia[1:]):
                ar = mejores.get((o, d))
                if ar is None:
                    break
                patas.append(ar)
            else:
                producto = 1.0
                for p in patas:
                    producto *= p.tasa
                rulos.append(Rulo(patas, (producto - 1) * 100))
    rulos.sort(key=lambda r: -r.rendimiento_pct)
    return rulos


# ---------- estado: aperturas y cierres ----------

def detectar_cambios(abiertos: dict, rulos: list[Rulo], umbral: float, ahora: float) -> tuple[list, list, dict]:
    """abiertos: {clave: {"max": pct, "desde": ts, "ruta": str}} de la corrida anterior.
    Devuelve (nuevos, cerrados, abiertos_actualizados)."""
    actuales = {r.clave: r for r in rulos if r.rendimiento_pct >= umbral}
    nuevo_estado: dict = {}
    nuevos, cerrados = [], []
    for clave, r in actuales.items():
        previo = abiertos.get(clave)
        if previo is None:
            nuevos.append(r)
            nuevo_estado[clave] = {"max": r.rendimiento_pct, "desde": ahora, "ruta": r.ruta}
        else:
            nuevo_estado[clave] = dict(previo, max=max(previo["max"], r.rendimiento_pct))
    por_clave = {r.clave: r for r in rulos}
    for clave, previo in abiertos.items():
        if clave not in actuales:
            actual = por_clave.get(clave)
            cerrados.append({"ruta": previo.get("ruta", clave), "max": previo["max"],
                             "ahora": actual.rendimiento_pct if actual else None,
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


def formatear_rulo(r: Rulo, monto: float = 100_000) -> str:
    out = [f"\U0001f501 <b>RULO {r.ruta}</b>   ▲ <b>{r.rendimiento_pct:+.2f}%</b>", a.SEP]
    hay_p2p = False
    cambia_exchange = False
    for i, p in enumerate(r.patas):
        marca = " \U0001f465" if p.p2p else ""
        hay_p2p |= p.p2p
        if i and p.exchange != r.patas[i - 1].exchange:
            cambia_exchange = True
        out.append(f"{NUM[i]} {p.accion} en <b>{p.exchange}</b>{marca} a {_precio(p)}")
    out.append(f"\U0001f4b0 Por cada $ {monto:,.0f}: <b>~$ {monto * r.rendimiento_pct / 100:,.0f}</b>")
    notas = []
    if hay_p2p:
        notas.append("\U0001f465 P2P: precio de una persona, confirmá monto y precio antes de operar")
    if cambia_exchange:
        notas.append("⚠️ Entre exchanges distintos hay que transferir: confirmá red en común y comisiones")
    if any(p.exchange in BANCARIOS for p in r.patas):
        notas.append("\U0001f3e6 La pata bancaria tiene límites y reglas propias")
    if notas:
        out.append("<i>" + "\n".join(notas) + "</i>")
    return "\n".join(out)


def formatear_nuevos(rulos: list[Rulo], monto: float = 100_000, maximo: int = 3) -> str:
    bloques = [formatear_rulo(r, monto) for r in rulos[:maximo]]
    titulo = "\U0001f6a8 <b>OPORTUNIDAD DE RULO</b>" if len(bloques) == 1 else f"\U0001f6a8 <b>{len(bloques)} OPORTUNIDADES DE RULO</b>"
    return titulo + "\n\n" + "\n\n".join(bloques)


def formatear_cerrados(cerrados: list[dict]) -> str:
    out = ["✅ <b>SE CERRÓ LA OPORTUNIDAD</b>", a.SEP]
    for c in cerrados:
        ahora = f", ahora {c['ahora']:+.2f}%" if c.get("ahora") is not None else ""
        dur = f", duró {c['duracion_min']:.0f} min" if c.get("duracion_min") else ""
        out.append(f"• {c['ruta']}  (llegó a <b>{c['max']:+.2f}%</b>{ahora}{dur})")
    return "\n".join(out)


def formatear_listado(rulos: list[Rulo], umbral: float, n: int = 5) -> str:
    """Para el comando /rulos: los mejores n, superen o no el umbral."""
    if not rulos:
        return "No pude armar ningún rulo con las cotizaciones de ahora."
    out = [f"\U0001f501 <b>Mejores rulos ahora</b> — alerta si supera <b>{umbral}%</b>", a.SEP]
    for r in rulos[:n]:
        sem = "\U0001f7e2" if r.rendimiento_pct >= umbral else ("\U0001f7e1" if r.rendimiento_pct > 0 else "\U0001f534")
        out.append(f"{sem} <b>{r.ruta}</b>  <b>{r.rendimiento_pct:+.2f}%</b>")
        out.append("<pre>" + "\n".join(
            f"  {p.accion[:7].lower()} {p.destino if p.accion.startswith('C') else p.origen:<4} "
            f"{(p.exchange[:18] + (' \U0001f465' if p.p2p else '')):<20} {_precio(p):>14}"
            for p in r.patas) + "</pre>")
    out.append("<i>\U0001f465 = P2P. Detalle de cada pata: esperá la alerta o mirá CriptoYa.</i>")
    return "\n".join(out)


# ---------- orquestacion ----------

def procesar(cfg: dict, cotizaciones: dict[str, dict | None], dolar: dict | None, abiertos: dict,
             ahora: float | None = None) -> tuple[list[Rulo], list[dict], dict]:
    """Calcula rulos, compara con `abiertos` (estado anterior), manda alertas.
    Devuelve (nuevos, cerrados, estado_nuevo). No toca el disco."""
    ahora = ahora or time.time()
    aristas = construir_aristas(cotizaciones, dolar, cfg, ahora)
    rulos = buscar_rulos(aristas, cfg.get("max_patas", 4))
    if rulos:
        m = rulos[0]
        print(f"[rulos] mejor: {m.ruta} {m.rendimiento_pct:+.2f}%")
    nuevos, cerrados, estado = detectar_cambios(abiertos, rulos, cfg["umbral_rulo_pct"], ahora)
    tok, chat = cfg["telegram_token"], cfg["telegram_chat_id"]
    if cerrados:
        msg = formatear_cerrados(cerrados)
        print("\n" + a.texto_plano(msg) + "\n")
        a.enviar_telegram(tok, chat, msg)
    if nuevos:
        msg = formatear_nuevos(nuevos, cfg["volumen_rulo"])
        print("\n" + a.texto_plano(msg) + "\n")
        a.enviar_telegram(tok, chat, msg)
    return nuevos, cerrados, estado


def correr(cfg: dict, cotizaciones: dict[str, dict | None], dolar: dict | None, estado_path: Path,
           ahora: float | None = None) -> tuple[list[Rulo], list[dict]]:
    """Como procesar(), pero leyendo y guardando el estado en un archivo (bot local, Actions)."""
    nuevos, cerrados, estado = procesar(cfg, cotizaciones, dolar, cargar_estado(estado_path), ahora)
    guardar_estado(estado_path, estado)
    return nuevos, cerrados
