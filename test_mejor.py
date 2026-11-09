import time
import arbitraje as a
import oportunidades as op
import p2p

NOW = time.time()
q = lambda ask, bid: {"totalAsk": ask, "totalBid": bid, "time": NOW}
COTS = {
    "usdt/ars": {"exA": q(1600, 1590), "exB": q(1670, 1662), "exC": q(1665, 1655)},
    "usdt/usd": {"exA": q(1.043, 1.030), "exB": q(1.065, 1.054), "exC": q(1.060, 1.050)},
}
DOLAR = {"oficial": {"ask": 1547, "bid": 1500}, "mep": {"al30": {"24hs": {"price": 1580}}}}


def _of(lado, precio, nombre="x", minimo=50_000, maximo=900_000):
    return p2p.Oferta(lado, precio, ["MercadoPagoNew"], minimo, maximo, nombre, 200, 0.99)


def _cfg():
    return dict(a.CONFIG_DEFAULT, pares=["usdt/ars", "usdt/usd"], excluir_exchanges=[], max_desvio_pct=0,
                max_desvio_usd_pct=0, telegram_token="t", telegram_chat_id="c", capital_usdt=1000)


def test_ranking_junta_todo_y_ordena(monkeypatch):
    cfg = _cfg()
    monkeypatch.setattr(a, "descargar_varios", lambda pares, vol, cfg=None: {k: dict(v) for k, v in COTS.items()})
    monkeypatch.setattr(a, "obtener_dolar", lambda: DOLAR)
    libros = {"ars": {"binancep2p": {"compra": [_of("compra", 1655.0, "v1")], "venta": [_of("venta", 1662.0, "c1")]},
                      "bitgetp2p": {"compra": [_of("compra", 1670.0)], "venta": [_of("venta", 1668.0, "bg")]}},
              "usd": {"binancep2p": {"compra": [_of("compra", 1.070)], "venta": [_of("venta", 1.050)]}}}
    monkeypatch.setattr(p2p, "descargar_libros_plataformas", lambda cfg: libros)
    ops = op.recolectar(cfg)
    tipos = {o.tipo for o in ops}
    assert {"arbitraje", "rulo", "p2p_cruce", "p2p_anuncios", "p2p_plataformas"} <= tipos
    assert [o.neto_pct for o in ops] == sorted((o.neto_pct for o in ops), reverse=True)
    # el arbitraje simple exA -> exB en pesos da 3.9% bruto menos 0.15 de transferencia
    arb = next(o for o in ops if o.tipo == "arbitraje" and o.moneda == "ARS")
    assert abs(arb.bruto_pct - (1662 - 1600) / 1600 * 100) < 1e-9 and abs(arb.neto_pct - (arb.bruto_pct - 0.15)) < 1e-9
    assert arb.alerta and "exA" in arb.titulo and "mand\u00e1s el USDT de exA a exB" in a.texto_plano("\n".join(arb.pasos))
    # hay rulos que empiezan en USDT (la moneda del usuario)
    assert any(o.tipo == "rulo" and o.moneda == "USDT" for o in ops)
    txt = a.texto_plano(op.formatear(ops, cfg))
    assert "Mejores oportunidades ahora" in txt and "Veredicto: hay oportunidad" in txt
    assert "1. \U0001f7e2" in txt and "Pasos del 1\u00ba" in txt and "\U0001f4bc" in txt


def test_formato_sin_datos_y_sin_positivos():
    cfg = _cfg()
    assert "No pude leer" in op.formatear([], cfg)
    o = op.Oportunidad("rulo", "ARS \u2192 USD \u2192 ARS", -0.5, -0.2, "ARS", "1 d\u00eda", False, ["1. x"], [])
    txt = a.texto_plano(op.formatear([o], cfg))
    assert "nada positivo" in txt and "Pasos del 1" in txt
