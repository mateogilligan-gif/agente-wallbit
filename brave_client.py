import requests
import os
from datetime import datetime

from tool_registry import tool

BRAVE_BASE_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_NEWS_URL = "https://api.search.brave.com/res/v1/news/search"
_cache = {}

def _is_cached(key, max_minutes=30):
    if key not in _cache:
        return False
    return (datetime.now() - _cache[key]["timestamp"]).seconds / 60 < max_minutes

def search_web(query, count=5):
    key = f"web:{query.lower()}"
    if _is_cached(key):
        return _cache[key]["data"]
    headers = {"Accept": "application/json", "Accept-Encoding": "gzip", "X-Subscription-Token": os.getenv("BRAVE_API_KEY")}
    try:
        r = requests.get(BRAVE_BASE_URL, headers=headers, params={"q": query, "count": count, "search_lang": "en"}, timeout=10)
        r.raise_for_status()
        results = [{"titulo": i.get("title",""), "url": i.get("url",""), "descripcion": i.get("description","")} for i in r.json().get("web",{}).get("results",[])]
        _cache[key] = {"data": results, "timestamp": datetime.now()}
        return results
    except Exception as e:
        return [{"titulo": "Error de búsqueda", "url": "", "descripcion": str(e)}]

def search_news(query, count=5):
    key = f"news:{query.lower()}"
    if _is_cached(key):
        return _cache[key]["data"]
    headers = {"Accept": "application/json", "Accept-Encoding": "gzip", "X-Subscription-Token": os.getenv("BRAVE_API_KEY")}
    try:
        r = requests.get(BRAVE_NEWS_URL, headers=headers, params={"q": query, "count": count, "search_lang": "en", "freshness": "pd"}, timeout=10)
        r.raise_for_status()
        results = [{"titulo": i.get("title",""), "url": i.get("url",""), "fuente": i.get("source",{}).get("name",""), "fecha": i.get("age",""), "descripcion": i.get("description","")} for i in r.json().get("results",[])]
        _cache[key] = {"data": results, "timestamp": datetime.now()}
        return results
    except Exception as e:
        return [{"titulo": "Error", "url": "", "fuente": "", "fecha": "", "descripcion": str(e)}]

def search_ticker_news(ticker):
    return search_news(f"{ticker} stock news Bloomberg Reuters CNBC", count=3)

def search_market_overview():
    return search_news("stock market today premarket S&P 500 Nasdaq", count=5)

def search_economic_calendar():
    return search_web("economic calendar today Fed CPI jobs report", count=3)

def clear_cache():
    _cache.clear()


# ─── Tool (Anthropic Tool Use) ──────────────────────────────────────────────────

@tool(
    "brave_search",
    "Busca noticias financieras en tiempo real.",
    {"type": "object", "properties": {"query": {"type": "string"}, "tipo": {"type": "string", "enum": ["web", "news"]}}, "required": ["query"]}
)
def _tool_brave_search(inputs: dict):
    tipo = inputs.get("tipo", "news")
    query = inputs["query"]
    if tipo == "news":
        items = search_news(query, count=5)
    else:
        items = search_web(query, count=5)
    if items:
        return {"ok": True, "data": items}
    else:
        return {"ok": False, "error": "Sin resultados"}
