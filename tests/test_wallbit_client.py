"""
Tests del parser de portfolio de Wallbit. Corren sin red — solo lógica pura.

Cubren dos bugs reales que encontramos en auditoría y corregimos:
1. El parser confundía claves como "cash"/"updated_at" con tickers falsos.
2. Un saldo de $0 se trataba como "dato faltante" (bug de falsy en Python).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wallbit_client


def test_parsea_formato_dict_de_tickers():
    """Formato {AAPL: {...}, MSFT: {...}}."""
    raw = '{"AAPL": {"shares": 10, "avg_cost": 150.0}, "MSFT": {"shares": 5, "avg_cost": 300.0}}'
    posiciones = wallbit_client._parse_portfolio_text(raw)
    tickers = {p["ticker"] for p in posiciones}
    assert tickers == {"AAPL", "MSFT"}


def test_no_confunde_campos_no_ticker_con_posiciones():
    """Bug real: 'cash', 'updated_at' no deben aparecer como tickers falsos."""
    raw = (
        '{"AAPL": {"shares": 10, "avg_cost": 150.0}, '
        '"cash": 500.0, "updated_at": "2026-08-25", '
        '"MSFT": {"shares": 5, "avg_cost": 300.0}}'
    )
    posiciones = wallbit_client._parse_portfolio_text(raw)
    tickers = {p["ticker"] for p in posiciones}
    assert "CASH" not in tickers
    assert "UPDATED_AT" not in tickers
    assert tickers == {"AAPL", "MSFT"}


def test_parsea_formato_array_positions():
    raw = '{"positions": [{"ticker": "NVDA", "shares": 3, "avg_cost": 400.0}]}'
    posiciones = wallbit_client._parse_portfolio_text(raw)
    assert len(posiciones) == 1
    assert posiciones[0]["ticker"] == "NVDA"


def test_texto_no_json_devuelve_lista_vacia():
    """Si Wallbit devuelve texto plano no parseable, no debe crashear."""
    posiciones = wallbit_client._parse_portfolio_text("esto no es JSON para nada")
    assert posiciones == []


def test_saldo_cero_no_se_trata_como_dato_faltante():
    """Bug real: `0 or d.get(...)` trataba un saldo de $0 como si faltara el dato."""
    checking_res = {"ok": True, "data": '{"balance": 0}'}
    stocks_res = {"ok": True, "data": "[]"}
    resumen = wallbit_client.format_portfolio_summary(checking_res, stocks_res)
    assert "CUENTA CORRIENTE: $0" in resumen


def test_saldo_normal_se_muestra_bien():
    checking_res = {"ok": True, "data": '{"balance": 1500.50}'}
    stocks_res = {"ok": True, "data": "[]"}
    resumen = wallbit_client.format_portfolio_summary(checking_res, stocks_res)
    assert "1500.5" in resumen
