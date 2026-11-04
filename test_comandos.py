import re
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
    txt = a.texto_plano(c.resp_moneda("usdt", USDT, "ARS", ahora=NOW))
    assert "viejo" not in txt
    # mas barato para comprar: binancep2p (1669), luego okexp2p (1672), fiwind (1680)
    assert txt.index("1. binancep2p") < txt.index("2. okexp2p") < txt.index("3. fiwind")
    # mejor para vender: okexp2p (1669) primero
    assert re.search(r"1\. okexp2p \U0001f465\s+1,669\.00", txt)  # P2P va marcado
    assert "Spread entre ambos: +0.00%" in txt


def test_dolar_ordena_de_barato_a_caro_y_marca_el_mejor():
    txt = a.texto_plano(c.resp_dolar(DOLAR, {"usdt": USDT}, ahora=NOW))
    filas = [l for l in txt.splitlines() if "$" in l and ("⭐" in l or l.startswith("  "))]
    assert "Blue" in filas[0] and "⭐" in filas[0]
    assert "Oficial" in filas[1]
    assert "Tarjeta" in filas[5]
    assert re.search(r"USDT\s+binancep2p \U0001f465\s+\$\s+1,669\.00", txt)


def test_dolar_sin_datos():
    assert "No pude" in c.resp_dolar({}, {})


def test_umbral_lee_y_cambia(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "CONFIG_PATH", tmp_path / "config.json")
    cfg = dict(a.CONFIG_DEFAULT)
    assert f"{cfg['umbral_pct']}%" in c.resp_umbral(cfg, None)
    assert "1.5%" in c.resp_umbral(cfg, "1,5")
    assert cfg["umbral_pct"] == 1.5
    assert (tmp_path / "config.json").exists()
    assert "No entendí" in c.resp_umbral(cfg, "abc")
    assert "entre 0 y 50" in c.resp_umbral(cfg, "99")


def test_arbitraje_marca_los_que_superan_umbral():
    o1 = a.Oportunidad("usdt/usd", "binancep2p", 1.04, "fiwind", 1.065, 2.4)
    o2 = a.Oportunidad("btc/ars", "x", 100, "y", 99, -1.0)
    txt = a.texto_plano(c.resp_arbitraje([("btc/ars", o2), ("usdt/usd", o1), ("eth/ars", None)], umbral=1.0))
    assert "\U0001f7e2 USDT/USD  +2.40%" in txt   # verde: supera el umbral
    assert "\U0001f534 BTC/ARS  -1.00%" in txt    # rojo: negativo
    assert txt.index("USDT/USD") < txt.index("BTC/ARS")  # ordenado de mejor a peor
    assert "sin datos: ETH/ARS" in txt


def test_manejar_comando_desconocido_devuelve_ayuda():
    txt = c.manejar("/loquesea", dict(a.CONFIG_DEFAULT))
    assert "No conozco" in txt and "/dolar" in txt


def test_manejar_acepta_sufijo_de_bot_y_mayusculas():
    assert c.manejar("/AYUDA@botarbitrajetrecbot", dict(a.CONFIG_DEFAULT)) == c.resp_ayuda()


def test_exclusion_se_aplica_en_moneda_y_dolar():
    ex = {"binancep2p"}
    txt = a.texto_plano(c.resp_moneda("usdt", USDT, "ARS", ahora=NOW, excluir=ex))
    assert "binancep2p" not in txt and "1. okexp2p" in txt
    txt = a.texto_plano(c.resp_dolar(DOLAR, {"usdt": USDT}, ahora=NOW, excluir=ex))
    assert "binancep2p" not in txt and re.search(r"USDT\s+okexp2p", txt)
    assert a.CONFIG_DEFAULT["excluir_exchanges"] == []


def test_patron_p2p_excluye_todos_los_p2p():
    ex = {"*p2p"}
    assert a.esta_excluido("binancep2p", ex) and a.esta_excluido("bybitp2p", ex) and a.esta_excluido("lemoncashp2p", ex)
    assert not a.esta_excluido("binance", ex) and not a.esta_excluido("fiwind", ex)
    txt = a.texto_plano(c.resp_moneda("usdt", USDT, "ARS", ahora=NOW, excluir=ex))
    assert "p2p" not in txt and "1. fiwind" in txt


def test_p2p_entra_marcado_con_advertencia():
    o = a.Oportunidad("usdt/ars", "binancep2p", 1660, "fiwind", 1690, 1.8)
    txt = a.texto_plano(a.formatear(o, 1000, incluir_pasos=False))
    assert "binancep2p 👥" in txt and "P2P" in txt and "Verificá precio" in txt
    sin = a.texto_plano(a.formatear(a.Oportunidad("usdt/ars", "ripio", 1660, "fiwind", 1690, 1.8), 1000, False))
    assert "👥" not in sin and "P2P" not in sin
    lst = a.texto_plano(c.resp_arbitraje([("usdt/ars", o)], umbral=1.0))
    assert "binancep2p 👥" in lst and "P2P" in lst
    mon = a.texto_plano(c.resp_moneda("usdt", USDT, "ARS", ahora=NOW))
    assert "binancep2p 👥" in mon and "P2P" in mon
