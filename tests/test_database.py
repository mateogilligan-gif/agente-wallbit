"""
Tests de las campañas de research en database.py. Usa una DB sqlite temporal
(no toca ~/agente-wallbit/agente.db) para poder correr sin afectar datos reales.
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


def test_crear_y_listar_campana_activa():
    campana_id = database.crear_campana_research(["aapl", "tsla"], dias=30)
    activas = database.obtener_campanas_activas()
    ids = [c[0] for c in activas]
    assert campana_id in ids
    fila = next(c for c in activas if c[0] == campana_id)
    assert fila[1] == "AAPL,TSLA"  # tickers guardados en mayúscula
    assert fila[3] == 30


def test_agregar_hallazgo_y_dedupe_por_url():
    campana_id = database.crear_campana_research(["nvda"], dias=10)
    assert database.existe_hallazgo(campana_id, "NVDA", "noticia", "https://ej.com/1") is False

    database.agregar_hallazgo(campana_id, "NVDA", "noticia", "Titulo", "https://ej.com/1", "Reuters", "https://ej.com/1")
    assert database.existe_hallazgo(campana_id, "NVDA", "noticia", "https://ej.com/1") is True

    # Distinta URL no es duplicado
    assert database.existe_hallazgo(campana_id, "NVDA", "noticia", "https://ej.com/2") is False


def test_dedupe_sentimiento_es_por_fecha_no_por_url():
    campana_id = database.crear_campana_research(["msft"], dias=10)
    clave_hoy = "stocktwits:2026-09-08"
    database.agregar_hallazgo(campana_id, "MSFT", "sentimiento", "60% bullish", "https://stocktwits.com/symbol/MSFT", "StockTwits", clave_hoy)
    # Misma clave (mismo dia) -> ya existe, aunque la URL sea siempre la misma
    assert database.existe_hallazgo(campana_id, "MSFT", "sentimiento", clave_hoy) is True
    # Otro dia -> no existe todavia
    assert database.existe_hallazgo(campana_id, "MSFT", "sentimiento", "stocktwits:2026-09-09") is False


def test_desactivar_campana_la_saca_de_activas():
    campana_id = database.crear_campana_research(["ko"], dias=5)
    ok = database.desactivar_campana_research(campana_id)
    assert ok is True
    ids_activas = [c[0] for c in database.obtener_campanas_activas()]
    assert campana_id not in ids_activas


def test_obtener_hallazgos_campana_devuelve_lo_guardado():
    campana_id = database.crear_campana_research(["pg"], dias=5)
    database.agregar_hallazgo(campana_id, "PG", "noticia", "Titulo", "https://ej.com/pg", "Reuters", "https://ej.com/pg")
    hallazgos = database.obtener_hallazgos_campana(campana_id)
    assert len(hallazgos) == 1
    assert hallazgos[0][0] == "PG"
