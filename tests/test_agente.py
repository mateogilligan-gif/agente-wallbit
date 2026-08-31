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
