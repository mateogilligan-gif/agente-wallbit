"""
Tests de lógica pura en agente.py. Sin red, sin llamar a la API de Anthropic.

Cubren dos bugs reales encontrados en auditoría:
1. Historial de conversación que se corrompía (turnos repetidos) tras un
   error de API — Anthropic exige alternancia estricta user/assistant.
2. Cálculo de disparo de alertas de porcentaje.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# agente.py importa `anthropic` y `database` al cargar — necesitamos que el
# import no truene aunque no haya ANTHROPIC_API_KEY configurada en este entorno.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-no-real")

import agente


def test_sanitizar_alternancia_fusiona_turnos_repetidos():
    """Bug real: dos mensajes 'user' seguidos rompían la llamada a la API."""
    historial_roto = [
        {"role": "user", "content": "Cual es mi balance?"},
        {"role": "user", "content": "Hola, seguis ahi?"},  # huerfano por el bug
        {"role": "assistant", "content": "Tu balance es X"},
        {"role": "user", "content": "Dale gracias"},
    ]
    limpio = agente._sanitizar_alternancia(historial_roto)
    roles = [m["role"] for m in limpio]
    # Nunca dos roles iguales seguidos
    assert all(roles[i] != roles[i + 1] for i in range(len(roles) - 1))
    # Arranca en "user"
    assert roles[0] == "user"


def test_sanitizar_alternancia_no_toca_historial_sano():
    historial_sano = [
        {"role": "user", "content": "Hola"},
        {"role": "assistant", "content": "Hola, como te ayudo?"},
    ]
    limpio = agente._sanitizar_alternancia(historial_sano)
    assert limpio == historial_sano


def test_sanitizar_alternancia_lista_vacia():
    assert agente._sanitizar_alternancia([]) == []


def test_evaluar_disparo_pct_sube_supera_umbral():
    cambio_pct, dispara = agente._evaluar_disparo_pct(
        precio_actual=106, precio_referencia=100, umbral_pct=5, direccion="ambas"
    )
    assert cambio_pct == 6.0
    assert dispara is True


def test_evaluar_disparo_pct_baja_pero_direccion_es_solo_sube():
    cambio_pct, dispara = agente._evaluar_disparo_pct(
        precio_actual=97, precio_referencia=100, umbral_pct=5, direccion="sube"
    )
    assert cambio_pct == -3.0
    assert dispara is False


def test_evaluar_disparo_pct_baja_supera_umbral_direccion_baja():
    cambio_pct, dispara = agente._evaluar_disparo_pct(
        precio_actual=92, precio_referencia=100, umbral_pct=5, direccion="baja"
    )
    assert cambio_pct == -8.0
    assert dispara is True


def test_evaluar_disparo_pct_no_alcanza_el_umbral():
    cambio_pct, dispara = agente._evaluar_disparo_pct(
        precio_actual=102, precio_referencia=100, umbral_pct=5, direccion="ambas"
    )
    assert cambio_pct == 2.0
    assert dispara is False


def test_evaluar_disparo_pct_ganancia_desde_compra():
    cambio_pct, dispara = agente._evaluar_disparo_pct(
        precio_actual=125, precio_referencia=100, umbral_pct=20, direccion="ambas"
    )
    assert cambio_pct == 25.0
    assert dispara is True


# ─── Prompt modular ─────────────────────────────────────────────────────────
# Antes el system prompt era un solo string fijo con los 11 protocolos
# siempre presentes. Ahora PROMPT_CORE va siempre y los módulos de
# PROMPT_MODULES se suman solo si el mensaje trae sus palabras clave.

def test_prompt_core_siempre_presente():
    for msg in ["cuál es mi saldo?", "dame un debate de AAPL", "hola"]:
        assert agente.PROMPT_CORE in agente.construir_system_prompt(msg)


def test_prompt_mensaje_generico_no_suma_modulos():
    p = agente.construir_system_prompt("cuál es mi saldo?")
    assert p == agente.PROMPT_CORE


def test_prompt_suma_solo_el_modulo_con_keyword():
    p = agente.construir_system_prompt("dame un debate de AAPL")
    assert agente.PROMPT_MODULES["bull_bear"]["texto"] in p
    assert agente.PROMPT_MODULES["screener_tesis"]["texto"] not in p
    assert agente.PROMPT_MODULES["morning_note"]["texto"] not in p


def test_prompt_profundo_suma_todos_los_modulos_como_red_de_seguridad():
    p = agente.construir_system_prompt("analizame TSLA en profundo")
    for modulo in agente.PROMPT_MODULES.values():
        assert modulo["texto"] in p


def test_prompt_busca_keywords_tambien_en_contexto_extra():
    p = agente.construir_system_prompt("dale, arrancá", contexto_extra="Dame mi Morning Briefing")
    assert agente.PROMPT_MODULES["morning_note"]["texto"] in p
