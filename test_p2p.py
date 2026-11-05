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
        assert "countries" not in b and b["payTypes"] == ["MercadoPagoNew", "UalaNew"]
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
    assert r == {"usdt/usd:binancep2p": "directo", "usdt/ars:binancep2p": "sin"}
    assert cots["usdt/usd"]["binancep2p"]["totalAsk"] == 1.065 and cots["usdt/usd"]["fiwind"]["totalAsk"] == 1.067
    assert "binancep2p" not in cots["usdt/ars"]       # sin ofertas para tus metodos: no mostrar
    assert cots["dai/ars"]["binancep2p"]["totalAsk"] == 1  # DAI no esta en Binance P2P: queda CriptoYa

    def explota(req, timeout=0): raise OSError("sin red")
    monkeypatch.setattr(p2p.urllib.request, "urlopen", explota)
    cots2 = {"btc/usd": {"binancep2p": {"totalAsk": 85000, "totalBid": 84000, "time": 1}}}
    assert p2p.aplicar(cots2, cfg) == {"btc/usd:binancep2p": "criptoya"}
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
    monkeypatch.setattr(p2p, "descargar_libros_plataformas", lambda cfg: {"ars": {"binancep2p": lib["ars"]}, "usd": {}})
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


def test_montos_desde_capital():
    assert p2p.montos_p2p(dict(a.CONFIG_DEFAULT, capital_ars=160000, capital_usdt=0, dolar_aprox=1600)) == {"ars": 80000, "usd": 50}
    assert p2p.montos_p2p(dict(a.CONFIG_DEFAULT, capital_usdt=1000, dolar_aprox=1600)) == {"ars": 800000, "usd": 500}
    assert p2p.capital_en_pesos(dict(a.CONFIG_DEFAULT, capital_usdt=1000), precio_usdt=1650) == 1650000
    assert p2p.montos_p2p(dict(a.CONFIG_DEFAULT, capital_ars=None, capital_usdt=0, p2p_monto={"ars": 5, "usd": 1})) == {"ars": 5, "usd": 1}
    assert p2p.montos_p2p(dict(a.CONFIG_DEFAULT), capital=100000)["ars"] == 50000


def test_plan_capital():
    cfg = _cfg(capital_ars=160000, capital_usdt=0)
    an = p2p.analizar_fiat({"compra": [_of("compra", 1660.0, nombre="vende1", minimo=20000)],
                            "venta": [_of("venta", 1650.0)]}, "ars", 80000, cfg)
    txt = a.texto_plano(p2p.plan_capital(160000, an, cfg))
    assert "Plan para arrancar con $ 160,000" in txt and "$ 80,000 quedan en Mercado Pago" in txt
    assert "48 USDT" in txt and "vende1 a $ 1,660.00" in txt
    assert "anuncio de COMPRA" in txt and "anuncio de VENTA" in txt and "l\u00edmites $ 20,000 a $ 80,000" in txt
    assert "Margen por vuelta hoy" in txt and "Reglas:" in txt
    assert "No pude leer" in a.texto_plano(p2p.plan_capital(160000, None, cfg))


def test_monto_parseo():
    from comandos import _monto
    assert _monto("160000") == 160000 and _monto("160.000") == 160000 and _monto("$160k") == 160000
    assert _monto(None) is None and _monto("abc") is None


def test_plan_capital_desde_usdt():
    cfg = _cfg(capital_usdt=1078)
    an = p2p.analizar_fiat({"compra": [_of("compra", 1668.0, nombre="vende1")],
                            "venta": [_of("venta", 1657.0, nombre="compra1", minimo=100000, maximo=2000000)]}, "ars", 890000, cfg)
    txt = a.texto_plano(p2p.plan_capital(1078 * 1657.0, an, cfg, usdt_total=1078))
    assert "1,078 USDT" in txt and "Vendé 539 USDT" in txt and "compra1 te paga" in txt
    assert "te entran $ 893,123" in txt and "539 USDT quedan en Binance" in txt
    assert "anuncio de COMPRA" in txt and "límites $ 223,000 a $ 893,123" in txt
    assert "comprá" not in txt.split("2. Publicá")[0]  # con USDT no hay compra inicial


def test_monto_y_unidad_usdt():
    from comandos import _monto, _unidad
    assert _monto("1078usdt") == 1078 and _monto("1078") == 1078
    assert _unidad(["/capital", "1078", "usdt"]) == "usdt" and _unidad(["/capital", "1078usdt"]) == "usdt"
    assert _unidad(["/capital", "160000"]) == "ars"


def test_plan_elige_contraparte_confiable():
    cfg = _cfg(capital_usdt=1000, p2p_min_ops=50, p2p_min_tasa=0.95)
    venta = [_of("venta", 1660.0, nombre="nuevito", ordenes=14, tasa=0.82),
             _of("venta", 1655.0, nombre="veterano", ordenes=300, tasa=0.99)]
    an = p2p.analizar_fiat({"compra": [_of("compra", 1668.0)], "venta": venta}, "ars", 800000, cfg)
    txt = a.texto_plano(p2p.plan_capital(1000 * 1660, an, cfg, usdt_total=1000))
    assert "veterano te paga $ 1,655.00" in txt and "Hay mejor precio (nuevito a $ 1,660.00)" in txt
    # si nadie cumple, usa el mejor precio sin aviso
    cfg2 = _cfg(capital_usdt=1000, p2p_min_ops=1000)
    txt2 = a.texto_plano(p2p.plan_capital(1000 * 1660, an, cfg2, usdt_total=1000))
    assert "nuevito te paga" in txt2 and "Hay mejor precio" not in txt2


def test_coincidencia_de_metodos_en_otras_plataformas():
    mios = ["MercadoPagoNew", "UalaNew", "BankArgentina", "SantanderArgentina", "BancoBrubankNew", "NaranjaX"]
    assert p2p._coincide("Mercadopago", mios) and p2p._coincide("Uala", mios) and p2p._coincide("Naranja X", mios)
    assert p2p._coincide("Bank Transfer (Argentina)", mios) and p2p._coincide("bank", mios) and p2p._coincide("Santander Rio (Argentina)", mios)
    assert not p2p._coincide("Santander Uruguay", mios) and not p2p._coincide("Lemon Cash", mios) and not p2p._coincide("Wise", mios)
    # en dolares "Bank Transfer" a secas es cualquier banco del mundo: no cuenta
    assert not p2p._coincide("Bank Transfer", mios, "usd") and p2p._coincide("Bank Transfer (Argentina)", mios, "usd")
    assert p2p.plataformas_para("ars", dict(a.CONFIG_DEFAULT)) == ["binancep2p", "bybitp2p", "okexp2p", "bitgetp2p"]
    assert p2p.plataformas_para("usd", dict(a.CONFIG_DEFAULT)) == ["binancep2p"]


def test_libros_de_otras_plataformas(monkeypatch):
    mios = ["MercadoPagoNew", "UalaNew"]
    monkeypatch.setattr(p2p, "_bybit_nombres", lambda: {"129": "Mercadopago", "134": "Uala", "14": "Bank Transfer"})

    def post(url, body):
        if "bybit" in url:
            precio = "1658.00" if body["side"] == "1" else "1653.50"
            return {"result": {"items": [
                {"price": precio, "nickName": "by1", "payments": ["129"], "minAmount": "50000", "maxAmount": "900000", "recentOrderNum": 217, "recentExecuteRate": 100},
                {"price": "1600", "nickName": "by2", "payments": ["14"], "minAmount": "1", "maxAmount": "9", "recentOrderNum": 1, "recentExecuteRate": 50}]}}
        if "bitget" in url:
            precio = "1667" if body["side"] == 1 else "1659.1"
            return {"data": {"dataList": [{"price": precio, "nickName": "bg1", "paymethodInfo": [{"paymethodName": "Mercadopago"}],
                                           "minAmount": "40000", "maxAmount": "400000", "thirtyCompletionRate": "0.99"}]}}
        raise AssertionError(url)

    def get(url):
        side = "sell" if "side=sell" in url else "buy"
        precio = "1661.00" if side == "sell" else "1656.31"
        return {"data": {side: [{"price": precio, "nickName": "ok1", "paymentMethods": ["Uala", "Mercadopago"],
                                 "quoteMinAmountPerOrder": "50000", "quoteMaxAmountPerOrder": "750000",
                                 "completedOrderQuantity": 9981, "completedRate": 0.96}]}}
    monkeypatch.setattr(p2p, "_post", post)
    monkeypatch.setattr(p2p, "_get", get)
    by = p2p.libro_bybit("usdt", "ars", mios, 500000)
    assert by["compra"][0].precio == 1658.0 and by["venta"][0].precio == 1653.5 and by["compra"][0].plataforma == "bybitp2p"
    assert all(o.nombre == "by1" for o in by["compra"] + by["venta"])  # by2 no acepta tus metodos ni el monto
    ok = p2p.libro_okx("usdt", "ars", mios, 500000)
    assert ok["compra"][0].precio == 1661.0 and ok["venta"][0].precio == 1656.31 and ok["venta"][0].ordenes_mes == 9981
    bg = p2p.libro_bitget("usdt", "ars", mios, 100000)
    assert bg["compra"][0].precio == 1667.0 and bg["venta"][0].precio == 1659.1 and bg["venta"][0].tasa == 0.99


def test_cruce_entre_plataformas_y_alerta():
    cfg = _cfg(capital_usdt=1000, dolar_aprox=1650, p2p_transferencia_usd=1.0, umbral_p2p_plataformas_pct=0.7)
    libros = {
        "binancep2p": {"compra": [_of("compra", 1652.6, nombre="b_vende", maximo=4000000)], "venta": [_of("venta", 1646.0, nombre="b_compra")]},
        "bitgetp2p": {"compra": [_of("compra", 1667.0)], "venta": [_of("venta", 1670.0, nombre="bg_compra", maximo=400000)]},
        "okexp2p": None,
    }
    cp = p2p.cruce_plataformas(libros, "ars", cfg)
    assert cp["compra_en"] == "binancep2p" and cp["venta_en"] == "bitgetp2p"
    assert abs(cp["pct"] - (1670 - 1652.6) / 1652.6 * 100) < 1e-9
    usdt = 825000 / 1652.6
    assert abs(cp["costo_pct"] - 1.0 / usdt * 100) < 1e-9 and abs(cp["neto_pct"] - (cp["pct"] - cp["costo_pct"])) < 1e-9
    assert cp["operable"] == 400000
    txt = a.texto_plano(p2p.formatear_alerta_plataformas(cp, cfg))
    assert "CRUCE ENTRE P2P en pesos" in txt and "Comprás en Binance" in txt and "Vendés en Bitget" in txt and "bg_compra" in txt
    actuales = p2p.detectar({"ars": None}, cfg, {"ars": cp})
    assert "plataformas|ars" in actuales
    # sin dos plataformas distintas no hay cruce
    assert p2p.cruce_plataformas({"binancep2p": libros["binancep2p"]}, "ars", cfg) is None
