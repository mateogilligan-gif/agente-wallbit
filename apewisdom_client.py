"""
apewisdom_client.py — Volumen de menciones de tickers en Reddit (y 4chan),
vía ApeWisdom (apewisdom.io), sin necesidad de credenciales propias.

Por qué existe: pedimos acceso a la Data API de Reddit para reddit_client.py
y Reddit lo rechazó. ApeWisdom resuelve un caso más chico pero sin ningún
trámite ni cuenta: cuántas veces se mencionó un ticker en las mismas
subreddits (wallstreetbets, stocks, investing, etc.) y si esa mención viene
subiendo o bajando de ranking vs ayer.

IMPORTANTE — esto NO es lo mismo que reddit_sentiment: no da el texto de
los posts ni un % real de bullish/bearish, solo volumen de menciones y
upvotes totales. Complementa a sentimiento_social (StockTwits, que sí trae
un sentimiento etiquetado), no lo reemplaza.

API pública, sin key: https://apewisdom.io/api/v1.0/filter/{filtro}/page/{n}
"""
import time
import requests

from tool_registry import tool

APEWISDOM_URL = "https://apewisdom.io/api/v1.0/filter/{filtro}/page/{pagina}"
FILTRO_DEFAULT = "all-stocks"
CACHE_SEGUNDOS = 900  # ApeWisdom actualiza cada ~30 min, no tiene sentido pegarle más seguido

_cache = {"filtro": None, "datos": None, "expira": 0}


def _traer_todas_las_paginas(filtro: str = FILTRO_DEFAULT, max_paginas: int = 10) -> list:
    """Trae todas las páginas del filtro (100 tickers c/u) y las junta. Cachea 15 min."""
    if _cache["filtro"] == filtro and time.time() < _cache["expira"]:
        return _cache["datos"]

    resultados = []
    pagina = 1
    while pagina <= max_paginas:
        r = requests.get(APEWISDOM_URL.format(filtro=filtro, pagina=pagina), timeout=12)
        r.raise_for_status()
        data = r.json()
        resultados.extend(data.get("results", []))
        if pagina >= data.get("pages", 1):
            break
        pagina += 1

    _cache["filtro"] = filtro
    _cache["datos"] = resultados
    _cache["expira"] = time.time() + CACHE_SEGUNDOS
    return resultados


def _buscar_ticker(resultados: list, ticker: str) -> dict:
    """Lógica PURA: busca un ticker dentro de la lista ya traída de ApeWisdom."""
    ticker = ticker.strip().upper()
    for item in resultados:
        if item.get("ticker", "").upper() == ticker:
            return item
    return None


def tendencia_ranking(rank: int, rank_24h_ago: int) -> str:
    """
    Lógica PURA: en ApeWisdom el ranking #1 es el MÁS mencionado, así que
    un número de ranking más bajo hoy que ayer significa que subió de moda.
    """
    if rank_24h_ago is None:
        return "sin dato de ayer"
    if rank < rank_24h_ago:
        return "subiendo"
    if rank > rank_24h_ago:
        return "bajando"
    return "estable"


def get_mentions(ticker: str, filtro: str = FILTRO_DEFAULT) -> dict:
    """Menciones y ranking de un ticker en Reddit, sin necesidad de credenciales propias."""
    ticker = ticker.strip().upper()
    try:
        resultados = _traer_todas_las_paginas(filtro)
        item = _buscar_ticker(resultados, ticker)
        if not item:
            return {
                "ok": True,
                "data": {
                    "ticker": ticker, "encontrado": False,
                    "nota": "No está entre los tickers con mayor volumen de menciones ahora mismo"
                }
            }

        rank = int(item["rank"]) if item.get("rank") not in (None, "") else None
        rank_24h_ago = int(item["rank_24h_ago"]) if item.get("rank_24h_ago") not in (None, "") else None

        return {
            "ok": True,
            "data": {
                "ticker": item.get("ticker", ticker),
                "nombre": item.get("name", ""),
                "encontrado": True,
                "rank": rank,
                "rank_24h_ago": rank_24h_ago,
                "tendencia": tendencia_ranking(rank, rank_24h_ago) if rank is not None else "sin dato",
                "mentions": int(item["mentions"]) if item.get("mentions") not in (None, "") else 0,
                "mentions_24h_ago": int(item["mentions_24h_ago"]) if item.get("mentions_24h_ago") not in (None, "") else 0,
                "upvotes": int(item["upvotes"]) if item.get("upvotes") not in (None, "") else 0,
            }
        }
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "Timeout consultando ApeWisdom"}
    except Exception as e:
        return {"ok": False, "error": f"Error consultando ApeWisdom: {str(e)}"}


# ─── Tool (Anthropic Tool Use) ──────────────────────────────────────────────────

@tool(
    "reddit_mentions_trending",
    "Volumen de menciones de un ticker en Reddit (wallstreetbets, stocks, investing, etc.) vía ApeWisdom — gratis, sin credenciales propias, funciona ya mismo. Da RANKING y VOLUMEN de menciones (¿está de moda?, ¿subiendo o bajando vs ayer?), no el texto de los posts ni un % bullish/bearish real. Complementa a sentimiento_social (StockTwits, que sí trae sentimiento etiquetado). Usar cuando pregunten 'está de moda en reddit', 'cuánto se habla de X', o similar.",
    {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}
)
def _tool_reddit_mentions_trending(inputs: dict):
    return get_mentions(inputs["ticker"])
