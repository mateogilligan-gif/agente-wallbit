"""Tests de lógica pura en apewisdom_client.py. Sin red."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import apewisdom_client

RESULTADOS_FAKE = [
    {"rank": "5", "ticker": "AAPL", "name": "Apple", "mentions": "120", "upvotes": "800",
     "rank_24h_ago": "12", "mentions_24h_ago": "60"},
    {"rank": "300", "ticker": "XYZ", "name": "XYZ Corp", "mentions": "3", "upvotes": "2",
     "rank_24h_ago": "50", "mentions_24h_ago": "10"},
]


def test_buscar_ticker_encuentra_por_mayusculas_o_minusculas():
    item = apewisdom_client._buscar_ticker(RESULTADOS_FAKE, "aapl")
    assert item is not None
    assert item["ticker"] == "AAPL"


def test_buscar_ticker_no_encontrado_devuelve_none():
    assert apewisdom_client._buscar_ticker(RESULTADOS_FAKE, "NVDA") is None


def test_tendencia_ranking_subiendo_cuando_rank_baja_de_numero():
    # ranking #1 es el MAS mencionado -> un numero mas chico hoy = subio de moda
    assert apewisdom_client.tendencia_ranking(rank=5, rank_24h_ago=12) == "subiendo"


def test_tendencia_ranking_bajando_cuando_rank_sube_de_numero():
    assert apewisdom_client.tendencia_ranking(rank=300, rank_24h_ago=50) == "bajando"


def test_tendencia_ranking_estable():
    assert apewisdom_client.tendencia_ranking(rank=10, rank_24h_ago=10) == "estable"


def test_tendencia_ranking_sin_dato_de_ayer():
    assert apewisdom_client.tendencia_ranking(rank=10, rank_24h_ago=None) == "sin dato de ayer"
