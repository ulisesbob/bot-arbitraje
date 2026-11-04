import arbitraje as a
import comandos as c
from api import telegram as w


def _update(chat_id, texto):
    return {"message": {"chat": {"id": chat_id}, "text": texto}}


def test_webhook_responde_solo_al_chat_configurado(monkeypatch):
    enviados = []
    monkeypatch.setattr(a, "cargar_config", lambda escribir=True: dict(a.CONFIG_DEFAULT, telegram_token="t", telegram_chat_id="123"))
    monkeypatch.setattr(c, "manejar", lambda texto, cfg, persistente=True: f"resp:{texto}:{persistente}")
    monkeypatch.setattr(a, "enviar_telegram", lambda tok, chat, msg: enviados.append((chat, msg)) or True)
    assert w.procesar(_update(123, "/dolar")).endswith("ok")
    assert enviados == [("123", "resp:/dolar:False")]
    assert "ignorado" in w.procesar(_update(999, "/dolar"))
    assert "ignorado" in w.procesar(_update(123, "hola"))
    assert len(enviados) == 1


def test_umbral_no_persistente_explica():
    cfg = dict(a.CONFIG_DEFAULT)
    txt = c.resp_umbral(cfg, "2", persistente=False)
    assert "no puedo guardarlo" in txt and cfg["umbral_pct"] == a.CONFIG_DEFAULT["umbral_pct"]


def test_ciclo_sin_comandos_no_lee_mensajes(monkeypatch):
    llamadas = []
    monkeypatch.setattr(a, "pasada", lambda cfg, cd: llamadas.append("pasada"))
    monkeypatch.setattr(a, "atender_comandos", lambda *x: llamadas.append("cmds"))
    cfg = dict(a.CONFIG_DEFAULT, telegram_token="t", telegram_chat_id="c")
    a.ciclo(cfg, a.Cooldown(1), sin_comandos=True)
    assert llamadas == ["pasada"]


def test_cargar_config_sin_escribir_no_crea_archivo(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "CONFIG_PATH", tmp_path / "config.json")
    cfg = a.cargar_config(escribir=False)
    assert cfg["pares"] == a.CONFIG_DEFAULT["pares"]
    assert not (tmp_path / "config.json").exists()


def test_variables_de_entorno_se_limpian(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc\r\n")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", " 555\n")
    cfg = a.cargar_config(escribir=False)
    assert cfg["telegram_token"] == "123:abc" and cfg["telegram_chat_id"] == "555"
