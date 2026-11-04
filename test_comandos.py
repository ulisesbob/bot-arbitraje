import time
import arbitraje as a
import comandos as c

NOW = int(time.time())

USDT = {
    "ripio":      {"totalAsk": 1694, "totalBid": 1647, "time": NOW},
    "binancep2p": {"totalAsk": 1669, "totalBid": 1663, "time": NOW},
    "okexp2p":    {"totalAsk": 1672, "totalBid": 1669, "time": NOW},
    "fiwind":     {"totalAsk": 1680, "totalBid": 1664, "time": NOW},
    "viejo":      {"totalAsk": 1500, "totalBid": 1700, "time": NOW - 99999},
}

DOLAR = {
    "oficial": {"ask": 1570, "bid": 1520},
    "blue": {"ask": 1565, "bid": 1545},
    "mep": {"al30": {"24hs": {"price": 1577.39}}},
    "ccl": {"al30": {"24hs": {"price": 1677.22}}},
    "tarjeta": {"price": 2041},
}


def test_ayuda_lista_todos_los_comandos():
    txt = c.resp_ayuda()
    for cmd, _ in c.COMANDOS:
        assert f"/{cmd}" in txt


def test_moneda_ordena_compra_y_venta_y_descarta_viejos():
    txt = c.resp_moneda("usdt", USDT, "ARS", ahora=NOW)
    assert "viejo" not in txt
    # mas barato para comprar: binancep2p (1669), luego okexp2p (1672), fiwind (1680)
    assert txt.index("1. binancep2p") < txt.index("2. okexp2p") < txt.index("3. fiwind")
    # mejor para vender: okexp2p (1669) primero
    assert "1. okexp2p: 1,669.00" in txt
    assert "Spread entre ambos: +0.00%" in txt


def test_dolar_ordena_de_barato_a_caro_y_marca_el_mejor():
    txt = c.resp_dolar(DOLAR, {"usdt": USDT}, ahora=NOW)
    lineas = [l for l in txt.splitlines() if l[:2] in ("1.", "2.", "3.", "4.", "5.", "6.")]
    assert "Blue" in lineas[0] and "⭐" in lineas[0]
    assert "Oficial" in lineas[1]
    assert "Tarjeta" in lineas[-1]
    assert "USDT: binancep2p a $1,669.00" in txt


def test_dolar_sin_datos():
    assert "No pude" in c.resp_dolar({}, {})


def test_umbral_lee_y_cambia(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "CONFIG_PATH", tmp_path / "config.json")
    cfg = dict(a.CONFIG_DEFAULT)
    assert "1.0%" in c.resp_umbral(cfg, None)
    assert "1.5%" in c.resp_umbral(cfg, "1,5")
    assert cfg["umbral_pct"] == 1.5
    assert (tmp_path / "config.json").exists()
    assert "No entendi" in c.resp_umbral(cfg, "abc")
    assert "entre 0 y 50" in c.resp_umbral(cfg, "99")


def test_arbitraje_marca_los_que_superan_umbral():
    o1 = a.Oportunidad("usdt/usd", "binancep2p", 1.04, "fiwind", 1.065, 2.4)
    o2 = a.Oportunidad("btc/ars", "x", 100, "y", 99, -1.0)
    txt = c.resp_arbitraje([("usdt/usd", o1), ("btc/ars", o2), ("eth/ars", None)], umbral=1.0)
    assert "USDT/USD: +2.40% \U0001f6a8" in txt
    assert "BTC/ARS: -1.00%\n" in txt
    assert "ETH/ARS: sin datos" in txt


def test_manejar_comando_desconocido_devuelve_ayuda():
    txt = c.manejar("/loquesea", dict(a.CONFIG_DEFAULT))
    assert "No conozco" in txt and "/dolar" in txt


def test_manejar_acepta_sufijo_de_bot_y_mayusculas():
    assert c.manejar("/AYUDA@botarbitrajetrecbot", dict(a.CONFIG_DEFAULT)) == c.resp_ayuda()
