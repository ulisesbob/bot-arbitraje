import json
import arbitraje as a
import p2p


def _fake_urlopen(respuestas):
    """respuestas: {(asset, fiat, trade): [precios]}"""
    class Resp:
        def __init__(self, datos): self.datos = datos
        def __enter__(self): return self
        def __exit__(self, *x): pass
        def read(self): return json.dumps({"data": [{"adv": {"price": str(p)}} for p in self.datos]}).encode()

    def urlopen(req, timeout=0):
        b = json.loads(req.data)
        assert b["countries"] == ["AR"] and b["payTypes"] == ["MercadoPagoNew", "UalaNew"]
        return Resp(respuestas.get((b["asset"], b["fiat"], b["tradeType"]), []))
    return urlopen


def test_cotizacion_directa_usa_mejor_oferta_por_lado(monkeypatch):
    monkeypatch.setattr(p2p.urllib.request, "urlopen", _fake_urlopen({
        ("USDT", "USD", "BUY"): [1.065, 1.066], ("USDT", "USD", "SELL"): [1.052, 1.051]}))
    c = p2p.cotizacion("usdt", "usd", ["MercadoPagoNew", "UalaNew"], 500)
    assert c["totalAsk"] == 1.065 and c["totalBid"] == 1.052 and c["time"] > 0
    assert p2p.cotizacion("dai", "ars", ["MercadoPagoNew", "UalaNew"], 1) is None  # no esta en Binance P2P


def test_aplicar_reemplaza_binancep2p_y_cae_a_criptoya_si_falla(monkeypatch):
    cfg = dict(a.CONFIG_DEFAULT, p2p_metodos=["MercadoPagoNew", "UalaNew"], p2p_monto={"usd": 500, "ars": 500000})
    cots = {"usdt/usd": {"binancep2p": {"totalAsk": 1.04, "totalBid": 1.056, "time": 1}, "fiwind": {"totalAsk": 1.067, "totalBid": 1.055, "time": 1}},
            "usdt/ars": {"binancep2p": {"totalAsk": 1600, "totalBid": 1650, "time": 1}},
            "dai/ars": {"binancep2p": {"totalAsk": 1, "totalBid": 1, "time": 1}}}
    monkeypatch.setattr(p2p.urllib.request, "urlopen", _fake_urlopen({
        ("USDT", "USD", "BUY"): [1.065], ("USDT", "USD", "SELL"): [1.052],
        ("USDT", "ARS", "BUY"): [], ("USDT", "ARS", "SELL"): [1655]}))
    r = p2p.aplicar(cots, cfg)
    assert r == {"usdt/usd": "directo", "usdt/ars": "sin"}
    assert cots["usdt/usd"]["binancep2p"]["totalAsk"] == 1.065 and cots["usdt/usd"]["fiwind"]["totalAsk"] == 1.067
    assert "binancep2p" not in cots["usdt/ars"]       # sin ofertas para tus metodos: no mostrar
    assert cots["dai/ars"]["binancep2p"]["totalAsk"] == 1  # DAI no esta en Binance P2P: queda CriptoYa

    def explota(req, timeout=0): raise OSError("sin red")
    monkeypatch.setattr(p2p.urllib.request, "urlopen", explota)
    cots2 = {"btc/usd": {"binancep2p": {"totalAsk": 85000, "totalBid": 84000, "time": 1}}}
    assert p2p.aplicar(cots2, cfg) == {"btc/usd": "criptoya"}
    assert cots2["btc/usd"]["binancep2p"]["totalAsk"] == 85000


def test_descargar_varios_aplica_p2p_cuando_esta_activo(monkeypatch):
    cfg = dict(a.CONFIG_DEFAULT, p2p_metodos=["MercadoPagoNew", "UalaNew"])
    monkeypatch.setattr(a, "obtener_cotizaciones", lambda par, vol, reintentos=2: {"binancep2p": {"totalAsk": 1.04, "totalBid": 1.05, "time": 1}})
    monkeypatch.setattr(p2p.urllib.request, "urlopen", _fake_urlopen({("USDT", "USD", "BUY"): [1.065], ("USDT", "USD", "SELL"): [1.052]}))
    assert a.descargar_varios(["usdt/usd"], 1000, cfg)["usdt/usd"]["binancep2p"]["totalAsk"] == 1.065
    assert a.descargar_varios(["usdt/usd"], 1000)["usdt/usd"]["binancep2p"]["totalAsk"] == 1.04  # sin cfg: CriptoYa


def _of(lado, precio, metodos=("MercadoPagoNew",), minimo=100_000, maximo=600_000, nombre="x", ordenes=100, tasa=0.98):
    return p2p.Oferta(lado, precio, list(metodos), minimo, maximo, nombre, ordenes, tasa)


def _cfg(**k):
    return dict(a.CONFIG_DEFAULT, telegram_token="t", telegram_chat_id="c", **k)


def test_analisis_cruce_y_anuncios():
    lib = {"compra": [_of("compra", 1655.0, nombre="vende1"), _of("compra", 1658.0)],
           "venta": [_of("venta", 1662.0, ("BankArgentina",), nombre="compra1"), _of("venta", 1650.0)]}
    an = p2p.analizar_fiat(lib, "ars", 500_000, _cfg())
    assert abs(an["cruce_pct"] - (1662 - 1655) / 1655 * 100) < 1e-9 and an["cruce_viable"]
    assert an["cruce_operable"] == 600_000 and an["cruce_minimo"] == 100_000
    # anuncios: compra un tick arriba del mejor comprador, venta un tick abajo del mejor vendedor
    tick = 1655.0 * 0.05 / 100
    assert abs(an["anuncio_compra"] - (1662.0 + tick)) < 1e-9 and abs(an["anuncio_venta"] - (1655.0 - tick)) < 1e-9
    assert an["margen_pct"] < 0  # puntas cruzadas: anunciar no deja margen
    # sin cruce y con margen para anuncios
    lib2 = {"compra": [_of("compra", 1670.0)], "venta": [_of("venta", 1640.0)]}
    an2 = p2p.analizar_fiat(lib2, "ars", 500_000, _cfg())
    assert not an2["cruce_viable"] and an2["margen_pct"] > 1.5
    assert p2p.analizar_fiat({"compra": [], "venta": [_of("venta", 1)]}, "ars", 1, _cfg()) is None


def test_dolar_implicito():
    ars = p2p.analizar_fiat({"compra": [_of("compra", 1660.0)], "venta": [_of("venta", 1655.0)]}, "ars", 500_000, _cfg())
    usd = p2p.analizar_fiat({"compra": [_of("compra", 1.065)], "venta": [_of("venta", 1.054)]}, "usd", 500, _cfg())
    imp = p2p.dolar_implicito(ars, usd)
    assert abs(imp["comprar_usd"] - 1660.0 / 1.054) < 1e-9 and abs(imp["vender_usd"] - 1655.0 / 1.065) < 1e-9


def test_informe_elige_que_hacer_y_marca_p2p():
    cfg = _cfg()
    ars = p2p.analizar_fiat({"compra": [_of("compra", 1655.0, nombre="vende1")], "venta": [_of("venta", 1662.0, nombre="compra1")]}, "ars", 500_000, cfg)
    usd = p2p.analizar_fiat({"compra": [_of("compra", 1.070)], "venta": [_of("venta", 1.050)]}, "usd", 500, cfg)
    txt = a.texto_plano(p2p.formatear_informe(ars, usd, {"oficial": {"ask": 1570}}, cfg))
    assert "QUÉ HACER: comprar y vender ya" in txt and "Comprale a vende1" in txt and "Vendele a compra1" in txt
    assert "Mercado ahora" in txt and "100k–600k" in txt and "vende1 (100 ops, 98%)" in txt
    assert "Reglas:" in txt and "PESOS" in txt and "DÓLARES" in txt
    # sin cruce pero con margen: sugiere anuncios
    usd2 = p2p.analizar_fiat({"compra": [_of("compra", 1.070)], "venta": [_of("venta", 1.050)]}, "usd", 500, cfg)
    txt2 = a.texto_plano(p2p.formatear_informe(None, usd2, None, cfg))
    assert "QUÉ HACER: publicar anuncios" in txt2 and "Anuncio de COMPRA a US$ 1.051" in txt2 and "Margen por vuelta" in txt2


def test_alertas_p2p_abren_y_cierran():
    cfg = _cfg()
    cruzado = p2p.analizar_fiat({"compra": [_of("compra", 1655.0)], "venta": [_of("venta", 1662.0)]}, "ars", 500_000, cfg)
    actuales = p2p.detectar({"ars": cruzado, "usd": None}, cfg)
    assert list(actuales) == ["cruce|ars"] and actuales["cruce|ars"]["pct"] > 0.3
    nuevas, cerradas, estado = p2p.actualizar({}, actuales, ahora=1000)
    assert nuevas == ["cruce|ars"] and cerradas == [] and estado["cruce|ars"]["max"] == actuales["cruce|ars"]["pct"]
    txt = a.texto_plano(p2p.formatear_alerta("cruce|ars", cruzado))
    assert "CRUCE P2P en pesos" in txt and "1. Comprale a" in txt and "Mercado ahora" in txt
    nuevas, cerradas, estado = p2p.actualizar(estado, {}, ahora=1600)
    assert nuevas == [] and estado == {} and cerradas[0]["tipo"] == "cruce" and abs(cerradas[0]["duracion_min"] - 10) < 1e-9
    assert "SE CERRÓ EN P2P" in a.texto_plano(p2p.formatear_cierres(cerradas))


def test_procesar_p2p_manda_alerta_una_vez(monkeypatch):
    cfg = _cfg()
    enviados = []
    monkeypatch.setattr(a, "enviar_telegram", lambda t, c, m: enviados.append(m) or True)
    lib = {"ars": {"compra": [_of("compra", 1655.0)], "venta": [_of("venta", 1662.0)]}, "usd": None}
    monkeypatch.setattr(p2p, "descargar_libros", lambda cfg: lib)
    _, _, estado = p2p.procesar(cfg, {}, ahora=1000)
    _, _, estado = p2p.procesar(cfg, estado, ahora=1060)
    assert len(enviados) == 1 and "CRUCE P2P" in enviados[0]
    lib["ars"]["venta"][0] = _of("venta", 1640.0)
    _, _, estado = p2p.procesar(cfg, estado, ahora=1200)
    assert len(enviados) == 2 and "SE CERR" in enviados[1] and estado == {}


def test_comision_de_anuncio_descuenta_del_margen():
    lib = {"compra": [_of("compra", 1670.0)], "venta": [_of("venta", 1640.0)]}
    sin = p2p.analizar_fiat(lib, "ars", 500_000, _cfg())
    con = p2p.analizar_fiat(lib, "ars", 500_000, _cfg(p2p_comision_anuncio_pct=0.35))
    assert abs(sin["margen_pct"] - sin["margen_bruto_pct"]) < 1e-9
    assert abs(con["margen_pct"] - (con["margen_bruto_pct"] - 0.7)) < 1e-9
    assert "descontada la comisi" in a.texto_plano(p2p.formatear_informe(con, None, None, _cfg(p2p_comision_anuncio_pct=0.35)))
