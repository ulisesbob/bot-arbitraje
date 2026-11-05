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
