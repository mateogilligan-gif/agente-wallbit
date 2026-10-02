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


# ─── Análisis de empresa — jefe de equipo de analistas ──────────────────────
# Se sumó el framing de "analista financiero/broker" (verificación de ticker,
# nunca desde memoria, riesgos, fuentes) que ya usábamos en la skill de
# research de Mateo, para que el bot de Telegram investigue con el mismo
# nivel de rigor.

def test_analisis_empresa_verifica_el_ticker_antes_de_investigar():
    assert "VERIFICAR EL TICKER" in agente.PROMPT_CORE
    assert "get_asset" in agente.PROMPT_CORE


def test_analisis_empresa_nunca_contesta_desde_memoria():
    assert "nunca contestar precio, market cap, noticias o estado de una empresa desde memoria" in agente.PROMPT_CORE


def test_analisis_empresa_pide_riesgos_y_fuentes():
    assert "RIESGOS CLAVE" in agente.PROMPT_CORE
    assert "FUENTES" in agente.PROMPT_CORE


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


# ─── Módulo de planes DCA programados ───────────────────────────────────────

def test_prompt_suma_modulo_planes_dca_con_keyword():
    for msg in ["quiero armar un plan de DCA", "configurame una compra recurrente el día 5", "mostrame mis planes", "pausá el plan 2"]:
        assert agente.PROMPT_MODULES["planes_dca"]["texto"] in agente.construir_system_prompt(msg)


def test_prompt_suma_modulo_planes_dca_con_el_contexto_de_tickets_pendientes():
    """telegram_bot.mensaje_libre suma este contexto cuando el job dejó tickets
    esperando respuesta: un simple "SÍ" tiene que traer el módulo."""
    p = agente.construir_system_prompt("SÍ", contexto_extra="PLANES_DCA_PENDIENTES: tickets esperando respuesta: plan 1 ...")
    assert agente.PROMPT_MODULES["planes_dca"]["texto"] in p


def test_modulo_planes_dca_dice_que_no_hay_research():
    texto = agente.PROMPT_MODULES["planes_dca"]["texto"]
    assert "SIN RESEARCH" in texto
    for prohibido in ("ANÁLISIS DE EMPRESA", "noticias_empresa", "brave_search", "decision_log"):
        assert prohibido in texto
    assert "NO se sugieren cambios de tickers" in texto


def test_modulo_planes_dca_confirmacion_sin_excepciones_y_solo_por_la_tool():
    texto = agente.PROMPT_MODULES["planes_dca"]["texto"]
    assert "NO tiene excepciones" in texto
    assert "SOLO ejecutar_plan_dca" in texto
    assert "nunca create_trade directo" in texto


def test_modulo_planes_dca_pide_si_plan_n_con_varios_pendientes():
    texto = agente.PROMPT_MODULES["planes_dca"]["texto"]
    assert 'solo vale "SÍ plan N"' in texto
    assert "Ante un SÍ sin número, NO ejecutes nada" in texto


def test_modulo_planes_dca_guardar_es_la_unica_palabra_para_guardar():
    texto = agente.PROMPT_MODULES["planes_dca"]["texto"]
    assert "Respondé GUARDAR" in texto
    assert "SÍ queda reservado EXCLUSIVAMENTE para comprar" in texto
    assert 'Nunca pidas "sí" para guardar un plan' in texto


def test_ya_no_existe_el_modulo_de_sueldo():
    assert "inversion_sueldo_dca" not in agente.PROMPT_MODULES
    assert not any(n in agente.TOOL_REGISTRY for n in (
        "calcular_split_sueldo", "calcular_monto_a_invertir_sueldo", "guardar_rango_dias_sueldo", "iniciar_espera_traspaso_sueldo"))
    assert "gestionar_plan_dca" in agente.TOOL_REGISTRY and "ejecutar_plan_dca" in agente.TOOL_REGISTRY


def test_ticket_guardado_como_mensaje_del_bot_no_rompe_la_alternancia():
    """El job guarda el ticket como mensaje 'assistant' sin un 'user' antes
    (incluso dos tickets seguidos): el historial tiene que seguir alternado."""
    historial = [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "hola, ¿en qué te ayudo?"},
        {"role": "assistant", "content": "Plan 1 — ticket ... Respondé SÍ plan 1"},
        {"role": "assistant", "content": "Plan 2 — ticket ... Respondé SÍ plan 2"},
        {"role": "user", "content": "SÍ plan 1"},
    ]
    limpio = agente._sanitizar_alternancia(historial)
    roles = [m["role"] for m in limpio]
    assert all(roles[i] != roles[i + 1] for i in range(len(roles) - 1))
    assert roles[0] == "user"
    assert "Respondé SÍ plan 2" in limpio[1]["content"]  # se fusionaron, no se perdió ninguno


def test_historial_que_arranca_con_un_ticket_del_bot_sigue_valido():
    limpio = agente._sanitizar_alternancia([
        {"role": "assistant", "content": "Plan 1 — ticket ... Respondé SÍ"},
        {"role": "user", "content": "SÍ"},
    ])
    assert [m["role"] for m in limpio] == ["user"]


# ─── Módulo de datos de empresa (modo gratis/Brave vs fmp_pago/FMP) ─────────

def test_prompt_suma_modulo_datos_empresa_con_keyword_modo_pago():
    p = agente.construir_system_prompt("pasá a modo pago")
    assert agente.PROMPT_MODULES["datos_empresa_fmp"]["texto"] in p


def test_prompt_suma_modulo_datos_empresa_con_keyword_screener():
    p = agente.construir_system_prompt("dame un screener de empresas por sector")
    assert agente.PROMPT_MODULES["datos_empresa_fmp"]["texto"] in p


def test_prompt_mensaje_generico_no_suma_modulo_datos_empresa():
    """'analizá NVDA' no trae ninguna keyword del módulo — por eso la regla
    de 'preguntar una sola vez' vive TAMBIÉN en PROMPT_CORE (regla 6), no
    solo acá, para no depender de que el mensaje mencione el modo."""
    p = agente.construir_system_prompt("analizá NVDA")
    assert agente.PROMPT_MODULES["datos_empresa_fmp"]["texto"] not in p
    assert "noticias_empresa" in agente.PROMPT_CORE
    assert "configurar_modo_datos_empresa" in agente.PROMPT_CORE


def test_modulo_datos_empresa_pregunta_una_sola_vez():
    texto = agente.PROMPT_MODULES["datos_empresa_fmp"]["texto"]
    assert "UNA SOLA VEZ" in texto
    assert "No volver a preguntar" in texto


def test_modulo_datos_empresa_menciona_las_dos_tools():
    texto = agente.PROMPT_MODULES["datos_empresa_fmp"]["texto"]
    assert "noticias_empresa" in texto
    assert "screener_empresas" in texto
    assert "configurar_modo_datos_empresa" in texto


def test_modulo_datos_empresa_no_afirma_costo_fijo_del_screener():
    """Guardrail de regresión: las noticias están confirmadas en el plan
    Starter, pero el screener podría necesitar un plan superior — el texto
    no debe prometer el mismo costo para los dos."""
    texto = agente.PROMPT_MODULES["datos_empresa_fmp"]["texto"]
    assert "Starter" in texto
    assert "no está confirmado" in texto or "NO está confirmado" in texto
