"""
social_sentiment.py — Sentimiento social especializado en trading (StockTwits).

Evaluamos usar la API de X/Twitter para esto y la descartamos: desde 2026
X cobra por post leído (pay-per-use, sin tier gratis para developers nuevos)
y el contenido tiene muchísimo ruido (bots, pump groups) sin ningún filtro
de calidad.

StockTwits es mejor fit para este caso: es gratis, sin API key, 100%
financiera (mucho menos ruido), y cada mensaje ya viene etiquetado
Bullish/Bearish por el propio usuario que lo escribió — no hace falta
inventar un análisis de sentimiento propio.

Nota: usa el endpoint público de StockTwits, que no tiene garantía de
disponibilidad (no es una API oficial con SLA). Si StockTwits cambia su
política de acceso, esta función puede empezar a fallar — el error queda
manejado con un mensaje claro en ese caso.
"""
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json"
}

STOCKTWITS_URL = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"


def stocktwits_sentiment(ticker: str, limit: int = 30) -> dict:
    """
    Trae los últimos mensajes de StockTwits sobre un ticker y calcula
    el % de sentimiento Bullish/Bearish entre los mensajes etiquetados.
    """
    ticker = ticker.strip().upper()
    try:
        url = STOCKTWITS_URL.format(ticker=ticker)
        r = requests.get(url, headers=HEADERS, timeout=12)

        if r.status_code == 404:
            return {"ok": False, "error": f"Ticker {ticker} no encontrado en StockTwits"}
        if r.status_code != 200:
            return {"ok": False, "error": f"StockTwits devolvió status {r.status_code} (puede haber cambiado su acceso público)"}

        data = r.json()
        mensajes = data.get("messages", [])[:limit]

        if not mensajes:
            return {"ok": True, "data": {"ticker": ticker, "total_mensajes": 0, "nota": "Sin actividad reciente en StockTwits"}}

        bullish = 0
        bearish = 0
        sin_tag = 0
        recientes = []

        for m in mensajes:
            sentimiento = None
            entities = m.get("entities") or {}
            sent_obj = entities.get("sentiment")
            if sent_obj:
                sentimiento = sent_obj.get("basic")

            if sentimiento == "Bullish":
                bullish += 1
            elif sentimiento == "Bearish":
                bearish += 1
            else:
                sin_tag += 1

            if len(recientes) < 8:
                recientes.append({
                    "usuario": m.get("user", {}).get("username", ""),
                    "texto": (m.get("body") or "")[:200],
                    "sentimiento": sentimiento or "sin etiquetar",
                    "fecha": m.get("created_at", "")
                })

        total_tagged = bullish + bearish
        bullish_pct = round(bullish / total_tagged * 100, 1) if total_tagged else None
        bearish_pct = round(bearish / total_tagged * 100, 1) if total_tagged else None

        return {
            "ok": True,
            "data": {
                "ticker": ticker,
                "total_mensajes": len(mensajes),
                "bullish": bullish,
                "bearish": bearish,
                "sin_etiquetar": sin_tag,
                "bullish_pct": bullish_pct,
                "bearish_pct": bearish_pct,
                "mensajes_recientes": recientes
            }
        }

    except requests.exceptions.Timeout:
        return {"ok": False, "error": "Timeout consultando StockTwits"}
    except Exception as e:
        return {"ok": False, "error": f"Error consultando StockTwits: {str(e)}"}
