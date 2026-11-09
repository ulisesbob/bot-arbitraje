"""Ranking unico de oportunidades: arbitraje simple, rulos (desde pesos, dolares o USDT),
cruce y anuncios en Binance P2P, y cruce entre plataformas P2P. Todo medido en NETO
(descontados los costos de mover la plata) y ordenado de mejor a peor, con los pasos del primero.

Comando: /mejor
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import arbitraje as a
import p2p
import rulos as rl

TIPO_NOMBRE = {
    "arbitraje": "Arbitraje entre exchanges",
    "rulo": "Rulo",
    "p2p_cruce": "Cruce en Binance P2P",
    "p2p_anuncios": "Anuncios en Binance P2P",
    "p2p_plataformas": "Cruce entre plataformas P2P",
}
SIMBOLO = {"ARS": "$", "USD": "US$", "USDT": "USDT", "USDC": "USDC", "DAI": "DAI"}


@dataclass
class Oportunidad:
    tipo: str
    titulo: str
    neto_pct: float
    bruto_pct: float
    moneda: str              # con que empezas: ARS / USD / USDT
    tiempo: str              # cuanto tarda cerrar el ciclo
    alerta: bool             # supera su propio umbral
    pasos: list[str] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)

    @property
    def sem(self) -> str:
        return "\U0001f7e2" if self.alerta else ("\U0001f7e1" if self.neto_pct > 0 else "\U0001f534")


def _fmt(x: float, moneda: str) -> str:
    s = SIMBOLO.get(moneda, moneda)
    if moneda == "ARS":
        return f"$ {x:,.2f}"
    if moneda == "USD":
        return f"US$ {x:,.4f}" if x < 10 else f"US$ {x:,.2f}"
    return f"{x:,.2f} {s}"


# ---------- recoleccion por tipo ----------

def de_arbitraje(cotizaciones: dict, cfg: dict, ahora: float) -> list[Oportunidad]:
    out = []
    costo = cfg.get("costo_movimiento_pct", 0.15)
    for par, cot in cotizaciones.items():
        if not cot:
            continue
        ops = a.detectar_oportunidades(cot, -100, cfg["max_antiguedad_seg"], ahora, par,
                                       a.excluidos_para(par, cfg), a.desvio_para(par, cfg))
        if not ops:
            continue
        o = ops[0]
        coin, fiat = par.upper().split("/")
        neto = o.spread_pct - costo
        pasos = [
            f"1. Comprás {coin} en <b>{a.marcar(o.comprar_en)}</b> a {_fmt(o.precio_compra, fiat)}",
            f"   ↔️ mandás el {coin} de {o.comprar_en} a {o.vender_en} (TRC20 o Polygon)",
            f"2. Vendés {coin} en <b>{a.marcar(o.vender_en)}</b> a {_fmt(o.precio_venta, fiat)}",
        ]
        notas = [f"1 transferencia ≈ {costo:.2f}%"]
        if a.es_p2p(o.comprar_en) or a.es_p2p(o.vender_en):
            notas.append("\U0001f465 P2P: verificá la oferta")
        out.append(Oportunidad("arbitraje", f"{coin}/{fiat}: {o.comprar_en} → {o.vender_en}", neto, o.spread_pct,
                               fiat, "10 a 30 min", neto >= cfg["umbral_pct"], pasos, notas))
    return out


def de_rulos(cotizaciones: dict, dolar: dict | None, cfg: dict, ahora: float, n: int = 5) -> list[Oportunidad]:
    aristas = rl.construir_aristas(cotizaciones, dolar, cfg, ahora)
    out = []
    for r in rl.buscar_todos(aristas, cfg)[:n]:  # ya sin ciclos repetidos
        tiempo = "1 día (MEP liquida a 24 h)" if any(p.exchange == "broker" for p in r.patas) else "20 a 60 min"
        out.append(Oportunidad("rulo", r.ruta, r.neto_pct, r.rendimiento_pct, r.inicio, tiempo,
                               r.neto_pct >= cfg["umbral_rulo_pct"], rl.pasos_rulo(r), rl.notas_rulo(r, cfg)))
    return out


def de_p2p(libros: dict[str, dict[str, dict | None]], cfg: dict) -> list[Oportunidad]:
    out = []
    analisis = p2p.analizar_todo(cfg, {f: libs.get("binancep2p") for f, libs in libros.items()})
    for fiat, an in analisis.items():
        if not an:
            continue
        F = fiat.upper()
        if an["cruce_viable"]:
            out.append(Oportunidad("p2p_cruce", f"USDT en {p2p._fiat_nombre(fiat)}: {an['ask'].nombre} → {an['bid'].nombre}",
                                   an["cruce_pct"], an["cruce_pct"], F, "instantáneo",
                                   an["cruce_pct"] >= cfg.get("umbral_p2p_cruce_pct", 0.3),
                                   p2p.bloque_accion(an)[1:], ["\U0001f465 P2P: liberá solo con la plata acreditada"]))
        notas = ["se cobra por vuelta completa: alguien toma tu anuncio de compra y después el de venta"]
        if an.get("comision_pct"):
            notas.append(f"comisión de anuncio {an['comision_pct']}% por lado ya descontada")
        out.append(Oportunidad("p2p_anuncios", f"USDT en {p2p._fiat_nombre(fiat)}: comprá a {p2p._fmt(an['anuncio_compra'], fiat)} / vendé a {p2p._fmt(an['anuncio_venta'], fiat)}",
                               an["margen_pct"], an.get("margen_bruto_pct", an["margen_pct"]), F,
                               "horas o días (esperar que tomen tus anuncios)",
                               an["margen_pct"] >= cfg.get("umbral_p2p_anuncio_pct", 1.0),
                               p2p.bloque_accion(an)[1:] if an["margen_pct"] > 0 else [], notas))
    for fiat, libs in libros.items():
        cp = p2p.cruce_plataformas(libs, fiat, cfg)
        if cp:
            out.append(Oportunidad("p2p_plataformas",
                                   f"USDT en {p2p._fiat_nombre(fiat)}: {p2p.NOMBRE_PLAT.get(cp['compra_en'])} → {p2p.NOMBRE_PLAT.get(cp['venta_en'])}",
                                   cp["neto_pct"], cp["pct"], fiat.upper(), "instantáneo con USDT en las dos; si no, 5 a 10 min",
                                   cp["neto_pct"] >= cfg.get("umbral_p2p_plataformas_pct", 0.7),
                                   p2p.bloque_cruce_plataformas(cp, cfg)[1:], [f"mover USDT ≈ {cp['costo_pct']:.2f}% ya descontado"]))
    return out


def recolectar(cfg: dict) -> list[Oportunidad]:
    """Descarga todo una sola vez y arma el ranking completo, de mejor a peor neto."""
    ahora = time.time()
    cotizaciones = a.descargar_varios(cfg["pares"], cfg["volumen"], cfg)
    try:
        dolar = a.obtener_dolar()
    except Exception:  # noqa: BLE001
        dolar = None
    libros = p2p.descargar_libros_plataformas(cfg) if cfg.get("p2p_binance_directo") else {}
    ops = de_arbitraje(cotizaciones, cfg, ahora) + de_rulos(cotizaciones, dolar, cfg, ahora) + de_p2p(libros, cfg)
    ops.sort(key=lambda o: -o.neto_pct)
    return ops


# ---------- formato ----------

def formatear(ops: list[Oportunidad], cfg: dict, n: int = 6) -> str:
    SEP = a.SEP
    if not ops:
        return "No pude leer las cotizaciones ahora; probá de nuevo en un minuto."
    mejor = ops[0]
    capital = "USDT" if cfg.get("capital_usdt") else "ARS"
    out = ["\U0001f3c6 <b>Mejores oportunidades ahora</b>  <i>todas las monedas, neto después de costos</i>", SEP]
    if mejor.alerta:
        out.append(f"\U0001f4cc <b>Veredicto: hay oportunidad.</b> {TIPO_NOMBRE[mejor.tipo]} → <b>{mejor.neto_pct:+.2f}%</b> neto "
                   f"empezando en {mejor.moneda} · {mejor.tiempo}.")
    elif mejor.neto_pct > 0:
        out.append(f"\U0001f4cc <b>Veredicto: nada supera su umbral.</b> Lo mejor deja {mejor.neto_pct:+.2f}% neto "
                   f"({TIPO_NOMBRE[mejor.tipo].lower()}). Esperá la alerta.")
    else:
        out.append("\U0001f4cc <b>Veredicto: nada positivo ahora.</b> Todo lo que hay pierde después de costos.")
    out.append(SEP)
    for i, o in enumerate(ops[:n]):
        mio = " \U0001f4bc" if o.moneda == capital else ""
        out.append(f"{i + 1}. {o.sem} <b>{TIPO_NOMBRE[o.tipo]}</b>{mio} — neto <b>{o.neto_pct:+.2f}%</b> <i>(bruto {o.bruto_pct:+.2f}%)</i>")
        out.append(f"   {o.titulo} · empezás en {o.moneda} · {o.tiempo}")
    if mejor.pasos:
        out += [SEP, f"\U0001f4cb <b>Pasos del 1º</b>"] + mejor.pasos
        if mejor.notas:
            out.append("<i>" + " · ".join(mejor.notas) + "</i>")
    out += [SEP, f"<i>\U0001f4bc = empieza en tu moneda ({capital}). Para ver otro en detalle: /rulos, /p2p o /arbitraje.</i>"]
    return "\n".join(out)


def informe(cfg: dict) -> str:
    return formatear(recolectar(cfg), cfg)
