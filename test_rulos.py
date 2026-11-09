import time
import arbitraje as a
import rulos as r

NOW = int(time.time())
CFG = dict(a.CONFIG_DEFAULT, excluir_exchanges=[], umbral_rulo_pct=2.0, volumen_rulo=100_000)


def q(ask, bid):
    return {"totalAsk": ask, "totalBid": bid, "time": NOW}


# Escenario: dolar oficial barato (1547), USDT con dolares a 1.043 en exA, USDT por pesos a 1662 en exB
# ARS -> USD -> USDT -> ARS = 1662 / (1547 * 1.043) - 1 = +3.00%
COTS = {
    "usdt/ars": {"exB": q(1670, 1662), "exC": q(1668, 1655), "exD": q(1669, 1660)},
    "usdt/usd": {"exA": q(1.043, 1.030), "exE": q(1.060, 1.050), "exF": q(1.055, 1.045)},
    "usdc/ars": {"exB": q(1675, 1660), "exC": q(1672, 1658), "exD": q(1674, 1659)},
    "usdc/usd": {"exA": q(1.070, 1.065), "exE": q(1.072, 1.060), "exF": q(1.071, 1.062)},
}
DOLAR = {"oficial": {"ask": 1547, "bid": 1500}, "mep": {"al30": {"24hs": {"price": 1580}}}}


def test_construye_aristas_en_ambos_sentidos_y_banco():
    ar = r.construir_aristas(COTS, DOLAR, CFG, NOW)
    tramos = {(x.origen, x.destino) for x in ar}
    assert {("ARS", "USDT"), ("USDT", "ARS"), ("USD", "USDT"), ("USDT", "USD"), ("ARS", "USD"), ("USD", "ARS")} <= tramos
    banco = [x for x in ar if x.exchange == "banco" and x.destino == "USD"][0]
    assert abs(banco.tasa - 1 / 1547) < 1e-12 and banco.precio == 1547


def test_encuentra_el_rulo_del_dolar_oficial():
    rulos = r.buscar_rulos(r.construir_aristas(COTS, DOLAR, CFG, NOW))
    mejor = rulos[0]
    assert mejor.ruta == "ARS → USD → USDT → ARS"
    assert abs(mejor.rendimiento_pct - (1662 / (1547 * 1.043) - 1) * 100) < 1e-9
    assert [p.exchange for p in mejor.patas] == ["banco", "exA", "exB"]
    # no incluye ciclos de 2 patas (eso es el arbitraje simple)
    assert all(len(x.patas) >= 3 for x in rulos)
    # no repite intermedios
    assert all(len({p.destino for p in x.patas[:-1]}) == len(x.patas) - 1 for x in rulos)


def test_excluir_exchanges_saca_la_pata():
    cfg = dict(CFG, excluir_exchanges=["exA"])
    rulos = r.buscar_rulos(r.construir_aristas(COTS, DOLAR, cfg, NOW))
    assert all(p.exchange != "exA" for x in rulos for p in x.patas)


def test_detecta_nuevos_persistentes_y_cerrados():
    rulos = r.buscar_rulos(r.construir_aristas(COTS, DOLAR, CFG, NOW))
    nuevos, cerrados, estado = r.detectar_cambios({}, rulos, umbral=2.0, ahora=1000)
    assert [x.clave for x in nuevos] == [rulos[0].clave] and cerrados == []
    assert estado[rulos[0].clave]["max"] == rulos[0].neto_pct
    # segunda corrida: sigue abierto con mas rendimiento -> ni nuevo ni cerrado, sube el maximo
    rulos[0].neto_pct += 1
    nuevos2, cerrados2, estado2 = r.detectar_cambios(estado, rulos, umbral=2.0, ahora=1600)
    assert nuevos2 == [] and cerrados2 == [] and estado2[rulos[0].clave]["max"] == rulos[0].neto_pct
    # tercera: cae bajo el umbral -> cerrado con el maximo alcanzado y la duracion
    rulos[0].neto_pct = 0.5
    nuevos3, cerrados3, estado3 = r.detectar_cambios(estado2, rulos, umbral=2.0, ahora=2200)
    assert nuevos3 == [] and estado3 == {}
    assert len(cerrados3) == 1 and cerrados3[0]["max"] == estado2[rulos[0].clave]["max"]
    assert cerrados3[0]["ahora"] == 0.5 and abs(cerrados3[0]["duracion_min"] - 20) < 1e-9


def test_formato_marca_p2p_y_transferencias():
    cots = {"usdt/ars": {"bybitp2p": q(1670, 1662)}, "usdt/usd": {"binancep2p": q(1.043, 1.030)}}
    cfg = dict(CFG, excluir_por_fiat={})  # este test quiere ver un P2P en la pata en dolares
    rulo = r.buscar_rulos(r.construir_aristas(cots, DOLAR, cfg, NOW), cfg=cfg)[0]
    txt = a.texto_plano(r.formatear_rulo(rulo, 100_000, cfg))
    assert "ARS → USD → USDT → ARS" in txt and "neto" in txt and "bruto" in txt
    assert "1. Comprás dólar oficial en el banco a $ 1,547.00" in txt
    assert "mandás los dólares del banco a binancep2p" in txt and "TRC20" in txt
    assert "binancep2p \U0001f465" in txt and "P2P: precio de una persona" in txt
    assert "2 transferencias" in txt and "pata del banco" in txt
    assert rulo.movimientos == 2 and abs(rulo.neto_pct - (rulo.rendimiento_pct - 0.30)) < 1e-9
    assert f"~$ {100_000 * rulo.neto_pct / 100:,.0f} netos" in txt


def test_formato_cierre_y_listado():
    txt = a.texto_plano(r.formatear_cerrados([{"ruta": "ARS → USD → USDT → ARS", "max": 3.0, "ahora": 0.8, "duracion_min": 20}]))
    assert "SE CERRÓ" in txt and "+3.00%" in txt and "ahora +0.80%" in txt and "20 min" in txt
    rulos = r.buscar_rulos(r.construir_aristas(COTS, DOLAR, CFG, NOW))
    lst = a.texto_plano(r.formatear_listado(rulos, 2.0, n=3))
    assert lst.count("→") >= 3 and "\U0001f7e2 ARS → USD → USDT → ARS" in lst


def test_correr_manda_alertas_y_guarda_estado(tmp_path, monkeypatch):
    enviados = []
    monkeypatch.setattr(a, "enviar_telegram", lambda t, c, m: enviados.append(m) or True)
    cfg = dict(CFG, telegram_token="t", telegram_chat_id="c")
    estado = tmp_path / "rulos.json"
    nuevos, cerrados = r.correr(cfg, COTS, DOLAR, estado, ahora=1000)
    assert len(nuevos) == 1 and cerrados == [] and len(enviados) == 1 and "OPORTUNIDAD DE RULO" in enviados[0]
    assert estado.exists()
    # misma situacion otra vez: nada nuevo, nada enviado
    r.correr(cfg, COTS, DOLAR, estado, ahora=1600)
    assert len(enviados) == 1
    # sin dolar barato ya no hay rulo -> se cierra
    r.correr(cfg, COTS, {"oficial": {"ask": 1700, "bid": 1500}}, estado, ahora=2200)
    assert len(enviados) == 2 and "SE CERR" in enviados[1]


def test_mep_con_castigo_del_broker():
    cfg = dict(CFG, mep_spread_pct=1.0)
    ar = r.construir_aristas({}, DOLAR, cfg, NOW)
    compra = [x for x in ar if x.exchange == "broker" and x.destino == "USD"][0]
    venta = [x for x in ar if x.exchange == "broker" and x.origen == "USD"][0]
    assert abs(compra.precio - 1580 * 1.01) < 1e-9 and abs(venta.precio - 1580 * 0.99) < 1e-9
    assert abs(compra.tasa - 1 / (1580 * 1.01)) < 1e-12 and abs(venta.tasa - 1580 * 0.99) < 1e-9
    assert "ref. $ 1,580" in venta.accion and "1.0%" in venta.accion
    # sin castigo: referencia pura y sin nota
    ar0 = r.construir_aristas({}, DOLAR, dict(CFG, mep_spread_pct=0), NOW)
    v0 = [x for x in ar0 if x.exchange == "broker" and x.origen == "USD"][0]
    assert v0.precio == 1580 and "ref." not in v0.accion
