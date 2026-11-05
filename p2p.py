"""Cotizacion directa de Binance P2P filtrada por metodos de pago y monto.

CriptoYa publica para binancep2p el mejor precio entre TODAS las ofertas, y en los pares en
dolares la mejor suele pedir un banco de Panama o Wise. Consultando Binance directo con los
metodos de pago que uno realmente tiene (Mercado Pago, Uala, banco argentino) el precio es el
que de verdad se puede operar.

Endpoint publico (el mismo que usa la web de Binance), sin login.
"""

from __future__ import annotations

import json
import time
import urllib.request

URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"

# Activos que Binance P2P opera contra ARS y USD
ACTIVOS = {"usdt", "usdc", "btc", "eth", "bnb"}


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
