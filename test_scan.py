import time
import arbitraje as a
import rulos as r
from api import scan as s


def test_cooldown_en_memoria_comparte_el_dict():
    estado = {}
    cd = a.Cooldown(300, estado=estado)
    assert cd.permitir("usdt/ars", "x", "y", ahora=1000)
    assert estado == {"usdt/ars|x|y": 1000}
    assert not cd.permitir("usdt/ars", "x", "y", ahora=1100)
    # las vencidas se olvidan al registrar una nueva
    assert cd.permitir("btc/ars", "x", "y", ahora=2000)
    assert "usdt/ars|x|y" not in estado and "btc/ars|x|y" in estado


def test_escanear_devuelve_estado_nuevo(monkeypatch):
    NOW = time.time()
    q = lambda ask, bid: {"totalAsk": ask, "totalBid": bid, "time": NOW}
    cots = {"usdt/ars": {"exA": q(1600, 1590), "exB": q(1660, 1650), "exC": q(1640, 1630)}}
    monkeypatch.setattr(a, "descargar_varios", lambda pares, vol, cfg=None: cots)
    monkeypatch.setattr(a, "obtener_dolar", lambda: {"oficial": {"ask": 1547, "bid": 1500}})
    enviados = []
    monkeypatch.setattr(a, "enviar_telegram", lambda t, c, m: enviados.append(m) or True)
    monkeypatch.setattr(a, "cargar_config", lambda escribir=True: dict(
        a.CONFIG_DEFAULT, pares=["usdt/ars"], excluir_exchanges=[], telegram_token="t", telegram_chat_id="c",
        max_desvio_pct=0, p2p_alertas=False, p2p_binance_directo=False))
    r1 = s.escanear({})
    assert r1["alertas"] == 1 and len(enviados) == 1  # exA -> exB = +3.1%
    assert list(r1["estado"]["cooldown"]) == ["usdt/ars|exA|exB"]
    assert r1["estado"]["rulos"] == {} and r1["ms"] >= 0
    # segunda pasada con el estado devuelto: no repite
    r2 = s.escanear(r1["estado"])
    assert r2["alertas"] == 0 and len(enviados) == 1


def test_procesar_rulos_sin_disco(tmp_path):
    NOW = time.time()
    q = lambda ask, bid: {"totalAsk": ask, "totalBid": bid, "time": NOW}
    cots = {"usdt/ars": {"exB": q(1670, 1662)}, "usdt/usd": {"exA": q(1.043, 1.030)}}
    cfg = dict(a.CONFIG_DEFAULT, excluir_exchanges=[], telegram_token="", telegram_chat_id="")
    nuevos, cerrados, estado = r.procesar(cfg, cots, {"oficial": {"ask": 1547, "bid": 1500}}, {}, NOW)
    assert len(nuevos) == 1 and cerrados == [] and len(estado) == 1
    assert not (tmp_path / "rulos.json").exists()
