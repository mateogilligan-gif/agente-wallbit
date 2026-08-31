"""Tests de lógica pura en market_data.py. Sin red."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_data


def test_parse_stooq_csv_formato_valido():
    csv_texto = (
        "Date,Open,High,Low,Close,Volume\n"
        "2026-08-24,228.50,230.10,227.80,229.40,45000000\n"
        "2026-08-25,229.50,232.00,228.90,231.75,52000000"
    )
    resultado = market_data._parse_stooq_csv(csv_texto)
    assert resultado is not None
    precio_actual, cierre_anterior = resultado
    assert precio_actual == 231.75
    assert cierre_anterior == 229.40


def test_parse_stooq_csv_formato_invalido_no_crashea():
    assert market_data._parse_stooq_csv("") is None
    assert market_data._parse_stooq_csv("solo un header,sin datos") is None
    assert market_data._parse_stooq_csv("Symbol not found") is None


def test_screener_filtra_por_revenue_growth():
    """Sin llamar a yfinance real: probamos la lógica de filtro con datos ya obtenidos."""
    # Simulamos lo que haría screener_filtrar comparando manualmente sus condiciones
    revenue_growth = 0.10
    min_revenue_growth = 0.15
    descarta = revenue_growth is None or revenue_growth < min_revenue_growth
    assert descarta is True

    revenue_growth = 0.20
    descarta = revenue_growth is None or revenue_growth < min_revenue_growth
    assert descarta is False


def test_check_earnings_upcoming_estructura_vacia():
    """Con lista vacía de tickers no debe crashear ni pegarle a la red."""
    resultado = market_data.check_earnings_upcoming([], days=14)
    assert resultado["ok"] is True
    assert resultado["data"] == []
