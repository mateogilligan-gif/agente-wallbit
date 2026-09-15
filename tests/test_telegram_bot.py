"""
Test de integración (mockeado) del job chequear_sueldo_diario en telegram_bot.py.

No se conecta a Telegram real, no llama a la API de Anthropic y no toca la
DB real (agente.db) — usa una DB sqlite temporal, un "bot" falso que solo
graba las llamadas a send_message, y un agente.chat mockeado. Sirve para
probar, sin plata ni cuentas reales de por medio, dos cosas puntuales:
1. Si agente.chat responde "SIN_NOVEDADES", no se manda ningún mensaje.
2. Si responde otra cosa, ese texto se manda tal cual por Telegram.
La ventana de fechas (DCA_SUELDO_ULTIMA_FECHA) se actualiza en los dos casos.
"""
import sys
import os
import asyncio
from pathlib import Path
from datetime import date
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-no-real")

import database
_tmp_dir = tempfile.mkdtemp()
database.DB_PATH = Path(_tmp_dir) / "test_agente.db"
database.init_db()

import telegram_bot


class _BotFalso:
    def __init__(self):
        self.mensajes_enviados = []

    async def send_message(self, chat_id, text, parse_mode=None):
        self.mensajes_enviados.append({"chat_id": chat_id, "text": text})


class _ContextFalso:
    def __init__(self, bot):
        self.bot = bot


def test_sin_novedades_no_manda_mensaje_pero_actualiza_fecha(monkeypatch):
    monkeypatch.setattr(telegram_bot, "AUTHORIZED_USER_ID", 999999)
    monkeypatch.setattr(telegram_bot.agente, "chat", lambda *a, **k: "SIN_NOVEDADES")
    database.guardar_config("DCA_SUELDO_ULTIMA_FECHA", "2020-01-01")

    bot_falso = _BotFalso()
    asyncio.run(telegram_bot.chequear_sueldo_diario(_ContextFalso(bot_falso)))

    assert bot_falso.mensajes_enviados == []
    assert database.obtener_config("DCA_SUELDO_ULTIMA_FECHA") == date.today().isoformat()


def test_con_novedades_manda_el_mensaje_del_agente(monkeypatch):
    monkeypatch.setattr(telegram_bot, "AUTHORIZED_USER_ID", 999999)
    mensaje_ticket = "[💰 SUELDO DETECTADO] Vi que ingresaron $1500..."
    monkeypatch.setattr(telegram_bot.agente, "chat", lambda *a, **k: mensaje_ticket)

    bot_falso = _BotFalso()
    asyncio.run(telegram_bot.chequear_sueldo_diario(_ContextFalso(bot_falso)))

    assert len(bot_falso.mensajes_enviados) == 1
    assert bot_falso.mensajes_enviados[0]["chat_id"] == 999999
    assert bot_falso.mensajes_enviados[0]["text"] == mensaje_ticket


def test_sin_authorized_user_id_no_hace_nada(monkeypatch):
    monkeypatch.setattr(telegram_bot, "AUTHORIZED_USER_ID", 0)
    llamadas = []
    monkeypatch.setattr(telegram_bot.agente, "chat", lambda *a, **k: llamadas.append(1) or "algo")

    bot_falso = _BotFalso()
    asyncio.run(telegram_bot.chequear_sueldo_diario(_ContextFalso(bot_falso)))

    assert llamadas == []  # ni siquiera llega a llamar al agente
    assert bot_falso.mensajes_enviados == []


def test_le_pasa_al_agente_la_ultima_fecha_guardada_como_ventana(monkeypatch):
    monkeypatch.setattr(telegram_bot, "AUTHORIZED_USER_ID", 999999)
    database.guardar_config("DCA_SUELDO_ULTIMA_FECHA", "2026-09-01")

    contextos_recibidos = []

    def chat_falso(mensaje, contexto_extra=""):
        contextos_recibidos.append(contexto_extra)
        return "SIN_NOVEDADES"

    monkeypatch.setattr(telegram_bot.agente, "chat", chat_falso)
    asyncio.run(telegram_bot.chequear_sueldo_diario(_ContextFalso(_BotFalso())))

    assert "2026-09-01" in contextos_recibidos[0]
    assert "CHEQUEO_AUTOMATICO_SUELDO" in contextos_recibidos[0]
