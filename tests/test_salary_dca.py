"""
Tests de salary_dca.py — el split de inversión de sueldo. La parte de plata
(porcentajes, redondeo, montos) es 100% pura, así que se testea sin red, sin
Wallbit y sin tocar la DB real. Solo el wrapper de la tool (_tool_calcular_split_sueldo)
usa una DB sqlite temporal para leer el split guardado, igual que test_database.py.
"""
import sys
import os
from pathlib import Path
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
_tmp_dir = tempfile.mkdtemp()
database.DB_PATH = Path(_tmp_dir) / "test_agente.db"
database.init_db()

import salary_dca


# ─── validar_split ──────────────────────────────────────────────────────────

def test_validar_split_ok_cuando_suma_100():
    ok, motivo = salary_dca.validar_split([{"ticker": "NVDA", "pct": 50}, {"ticker": "MSFT", "pct": 50}])
    assert ok is True
    assert motivo is None


def test_validar_split_rechaza_vacio():
    ok, motivo = salary_dca.validar_split([])
    assert ok is False


def test_validar_split_rechaza_suma_distinta_de_100():
    ok, motivo = salary_dca.validar_split([{"ticker": "NVDA", "pct": 50}, {"ticker": "MSFT", "pct": 30}])
    assert ok is False
    assert "80" in motivo


def test_validar_split_tolera_pequenos_errores_de_redondeo():
    # 33.33 x 3 = 99.99, no exactamente 100 — no debería rechazarse por eso
    ok, motivo = salary_dca.validar_split([{"ticker": "A", "pct": 33.33}, {"ticker": "B", "pct": 33.33}, {"ticker": "C", "pct": 33.34}])
    assert ok is True


def test_validar_split_rechaza_pct_negativo_o_cero():
    ok, motivo = salary_dca.validar_split([{"ticker": "NVDA", "pct": 0}, {"ticker": "MSFT", "pct": 100}])
    assert ok is False


def test_validar_split_rechaza_item_sin_ticker():
    ok, motivo = salary_dca.validar_split([{"pct": 100}])
    assert ok is False


def test_validar_split_rechaza_mas_de_10_tickers():
    split_11 = [{"ticker": f"T{i}", "pct": 100 / 11} for i in range(11)]
    ok, motivo = salary_dca.validar_split(split_11)
    assert ok is False
    assert "10" in motivo


def test_validar_split_acepta_justo_10_tickers():
    split_10 = [{"ticker": f"T{i}", "pct": 10} for i in range(10)]
    ok, motivo = salary_dca.validar_split(split_10)
    assert ok is True, motivo


# ─── calcular_montos ────────────────────────────────────────────────────────

def test_calcular_montos_split_simple():
    asignaciones = salary_dca.calcular_montos(500, [{"ticker": "nvda", "pct": 50}, {"ticker": "msft", "pct": 25}, {"ticker": "pltr", "pct": 25}])
    por_ticker = {a["ticker"]: a["monto"] for a in asignaciones}
    assert por_ticker == {"NVDA": 250.0, "MSFT": 125.0, "PLTR": 125.0}


def test_calcular_montos_suma_exacta_al_monto_total_pese_al_redondeo():
    # 100 / 3 = 33.333... — el caso clásico donde la suma de redondeos no da exacto
    asignaciones = salary_dca.calcular_montos(100, [{"ticker": "A", "pct": 33.33}, {"ticker": "B", "pct": 33.33}, {"ticker": "C", "pct": 33.34}])
    assert round(sum(a["monto"] for a in asignaciones), 2) == 100.0


def test_calcular_montos_rechaza_monto_cero_o_negativo():
    import pytest
    with pytest.raises(ValueError):
        salary_dca.calcular_montos(0, [{"ticker": "NVDA", "pct": 100}])


def test_calcular_montos_rechaza_split_invalido():
    import pytest
    with pytest.raises(ValueError):
        salary_dca.calcular_montos(100, [{"ticker": "NVDA", "pct": 50}])  # no suma 100


# ─── split_equitativo ───────────────────────────────────────────────────────

def test_split_equitativo_dos_tickers():
    split = salary_dca.split_equitativo(["nvda", "msft"])
    assert split == [{"ticker": "NVDA", "pct": 50.0}, {"ticker": "MSFT", "pct": 50.0}]


def test_split_equitativo_tres_tickers_suma_exacto_100():
    split = salary_dca.split_equitativo(["nvda", "msft", "pltr"])
    assert round(sum(item["pct"] for item in split), 2) == 100.0
    assert len(split) == 3


def test_split_equitativo_pasa_validar_split():
    split = salary_dca.split_equitativo(["a", "b", "c", "d", "e", "f", "g"])  # 100/7 no da redondo
    ok, motivo = salary_dca.validar_split(split)
    assert ok is True, motivo


def test_split_equitativo_rechaza_lista_vacia():
    import pytest
    with pytest.raises(ValueError):
        salary_dca.split_equitativo([])


def test_split_equitativo_rechaza_mas_de_10_tickers():
    import pytest
    with pytest.raises(ValueError):
        salary_dca.split_equitativo([f"T{i}" for i in range(11)])


# ─── parsear_split_json ─────────────────────────────────────────────────────

def test_parsear_split_json_valido():
    split = salary_dca.parsear_split_json('[{"ticker":"NVDA","pct":50},{"ticker":"MSFT","pct":50}]')
    assert split == [{"ticker": "NVDA", "pct": 50}, {"ticker": "MSFT", "pct": 50}]


def test_parsear_split_json_invalido_tira_value_error():
    import pytest
    with pytest.raises(ValueError):
        salary_dca.parsear_split_json("esto no es json")


def test_parsear_split_json_con_porcentajes_incorrectos_tira_value_error():
    import pytest
    with pytest.raises(ValueError):
        salary_dca.parsear_split_json('[{"ticker":"NVDA","pct":10}]')


# ─── armar_texto_ticket ─────────────────────────────────────────────────────

def test_armar_texto_ticket_incluye_cada_ticker_y_pregunta_confirmacion():
    asignaciones = [{"ticker": "NVDA", "pct": 50, "monto": 250.0}, {"ticker": "MSFT", "pct": 50, "monto": 250.0}]
    texto = salary_dca.armar_texto_ticket(500, asignaciones)
    assert "NVDA" in texto and "MSFT" in texto
    assert "$250.00" in texto
    assert "SÍ/NO" in texto


# ─── tool _tool_calcular_split_sueldo (usa DB temporal) ────────────────────

def test_tool_usa_split_pasado_explicitamente():
    resultado = salary_dca._tool_calcular_split_sueldo({
        "monto_total": 200,
        "split": [{"ticker": "AAPL", "pct": 100}],
    })
    assert resultado["ok"] is True
    assert resultado["data"]["asignaciones"] == [{"ticker": "AAPL", "pct": 100, "monto": 200.0}]


def test_tool_sin_split_ni_config_devuelve_error_claro():
    resultado = salary_dca._tool_calcular_split_sueldo({"monto_total": 200})
    assert resultado["ok"] is False
    assert "split" in resultado["error"].lower()


def test_tool_usa_split_guardado_en_config_si_no_se_pasa_uno():
    database.guardar_config("DCA_SUELDO_SPLIT", '[{"ticker":"NVDA","pct":50},{"ticker":"MSFT","pct":50}]')
    resultado = salary_dca._tool_calcular_split_sueldo({"monto_total": 400})
    assert resultado["ok"] is True
    por_ticker = {a["ticker"]: a["monto"] for a in resultado["data"]["asignaciones"]}
    assert por_ticker == {"NVDA": 200.0, "MSFT": 200.0}
    assert "ticket_sugerido" in resultado["data"]


def test_tool_con_tickers_hace_reparto_equitativo():
    resultado = salary_dca._tool_calcular_split_sueldo({"monto_total": 300, "tickers": ["nvda", "msft", "pltr"]})
    assert resultado["ok"] is True
    por_ticker = {a["ticker"]: a["monto"] for a in resultado["data"]["asignaciones"]}
    assert set(por_ticker) == {"NVDA", "MSFT", "PLTR"}
    assert round(sum(por_ticker.values()), 2) == 300.0


def test_tool_prioriza_split_explicito_sobre_tickers():
    resultado = salary_dca._tool_calcular_split_sueldo({
        "monto_total": 100,
        "split": [{"ticker": "AAPL", "pct": 100}],
        "tickers": ["nvda", "msft"],
    })
    assert resultado["ok"] is True
    assert resultado["data"]["asignaciones"] == [{"ticker": "AAPL", "pct": 100, "monto": 100.0}]


def test_tool_con_mas_de_10_tickers_devuelve_error_claro():
    resultado = salary_dca._tool_calcular_split_sueldo({"monto_total": 100, "tickers": [f"T{i}" for i in range(11)]})
    assert resultado["ok"] is False
    assert "10" in resultado["error"]


# ─── calcular_monto_a_invertir ──────────────────────────────────────────────

def test_calcular_monto_a_invertir_modo_porcentaje():
    assert salary_dca.calcular_monto_a_invertir(1500, "porcentaje", 10) == 150.0


def test_calcular_monto_a_invertir_modo_fijo():
    assert salary_dca.calcular_monto_a_invertir(1500, "fijo", 200) == 200.0


def test_calcular_monto_a_invertir_no_invierte_todo_por_default():
    # Con 10% de un sueldo de 1500, el resultado NO puede ser 1500 (todo el sueldo)
    monto = salary_dca.calcular_monto_a_invertir(1500, "porcentaje", 10)
    assert monto < 1500


def test_calcular_monto_a_invertir_porcentaje_100_invierte_todo():
    assert salary_dca.calcular_monto_a_invertir(1500, "porcentaje", 100) == 1500.0


def test_calcular_monto_a_invertir_rechaza_porcentaje_fuera_de_rango():
    import pytest
    with pytest.raises(ValueError):
        salary_dca.calcular_monto_a_invertir(1500, "porcentaje", 150)
    with pytest.raises(ValueError):
        salary_dca.calcular_monto_a_invertir(1500, "porcentaje", 0)


def test_calcular_monto_a_invertir_rechaza_fijo_mayor_al_sueldo():
    import pytest
    with pytest.raises(ValueError):
        salary_dca.calcular_monto_a_invertir(1500, "fijo", 2000)


def test_calcular_monto_a_invertir_rechaza_modo_desconocido():
    import pytest
    with pytest.raises(ValueError):
        salary_dca.calcular_monto_a_invertir(1500, "mitad", 10)


def test_calcular_monto_a_invertir_rechaza_sueldo_cero():
    import pytest
    with pytest.raises(ValueError):
        salary_dca.calcular_monto_a_invertir(0, "porcentaje", 10)


# ─── tool _tool_calcular_monto_a_invertir_sueldo ────────────────────────────

def test_tool_monto_a_invertir_usa_modo_y_valor_explicitos():
    resultado = salary_dca._tool_calcular_monto_a_invertir_sueldo({"monto_sueldo": 1500, "modo": "porcentaje", "valor": 10})
    assert resultado["ok"] is True
    assert resultado["data"]["monto_a_invertir"] == 150.0


def test_tool_monto_a_invertir_sin_config_ni_modo_devuelve_error_claro():
    resultado = salary_dca._tool_calcular_monto_a_invertir_sueldo({"monto_sueldo": 1500})
    assert resultado["ok"] is False
    assert "invertir" in resultado["error"].lower()


def test_tool_monto_a_invertir_usa_config_guardada_si_no_se_pasa_modo():
    database.guardar_config("DCA_SUELDO_MODO_MONTO", "fijo")
    database.guardar_config("DCA_SUELDO_MONTO_VALOR", "300")
    resultado = salary_dca._tool_calcular_monto_a_invertir_sueldo({"monto_sueldo": 1500})
    assert resultado["ok"] is True
    assert resultado["data"]["monto_a_invertir"] == 300.0


# ─── dia_en_rango ────────────────────────────────────────────────────────────
# Rango de días en que la persona suele cobrar (reemplaza al viejo "día
# aproximado" único) — se usa para decidir cuándo vale la pena que el chequeo
# diario llame a Wallbit, en vez de hacerlo los 365 días del año.

def test_dia_en_rango_simple_sin_cruzar_fin_de_mes():
    assert salary_dca.dia_en_rango(1, 5, 3) is True
    assert salary_dca.dia_en_rango(1, 5, 6) is False
    assert salary_dca.dia_en_rango(1, 5, 1) is True
    assert salary_dca.dia_en_rango(1, 5, 5) is True


def test_dia_en_rango_cruza_fin_de_mes():
    # "del 28 al 3": adentro están 28, 29, 30, 31, 1, 2, 3 — afuera el resto
    assert salary_dca.dia_en_rango(28, 3, 28) is True
    assert salary_dca.dia_en_rango(28, 3, 31) is True
    assert salary_dca.dia_en_rango(28, 3, 1) is True
    assert salary_dca.dia_en_rango(28, 3, 3) is True
    assert salary_dca.dia_en_rango(28, 3, 15) is False


def test_dia_en_rango_funciona_igual_en_meses_de_distinta_duracion():
    # No hay que "saber" cuántos días tiene el mes — solo importa el día de
    # hoy. Un mes de 30 días (ej. abril) nunca va a evaluar día 31, así que
    # el rango 28-3 se comporta igual sin ningún caso especial.
    assert salary_dca.dia_en_rango(28, 3, 30) is True  # último día de un mes de 30
    assert salary_dca.dia_en_rango(28, 3, 2) is True   # ya en el mes siguiente


# ─── validar_rango_dias ──────────────────────────────────────────────────────

def test_validar_rango_dias_acepta_valores_validos():
    assert salary_dca.validar_rango_dias(28, 3) is None
    assert salary_dca.validar_rango_dias(1, 31) is None


def test_validar_rango_dias_rechaza_fuera_de_1_31():
    assert salary_dca.validar_rango_dias(0, 5) is not None
    assert salary_dca.validar_rango_dias(1, 32) is not None


def test_validar_rango_dias_rechaza_no_enteros():
    assert salary_dca.validar_rango_dias(1.5, 5) is not None
    assert salary_dca.validar_rango_dias(1, "5") is not None


# ─── hoy_esta_en_ventana_sueldo ──────────────────────────────────────────────

def test_hoy_esta_en_ventana_sueldo_sin_rango_configurado_siempre_true():
    # Si no cargó rango (ninguno de los dos), fallback conservador: chequear siempre.
    from datetime import date
    assert salary_dca.hoy_esta_en_ventana_sueldo(None, None, hoy=date(2026, 6, 15)) is True


def test_hoy_esta_en_ventana_sueldo_respeta_el_rango_configurado():
    from datetime import date
    assert salary_dca.hoy_esta_en_ventana_sueldo(28, 3, hoy=date(2026, 6, 30)) is True
    assert salary_dca.hoy_esta_en_ventana_sueldo(28, 3, hoy=date(2026, 6, 15)) is False


# ─── traspaso_detectado ──────────────────────────────────────────────────────

def test_traspaso_detectado_con_monto_exacto():
    assert salary_dca.traspaso_detectado(500, 500) is True


def test_traspaso_detectado_tolera_transferencia_de_menos_dentro_del_margen():
    # Se avisó $500, transfirió $480 (4% menos) — sigue contando como detectado
    assert salary_dca.traspaso_detectado(480, 500) is True


def test_traspaso_detectado_no_cuenta_si_es_mucho_menos_de_lo_esperado():
    # $100 no se parece en nada a los $500 esperados — no debería dispararse
    assert salary_dca.traspaso_detectado(100, 500) is False


def test_traspaso_detectado_false_si_no_hay_monto_esperado():
    assert salary_dca.traspaso_detectado(500, 0) is False


# ─── espera_vencida ──────────────────────────────────────────────────────────

def test_espera_vencida_false_dentro_del_plazo():
    from datetime import date
    assert salary_dca.espera_vencida("2026-06-01", hoy=date(2026, 6, 5)) is False


def test_espera_vencida_true_pasado_el_plazo():
    from datetime import date
    assert salary_dca.espera_vencida("2026-06-01", hoy=date(2026, 6, 20)) is True


# ─── tool guardar_rango_dias_sueldo (usa DB temporal) ───────────────────────

def test_tool_guardar_rango_dias_sueldo_guarda_ambos_valores():
    resultado = salary_dca._tool_guardar_rango_dias_sueldo({"dia_desde": 28, "dia_hasta": 3})
    assert resultado["ok"] is True
    assert database.obtener_config("DCA_SUELDO_DIA_DESDE") == "28"
    assert database.obtener_config("DCA_SUELDO_DIA_HASTA") == "3"


def test_tool_guardar_rango_dias_sueldo_rechaza_dia_invalido():
    resultado = salary_dca._tool_guardar_rango_dias_sueldo({"dia_desde": 40, "dia_hasta": 3})
    assert resultado["ok"] is False


# ─── tool iniciar_espera_traspaso_sueldo (mockea wallbit_client) ────────────

def test_tool_iniciar_espera_traspaso_sueldo_guarda_monto_y_foto_de_cash():
    from unittest.mock import patch
    import wallbit_client

    with patch.object(wallbit_client, "get_stocks_balance", return_value={"ok": True, "data": '{"cash": 120.5}'}):
        resultado = salary_dca._tool_iniciar_espera_traspaso_sueldo({"monto_esperado": 500})

    assert resultado["ok"] is True
    assert database.obtener_config("DCA_SUELDO_MONTO_ESPERADO") == "500"
    assert database.obtener_config("DCA_SUELDO_CASH_BASELINE") == "120.5"
    assert database.obtener_config("DCA_SUELDO_ESPERA_DESDE")  # se guardó alguna fecha


def test_tool_iniciar_espera_traspaso_sueldo_rechaza_monto_invalido():
    resultado = salary_dca._tool_iniciar_espera_traspaso_sueldo({"monto_esperado": 0})
    assert resultado["ok"] is False


def test_tool_iniciar_espera_traspaso_sueldo_error_claro_si_no_puede_leer_cash():
    from unittest.mock import patch
    import wallbit_client

    with patch.object(wallbit_client, "get_stocks_balance", return_value={"ok": False, "error": "timeout"}):
        resultado = salary_dca._tool_iniciar_espera_traspaso_sueldo({"monto_esperado": 500})

    assert resultado["ok"] is False
