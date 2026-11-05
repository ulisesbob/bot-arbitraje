import time
import arbitraje as a


def test_exclusion_por_fiat_solo_en_dolares():
    cfg = dict(a.CONFIG_DEFAULT, excluir_por_fiat={"usd": ["*p2p", "p2pme"]})
    assert a.esta_excluido("binancep2p", a.excluidos_para("usdt/usd", cfg))
    assert a.esta_excluido("p2pme", a.excluidos_para("usdc/usd", cfg))
    assert not a.esta_excluido("binancep2p", a.excluidos_para("usdt/ars", cfg))
    assert not a.esta_excluido("fiwind", a.excluidos_para("usdt/usd", cfg))
    assert not a.esta_excluido("binancep2p", a.excluidos_para("usdt/usd", dict(a.CONFIG_DEFAULT)))  # default: entran


def test_apertura_y_cierre_de_arbitraje_simple():
    o = a.Oportunidad("usdt/ars", "a", 100, "b", 102, 2.0)
    clave = "usdt/ars|a|b"
    nuevas, cerradas, estado = a.actualizar_abiertas({}, {clave: o}, {clave: o}, ahora=1000)
    assert nuevas == [clave] and cerradas == [] and estado[clave]["max"] == 2.0
    o2 = a.Oportunidad("usdt/ars", "a", 100, "b", 103, 3.0)      # sigue abierta, sube el maximo
    nuevas, cerradas, estado = a.actualizar_abiertas(estado, {clave: o2}, {clave: o2}, ahora=1600)
    assert nuevas == [] and cerradas == [] and estado[clave]["max"] == 3.0
    o3 = a.Oportunidad("usdt/ars", "a", 100, "b", 100.5, 0.5)    # cae bajo el umbral: se cierra
    nuevas, cerradas, estado = a.actualizar_abiertas(estado, {}, {clave: o3}, ahora=2200)
    assert nuevas == [] and estado == {} and len(cerradas) == 1
    c = cerradas[0]
    assert c["max"] == 3.0 and c["ahora"] == 0.5 and abs(c["duracion_min"] - 20) < 1e-9
    txt = a.texto_plano(a.formatear_cierres(cerradas))
    assert "SE CERR" in txt and "USDT/ARS a → b" in txt and "+3.00%" in txt and "ahora +0.50%" in txt and "20 min" in txt


def test_pasada_avisa_una_vez_al_abrir_y_una_al_cerrar(monkeypatch):
    NOW = time.time()
    q = lambda ask, bid: {"totalAsk": ask, "totalBid": bid, "time": NOW}
    cots = {"usdt/ars": {"exA": q(1600, 1590), "exB": q(1660, 1650), "exC": q(1640, 1610)}}
    monkeypatch.setattr(a, "descargar_varios", lambda pares, vol: cots)
    enviados = []
    monkeypatch.setattr(a, "enviar_telegram", lambda t, c, m: enviados.append(m) or True)
    cfg = dict(a.CONFIG_DEFAULT, pares=["usdt/ars"], excluir_exchanges=[], telegram_token="t",
               telegram_chat_id="c", max_desvio_pct=0, rulos=False)
    abiertas = {}
    cd = a.Cooldown(1, estado={})
    for _ in range(30):                                            # 30 pasadas con la oportunidad abierta
        a.pasada(cfg, cd, mostrar_resumen=False, abiertas=abiertas)
    assert len(enviados) == 1 and "ARBITRAJE USDT/ARS" in enviados[0] and "usdt/ars|exA|exB" in abiertas
    cots["usdt/ars"]["exB"] = q(1660, 1605)                          # el spread cae a 0.3%
    a.pasada(cfg, cd, mostrar_resumen=False, abiertas=abiertas)
    assert len(enviados) == 2 and "SE CERR" in enviados[1] and abiertas == {}
