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


# ─── Módulo de inversión de sueldo (DCA con split fijo) ─────────────────────

def test_prompt_suma_modulo_sueldo_con_keyword_explicita():
    p = agente.construir_system_prompt("quiero configurar el split fijo de mi sueldo")
    assert agente.PROMPT_MODULES["inversion_sueldo_dca"]["texto"] in p


def test_prompt_suma_modulo_sueldo_en_el_chequeo_automatico_diario():
    """El job diario de telegram_bot.py manda esto como contexto_extra — tiene
    que disparar el módulo igual que si Mateo lo pidiera por chat."""
    p = agente.construir_system_prompt("Chequeo automático de sueldo.", contexto_extra="CHEQUEO_AUTOMATICO_SUELDO: revisá list_transactions...")
    assert agente.PROMPT_MODULES["inversion_sueldo_dca"]["texto"] in p


def test_modulo_sueldo_no_tiene_excepciones_a_la_confirmacion():
    """Guardrail de regresión: el texto del módulo no debe sugerir nunca
    ejecutar create_trade sin el SÍ explícito del usuario, ni siquiera en el
    chequeo automático."""
    texto = agente.PROMPT_MODULES["inversion_sueldo_dca"]["texto"]
    assert "SIN_NOVEDADES" in texto  # la corrida silenciosa no manda mensajes falsos
    assert "NO tiene excepciones" in texto  # la regla de confirmación se reafirma explícitamente


def test_modulo_sueldo_pregunta_dia_aproximado_y_no_asume_el_emisor_de_nadie():
    """Guardrail de regresión: la detección por emisor ('Origen: Wallbit LLC')
    fue un hallazgo puntual de la cuenta de Mateo, no una verdad general del
    bot — el wizard tiene que preguntarle a cada usuario, no asumir la
    respuesta de nadie más. También cubre que la fecha aproximada del sueldo
    quedó como señal extra de refuerzo."""
    texto = agente.PROMPT_MODULES["inversion_sueldo_dca"]["texto"]
    assert "DCA_SUELDO_DIA_APROX" in texto
    assert "no asumir la respuesta de nadie más" in texto


def test_modulo_sueldo_avisa_el_tope_de_10_tickers():
    """El tope de 10 tickers está aplicado en código (salary_dca.validar_split),
    pero también tiene que estar en el wizard para que el LLM no deje que el
    usuario configure de más y se entere recién al fallar la tool."""
    texto = agente.PROMPT_MODULES["inversion_sueldo_dca"]["texto"]
    assert "Máximo 10 tickers" in texto
