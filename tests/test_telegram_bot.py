"""
Test de integración (mockeado) del job chequear_planes_dca_diario y del
paso del mensaje real del usuario en mensaje_libre (telegram_bot.py).

No se conecta a Telegram real, no llama a la API de Anthropic, no toca la
DB real (agente.db) ni Wallbit — usa una DB sqlite temporal, un "bot" falso
que solo graba las llamadas a send_message y wallbit_client/agente.chat
mockeados.
"""
import sys
import os
import json
import asyncio
import sqlite3
from pathlib import Path
from datetime import date
import tempfile
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-no-real")

import database
_tmp_dir = tempfile.mkdtemp()
database.DB_PATH = Path(_tmp_dir) / "test_agente.db"
database.init_db()

import telegram_bot
import planes_dca


@pytest.fixture(autouse=True)
def _limpiar_planes(monkeypatch):
    """
    database.DB_PATH es un global compartido por TODOS los archivos de test
    que lo tocan (pytest importa todos los módulos de test antes de correr
    ninguno, así que termina apuntando al último que lo reasigna) — sin este
    reset, un plan que deja creado test_planes_dca.py le cambiaría el
    comportamiento a los tests de este archivo. create_trade queda bloqueado
    por seguridad.
    """
    database.init_db()
    conn = sqlite3.connect(database.DB_PATH)
    conn.execute("DELETE FROM planes_dca")
    conn.execute("DELETE FROM ejecuciones_dca")
    conn.execute("DELETE FROM conversaciones")
    conn.commit()
    conn.close()

    def prohibido(*a, **k):
        raise AssertionError("create_trade real llamado en un test")

    monkeypatch.setattr(planes_dca.wallbit_client, "create_trade", prohibido)
    monkeypatch.setattr(planes_dca.wallbit_client, "get_asset",
                        lambda t: {"ok": True, "data": json.dumps({"data": {"symbol": t.upper()}})})
    yield


class _BotFalso:
    def __init__(self):
        self.mensajes_enviados = []

    async def send_message(self, chat_id, text, parse_mode=None):
        self.mensajes_enviados.append({"chat_id": chat_id, "text": text})


class _ContextFalso:
    def __init__(self, bot):
        self.bot = bot


class _MensajeFalso:
    def __init__(self, texto):
        self.text = texto
        self.respuestas = []

    async def reply_text(self, texto, parse_mode=None):
        self.respuestas.append(texto)


class _UpdateFalso:
    def __init__(self, user_id, texto):
        self.effective_user = type("U", (), {"id": user_id})()
        self.message = _MensajeFalso(texto)


class _FechaFija(date):
    """date.today() fijo para el job (telegram_bot usa date.today())."""
    @classmethod
    def today(cls):
        return date(2026, 10, 5)


def _crear_plan(monkeypatch, dia=5, monto=100, tickers=("MELI", "NU", "AAPL")):
    monkeypatch.setattr(planes_dca, "_hoy", lambda: date(2026, 10, 2))
    r = planes_dca._tool_gestionar_plan_dca({"accion": "crear", "dia": dia, "monto_usd": monto, "tickers": list(tickers)})
    assert r["ok"], r


def _cash(monkeypatch, valor):
    llamadas = []
    monkeypatch.setattr(planes_dca.wallbit_client, "get_stocks_balance",
                        lambda: llamadas.append(1) or {"ok": True, "data": json.dumps({"cash": valor})})
    return llamadas


def _correr_job():
    bot = _BotFalso()
    asyncio.run(telegram_bot.chequear_planes_dca_diario(_ContextFalso(bot)))
    return bot


def test_job_sin_planes_no_llama_a_wallbit_ni_al_agente(monkeypatch):
    monkeypatch.setattr(telegram_bot, "AUTHORIZED_USER_ID", 999999)
    llamadas = _cash(monkeypatch, 1000)
    monkeypatch.setattr(telegram_bot.agente, "chat", lambda *a, **k: pytest.fail("el job no debería llamar al LLM"))
    bot = _correr_job()
    assert bot.mensajes_enviados == []
    assert llamadas == []


def test_job_manda_el_ticket_y_lo_guarda_en_el_historial(monkeypatch):
    monkeypatch.setattr(telegram_bot, "AUTHORIZED_USER_ID", 999999)
    monkeypatch.setattr(telegram_bot, "date", _FechaFija)
    monkeypatch.setattr(telegram_bot.agente, "chat", lambda *a, **k: pytest.fail("el job no debería llamar al LLM"))
    _crear_plan(monkeypatch)
    _cash(monkeypatch, 500)

    bot = _correr_job()

    assert len(bot.mensajes_enviados) == 1
    assert bot.mensajes_enviados[0]["chat_id"] == 999999
    texto = bot.mensajes_enviados[0]["text"]
    assert texto.startswith("Plan 1") and "Respondé SÍ" in texto
    historial = database.obtener_historial(limite=5)
    assert historial[-1] == {"role": "assistant", "content": texto}


def test_job_sin_authorized_user_id_no_hace_nada(monkeypatch):
    monkeypatch.setattr(telegram_bot, "AUTHORIZED_USER_ID", 0)
    monkeypatch.setattr(telegram_bot, "date", _FechaFija)
    _crear_plan(monkeypatch)
    llamadas = _cash(monkeypatch, 500)
    bot = _correr_job()
    assert bot.mensajes_enviados == []
    assert llamadas == []


def test_job_avisa_falta_de_plata(monkeypatch):
    monkeypatch.setattr(telegram_bot, "AUTHORIZED_USER_ID", 999999)
    monkeypatch.setattr(telegram_bot, "date", _FechaFija)
    _crear_plan(monkeypatch, monto=50, tickers=("NU", "CRML", "AXTI"))
    _cash(monkeypatch, 18)
    bot = _correr_job()
    assert len(bot.mensajes_enviados) == 1
    assert "te faltan USD 32.00" in bot.mensajes_enviados[0]["text"]


def test_mensaje_libre_pasa_el_texto_real_y_el_contexto_de_pendientes(monkeypatch):
    monkeypatch.setattr(telegram_bot, "AUTHORIZED_USER_ID", 999999)
    monkeypatch.setattr(telegram_bot, "date", _FechaFija)
    _crear_plan(monkeypatch)
    _cash(monkeypatch, 500)
    _correr_job()

    recibido = {}

    def chat_falso(mensaje, contexto_extra=""):
        recibido["mensaje"] = mensaje
        recibido["contexto"] = contexto_extra
        recibido["texto_real_en_la_tool"] = planes_dca.mensaje_usuario_actual()
        return "ok"

    monkeypatch.setattr(telegram_bot.agente, "chat", chat_falso)
    update = _UpdateFalso(999999, "SÍ")
    asyncio.run(telegram_bot.mensaje_libre(update, None))

    assert recibido["texto_real_en_la_tool"] == "SÍ"
    assert "PLANES_DCA_PENDIENTES" in recibido["contexto"]
    assert planes_dca.mensaje_usuario_actual() is None  # fuera del mensaje ya no vale


def test_mensaje_libre_sin_pendientes_no_suma_contexto_de_planes(monkeypatch):
    monkeypatch.setattr(telegram_bot, "AUTHORIZED_USER_ID", 999999)
    recibido = {}
    monkeypatch.setattr(telegram_bot.agente, "chat", lambda m, contexto_extra="": recibido.update(ctx=contexto_extra) or "ok")
    asyncio.run(telegram_bot.mensaje_libre(_UpdateFalso(999999, "hola"), None))
    assert "PLANES_DCA_PENDIENTES" not in recibido["ctx"]


def test_comando_balance_no_habilita_ejecutar_un_plan(monkeypatch):
    """/balance llama a agente.chat con un mensaje sintético: adentro de ese turno no hay mensaje real del usuario."""
    monkeypatch.setattr(telegram_bot, "AUTHORIZED_USER_ID", 999999)
    visto = {}
    monkeypatch.setattr(telegram_bot.agente, "chat", lambda *a, **k: visto.update(real=planes_dca.mensaje_usuario_actual()) or "ok")
    asyncio.run(telegram_bot.balance(_UpdateFalso(999999, "/balance"), None))
    assert visto["real"] is None
