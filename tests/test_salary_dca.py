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
