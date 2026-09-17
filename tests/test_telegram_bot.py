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
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-no-real")

import database
_tmp_dir = tempfile.mkdtemp()
database.DB_PATH = Path(_tmp_dir) / "test_agente.db"
database.init_db()

import telegram_bot


@pytest.fixture(autouse=True)
def _limpiar_estado_sueldo():
    """
    database.DB_PATH es un global compartido por TODOS los archivos de test
    que lo tocan (pytest importa todos los módulos de test antes de correr
    ninguno, así que termina apuntando al último que lo reasigna) — sin este
    reset, un test de test_salary_dca.py que deja guardado un rango de días
    o un traspaso pendiente le cambiaría el comportamiento a los tests de
    este archivo. Se corre antes de cada test; los que necesitan un valor
    puntual lo configuran ellos mismos después.
    """
    for clave in ("DCA_SUELDO_DIA_DESDE", "DCA_SUELDO_DIA_HASTA", "DCA_SUELDO_MONTO_ESPERADO",
                  "DCA_SUELDO_CASH_BASELINE", "DCA_SUELDO_ESPERA_DESDE"):
        database.guardar_config(clave, "")
    yield


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
    database.guardar_config("DCA_SUELDO_MONTO_ESPERADO", "")  # nada pendiente, no interfiere
    database.guardar_config("DCA_SUELDO_DIA_DESDE", "")
    database.guardar_config("DCA_SUELDO_DIA_HASTA", "")
    database.guardar_config("DCA_SUELDO_ULTIMA_FECHA", "2026-09-01")

    contextos_recibidos = []

    def chat_falso(mensaje, contexto_extra=""):
        contextos_recibidos.append(contexto_extra)
        return "SIN_NOVEDADES"

    monkeypatch.setattr(telegram_bot.agente, "chat", chat_falso)
    asyncio.run(telegram_bot.chequear_sueldo_diario(_ContextFalso(_BotFalso())))

    assert "2026-09-01" in contextos_recibidos[0]
    assert "CHEQUEO_AUTOMATICO_SUELDO" in contextos_recibidos[0]


# ─── ventana de días (DCA_SUELDO_DIA_DESDE/HASTA) ───────────────────────────
# El chequeo de sueldo nuevo solo debería llamar a la API de Wallbit cuando
# hoy cae dentro del rango configurado — el resto del mes, ni se molesta.
# Estos tests mockean salary_dca.hoy_esta_en_ventana_sueldo (ya probada por
# su cuenta en test_salary_dca.py) para no depender de la fecha real del
# sistema y poder forzar los dos casos.

def test_fuera_de_la_ventana_de_dias_no_llama_al_agente(monkeypatch):
    monkeypatch.setattr(telegram_bot, "AUTHORIZED_USER_ID", 999999)
    database.guardar_config("DCA_SUELDO_MONTO_ESPERADO", "")  # nada pendiente
    monkeypatch.setattr(telegram_bot.salary_dca, "hoy_esta_en_ventana_sueldo", lambda *a, **k: False)

    llamadas = []
    monkeypatch.setattr(telegram_bot.agente, "chat", lambda *a, **k: llamadas.append(1) or "no debería llegar acá")

    asyncio.run(telegram_bot.chequear_sueldo_diario(_ContextFalso(_BotFalso())))

    assert llamadas == []  # ni se llamó al agente para buscar el sueldo


def test_dentro_de_la_ventana_de_dias_si_llama_al_agente(monkeypatch):
    monkeypatch.setattr(telegram_bot, "AUTHORIZED_USER_ID", 999999)
    database.guardar_config("DCA_SUELDO_MONTO_ESPERADO", "")
    monkeypatch.setattr(telegram_bot.salary_dca, "hoy_esta_en_ventana_sueldo", lambda *a, **k: True)

    llamadas = []
    monkeypatch.setattr(telegram_bot.agente, "chat", lambda *a, **k: llamadas.append(1) or "SIN_NOVEDADES")

    asyncio.run(telegram_bot.chequear_sueldo_diario(_ContextFalso(_BotFalso())))

    assert llamadas == [1]


def test_pasa_el_rango_de_dias_guardado_como_enteros(monkeypatch):
    monkeypatch.setattr(telegram_bot, "AUTHORIZED_USER_ID", 999999)
    database.guardar_config("DCA_SUELDO_MONTO_ESPERADO", "")
    database.guardar_config("DCA_SUELDO_DIA_DESDE", "28")
    database.guardar_config("DCA_SUELDO_DIA_HASTA", "3")

    args_recibidos = {}

    def ventana_falsa(dia_desde, dia_hasta):
        args_recibidos["dia_desde"] = dia_desde
        args_recibidos["dia_hasta"] = dia_hasta
        return False

    monkeypatch.setattr(telegram_bot.salary_dca, "hoy_esta_en_ventana_sueldo", ventana_falsa)
    asyncio.run(telegram_bot.chequear_sueldo_diario(_ContextFalso(_BotFalso())))

    assert args_recibidos == {"dia_desde": 28, "dia_hasta": 3}


# ─── traspaso pendiente (_chequear_traspaso_pendiente) ──────────────────────
# Chequeo del traspaso manual a la cuenta de Inversión: barato cuando no hay
# nada pendiente (no debería tocar Wallbit para nada), detecta la llegada de
# fondos comparando contra la foto guardada, y se rinde solo después de
# LIMITE_DIAS_ESPERA_TRASPASO días sin novedades.

def test_traspaso_pendiente_no_llama_a_wallbit_si_no_hay_nada_pendiente(monkeypatch):
    database.guardar_config("DCA_SUELDO_MONTO_ESPERADO", "")

    def falla_si_se_llama():
        raise AssertionError("no debería llamar a Wallbit si no hay traspaso pendiente")

    monkeypatch.setattr(telegram_bot.wallbit_client, "get_stocks_balance", falla_si_se_llama)

    assert telegram_bot._chequear_traspaso_pendiente() is None


def test_traspaso_pendiente_detecta_llegada_de_fondos_y_arma_ticket(monkeypatch):
    database.guardar_config("DCA_SUELDO_MONTO_ESPERADO", "500")
    database.guardar_config("DCA_SUELDO_CASH_BASELINE", "100")
    database.guardar_config("DCA_SUELDO_ESPERA_DESDE", date.today().isoformat())
    monkeypatch.setattr(telegram_bot.wallbit_client, "get_stocks_balance", lambda: {"ok": True, "data": '{"cash": 610}'})

    contextos_recibidos = []

    def chat_falso(mensaje, contexto_extra=""):
        contextos_recibidos.append(contexto_extra)
        return "Ticket armado, confirmás?"

    monkeypatch.setattr(telegram_bot.agente, "chat", chat_falso)

    resultado = telegram_bot._chequear_traspaso_pendiente()

    assert resultado == "Ticket armado, confirmás?"
    assert "CHEQUEO_TRASPASO_SUELDO" in contextos_recibidos[0]
    assert "510.00" in contextos_recibidos[0]  # delta real: 610 - 100
    assert not database.obtener_config("DCA_SUELDO_MONTO_ESPERADO")  # se limpió el estado


def test_traspaso_pendiente_no_detecta_si_todavia_no_llego_la_plata(monkeypatch):
    database.guardar_config("DCA_SUELDO_MONTO_ESPERADO", "500")
    database.guardar_config("DCA_SUELDO_CASH_BASELINE", "100")
    database.guardar_config("DCA_SUELDO_ESPERA_DESDE", date.today().isoformat())
    monkeypatch.setattr(telegram_bot.wallbit_client, "get_stocks_balance", lambda: {"ok": True, "data": '{"cash": 105}'})

    resultado = telegram_bot._chequear_traspaso_pendiente()

    assert resultado is None
    assert database.obtener_config("DCA_SUELDO_MONTO_ESPERADO") == "500"  # sigue esperando


def test_traspaso_pendiente_vencido_deja_de_esperar_sin_tocar_wallbit(monkeypatch):
    from datetime import timedelta
    hace_15_dias = (date.today() - timedelta(days=15)).isoformat()
    database.guardar_config("DCA_SUELDO_MONTO_ESPERADO", "500")
    database.guardar_config("DCA_SUELDO_CASH_BASELINE", "100")
    database.guardar_config("DCA_SUELDO_ESPERA_DESDE", hace_15_dias)

    def falla_si_se_llama():
        raise AssertionError("no debería llamar a Wallbit si ya venció el plazo de espera")

    monkeypatch.setattr(telegram_bot.wallbit_client, "get_stocks_balance", falla_si_se_llama)

    resultado = telegram_bot._chequear_traspaso_pendiente()

    assert resultado is not None
    assert "10 días" in resultado
    assert not database.obtener_config("DCA_SUELDO_MONTO_ESPERADO")  # se limpió el estado
