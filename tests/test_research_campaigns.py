"""Tests de lógica pura en research_campaigns.py. Sin red, sin DB."""
import sys
import os
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-no-real")

import research_campaigns


def test_dias_transcurridos_cero_el_mismo_dia():
    ahora = datetime.now()
    assert research_campaigns.dias_transcurridos(ahora.isoformat(), ahora=ahora) == 0


def test_dias_transcurridos_cuenta_dias_completos():
    ahora = datetime.now()
    hace_5_dias = (ahora - timedelta(days=5)).isoformat()
    assert research_campaigns.dias_transcurridos(hace_5_dias, ahora=ahora) == 5


def test_esta_finalizada_true_cuando_se_cumplieron_los_dias():
    assert research_campaigns.esta_finalizada(30, 30) is True
    assert research_campaigns.esta_finalizada(31, 30) is True


def test_esta_finalizada_false_si_todavia_no_se_cumplen():
    assert research_campaigns.esta_finalizada(29, 30) is False


def test_renderizar_html_agrupa_por_ticker_y_linkea():
    hallazgos = [
        ("AAPL", "2026-09-08T10:00:00", "noticia", "Apple lanza algo", "https://ejemplo.com/apple", "Reuters"),
        ("AAPL", "2026-09-07T10:00:00", "sentimiento", "StockTwits: 60% bullish", "https://stocktwits.com/symbol/AAPL", "StockTwits"),
        ("TSLA", "2026-09-08T09:00:00", "filing", "Filing 8-K: evento", "https://sec.gov/algo", "SEC EDGAR"),
    ]
    html = research_campaigns.renderizar_html(1, "AAPL,TSLA", hallazgos)

    assert "AAPL" in html and "TSLA" in html
    assert 'href="https://ejemplo.com/apple"' in html
    assert "Apple lanza algo" in html
    assert 'href="https://sec.gov/algo"' in html


def test_renderizar_html_sin_hallazgos_no_rompe():
    html = research_campaigns.renderizar_html(2, "NVDA", [])
    assert "Todavía no hay hallazgos" in html
    assert "NVDA" in html
