import time
import arbitraje as a

NOW = int(time.time())

QUOTES = {
    "ripio":     {"ask": 1694, "totalAsk": 1694, "bid": 1655, "totalBid": 1647, "time": NOW},
    "binancep2p": {"ask": 1669, "totalAsk": 1669, "bid": 1663, "totalBid": 1663, "time": NOW},
    "okexp2p":   {"ask": 1672, "totalAsk": 1672, "bid": 1669, "totalBid": 1669, "time": NOW},
    "huobip2p":  {"ask": 0,    "totalAsk": 0,    "bid": 1213, "totalBid": 1213, "time": NOW - 99999},
    "fakezero":  {"ask": 1000, "totalAsk": 1000, "bid": 0,    "totalBid": 0,    "time": NOW},
}


def test_filtra_precios_cero_y_viejos():
    validas = a.filtrar_cotizaciones(QUOTES, max_antiguedad=600, ahora=NOW)
    assert set(validas) == {"ripio", "binancep2p", "okexp2p"}


def test_detecta_mejor_oportunidad():
    ops = a.detectar_oportunidades(QUOTES, umbral_pct=0.0, max_antiguedad=600, ahora=NOW)
    mejor = ops[0]
    assert mejor.comprar_en == "binancep2p"
    assert mejor.vender_en == "okexp2p"
    assert mejor.precio_compra == 1669
    assert mejor.precio_venta == 1669
    assert mejor.spread_pct == 0.0


def test_respeta_umbral():
    q = dict(QUOTES)
    q["barato"] = {"ask": 1600, "totalAsk": 1600, "bid": 1590, "totalBid": 1590, "time": NOW}
    ops = a.detectar_oportunidades(q, umbral_pct=2.0, max_antiguedad=600, ahora=NOW)
    assert len(ops) == 3  # barato -> okexp2p / binancep2p / ripio, mejor primero
    assert all(o.comprar_en == "barato" for o in ops)
    assert [o.vender_en for o in ops] == ["okexp2p", "binancep2p", "ripio"]
    assert abs(ops[0].spread_pct - (1669 - 1600) / 1600 * 100) < 1e-9
    assert a.detectar_oportunidades(q, umbral_pct=10.0, max_antiguedad=600, ahora=NOW) == []


def test_no_cruza_mismo_exchange():
    q = {"solo": {"ask": 100, "totalAsk": 100, "bid": 200, "totalBid": 200, "time": NOW}}
    assert a.detectar_oportunidades(q, umbral_pct=0.0, max_antiguedad=600, ahora=NOW) == []


def test_cooldown_evita_repetir():
    cd = a.Cooldown(segundos=300)
    assert cd.permitir("usdt/ars", "a", "b", ahora=1000)
    assert not cd.permitir("usdt/ars", "a", "b", ahora=1100)
    assert cd.permitir("usdt/ars", "a", "c", ahora=1100)
    assert cd.permitir("usdt/ars", "a", "b", ahora=1301)


def test_descarta_outliers_respecto_a_mediana():
    q = dict(QUOTES)
    q["basura"] = {"ask": 1850, "totalAsk": 1850, "bid": 1850, "totalBid": 1850, "time": NOW}
    validas = a.filtrar_cotizaciones(q, max_antiguedad=600, ahora=NOW, max_desvio_pct=5.0)
    assert "basura" not in validas
    assert "binancep2p" in validas
    # con el filtro apagado, vuelve a aparecer
    assert "basura" in a.filtrar_cotizaciones(q, max_antiguedad=600, ahora=NOW, max_desvio_pct=0)


def test_formato_precio_usa_4_decimales_para_usd():
    assert a.precio(1.0659) == "1.0659"
    assert a.precio(1667.6) == "1,667.60"
    o = a.Oportunidad("usdt/usd", "binancep2p", 1.04, "fiwind", 1.065, 2.4)
    msg = a.texto_plano(a.formatear(o, 1000))
    assert "1.0400" in msg and "1.0650" in msg
    assert "+2.40%" in msg and "~24 USD" in msg


def test_alerta_incluye_pasos_con_los_exchanges():
    o = a.Oportunidad("usdt/usd", "binancep2p", 1.04, "fiwind", 1.065, 2.4)
    msg = a.texto_plano(a.formatear(o, 1000, incluir_pasos=True))
    assert "Cómo ejecutarlo" in msg
    assert "En binancep2p: comprá USDT" in msg and "Retirar USDT" in msg and "vendé el USDT en fiwind" in msg
    assert "Cómo ejecutarlo" not in a.formatear(o, 1000, incluir_pasos=False)


def test_cooldown_persiste_entre_reinicios(tmp_path):
    archivo = tmp_path / "cd.json"
    cd1 = a.Cooldown(segundos=300, archivo=archivo)
    assert cd1.permitir("usdt/usd", "a", "b", ahora=1000)
    cd2 = a.Cooldown(segundos=300, archivo=archivo)  # "reinicio"
    assert not cd2.permitir("usdt/usd", "a", "b", ahora=1100)
    assert cd2.permitir("usdt/usd", "a", "b", ahora=1301)


def test_ciclo_escanea_y_atiende_comandos(monkeypatch):
    llamadas = []
    monkeypatch.setattr(a, "pasada", lambda cfg, cd: llamadas.append("pasada"))
    monkeypatch.setattr(a, "atender_comandos", lambda cfg, off, espera: (llamadas.append(("cmds", espera)), 42)[1])
    monkeypatch.setattr(a, "confirmar_mensajes", lambda token, off: llamadas.append(("ack", off)))
    cfg = dict(a.CONFIG_DEFAULT, telegram_token="t", telegram_chat_id="c")
    a.ciclo(cfg, a.Cooldown(1))
    assert llamadas == ["pasada", ("cmds", 0), ("ack", 42)]


def test_ciclo_sin_telegram_solo_escanea(monkeypatch):
    llamadas = []
    monkeypatch.setattr(a, "pasada", lambda cfg, cd: llamadas.append("pasada"))
    monkeypatch.setattr(a, "atender_comandos", lambda *x: llamadas.append("cmds"))
    a.ciclo(dict(a.CONFIG_DEFAULT), a.Cooldown(1))
    assert llamadas == ["pasada"]
