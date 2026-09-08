"""
research_campaigns.py — Campañas de research automático por ticker.

El usuario pide "seguime estos tickers por 30 días" (tool manage_research_campaign
en database.py) y, una vez por día — disparado por un job de telegram_bot.py,
NO por el chat — este módulo busca novedades en todas las fuentes disponibles
y las junta en un HTML local que se va actualizando.

Diseño explícitamente pedido por Mateo: "no quiero que levante toda la
información y la resuma, sino que mande el link". Así que este módulo solo
recolecta, dedupea contra lo ya guardado, y renderiza — no resume ni opina
sobre nada. La única excepción es el pulso de sentimiento social (StockTwits/
ApeWisdom), que no tiene un "artículo" al que linkear, así que se guarda como
una foto numérica del día en vez de un link a una noticia.
"""
from datetime import datetime

import brave_client
import global_search
import social_sentiment
import apewisdom_client
import market_data
from database import (
    DB_PATH,
    obtener_campanas_activas, marcar_corrida_campana, existe_hallazgo,
    agregar_hallazgo, obtener_hallazgos_campana, desactivar_campana_research,
)

CARPETA_RESEARCH = DB_PATH.parent / "research"


# ─── Búsqueda de novedades (una fuente por función, para poder fallar una sin tumbar las demás) ──

def _buscar_noticias(ticker: str) -> list:
    """Noticias en inglés (Brave) + de cualquier país (Google News/GDELT). Tipo 'noticia'."""
    hallazgos = []
    try:
        for it in brave_client.search_news(f"{ticker} stock", count=5):
            if it.get("url") and it.get("titulo"):
                hallazgos.append({
                    "tipo": "noticia", "titulo": it["titulo"], "url": it["url"],
                    "fuente": it.get("fuente") or "Brave Search", "clave_dedupe": it["url"]
                })
    except Exception:
        pass

    try:
        res = global_search.busqueda_global(query=f"{ticker} stock", count=5)
        if res.get("ok"):
            for it in res["data"]:
                if it.get("url") and it.get("titulo"):
                    hallazgos.append({
                        "tipo": "noticia", "titulo": it["titulo"], "url": it["url"],
                        "fuente": it.get("fuente") or "Google News", "clave_dedupe": it["url"]
                    })
    except Exception:
        pass

    return hallazgos


def _buscar_filings(ticker: str) -> list:
    """Filings 8-K recientes (eventos materiales: adquisiciones, cambios de guidance, etc). Tipo 'filing'."""
    hallazgos = []
    try:
        res = market_data.sec_get_filings(ticker, form_type="8-K", limit=3)
        if res.get("ok"):
            for f in res["data"]:
                if f.get("url"):
                    hallazgos.append({
                        "tipo": "filing", "titulo": f"Filing 8-K: {f.get('titulo', '') or ticker}",
                        "url": f["url"], "fuente": "SEC EDGAR", "clave_dedupe": f["url"]
                    })
    except Exception:
        pass
    return hallazgos


def _buscar_sentimiento(ticker: str) -> list:
    """
    Pulso social del día (StockTwits + ApeWisdom). Sin URL de artículo real,
    se guarda como una foto del día — dedupeada por fecha+fuente, no por URL
    (la URL de la página del ticker en esos sitios es siempre la misma).
    """
    hoy = datetime.now().strftime("%Y-%m-%d")
    hallazgos = []

    try:
        res = social_sentiment.stocktwits_sentiment(ticker)
        if res.get("ok") and res["data"].get("bullish_pct") is not None:
            d = res["data"]
            hallazgos.append({
                "tipo": "sentimiento",
                "titulo": f"StockTwits: {d['bullish_pct']}% bullish / {d['bearish_pct']}% bearish ({d['total_mensajes']} mensajes)",
                "url": f"https://stocktwits.com/symbol/{ticker}",
                "fuente": "StockTwits", "clave_dedupe": f"stocktwits:{hoy}"
            })
    except Exception:
        pass

    try:
        res = apewisdom_client.get_mentions(ticker)
        if res.get("ok") and res["data"].get("encontrado"):
            d = res["data"]
            hallazgos.append({
                "tipo": "sentimiento",
                "titulo": f"ApeWisdom: rank #{d['rank']} en menciones de Reddit ({d['tendencia']} vs ayer), {d['mentions']} menciones",
                "url": f"https://apewisdom.io/stocks/{ticker}/",
                "fuente": "ApeWisdom", "clave_dedupe": f"apewisdom:{hoy}"
            })
    except Exception:
        pass

    return hallazgos


def buscar_novedades_ticker(ticker: str) -> list:
    """Junta las 3 fuentes para un ticker. No dedupea acá — eso se hace contra la DB al guardar."""
    return _buscar_noticias(ticker) + _buscar_filings(ticker) + _buscar_sentimiento(ticker)


# ─── Lógica pura (fechas, HTML) — separada de la I/O para poder testearla ─────

def dias_transcurridos(fecha_inicio_iso: str, ahora: datetime = None) -> int:
    ahora = ahora or datetime.now()
    return (ahora - datetime.fromisoformat(fecha_inicio_iso)).days


def esta_finalizada(transcurridos: int, dias_totales: int) -> bool:
    return transcurridos >= dias_totales


def renderizar_html(campana_id: int, tickers_str: str, hallazgos: list) -> str:
    """
    Arma el HTML completo de la campaña a partir de la lista de hallazgos ya
    guardados (ticker, fecha, tipo, titulo, url, fuente). Función pura —no
    toca la DB ni el filesystem— para poder testearla con datos de mentira.
    """
    por_ticker = {}
    for ticker, fecha, tipo, titulo, url, fuente in hallazgos:
        por_ticker.setdefault(ticker, []).append((fecha, tipo, titulo, url, fuente))

    secciones = []
    for ticker in sorted(por_ticker.keys()):
        filas = "".join(
            f'<tr><td>{fecha[:10]}</td><td>{tipo}</td>'
            f'<td><a href="{url}" target="_blank" rel="noopener">{titulo}</a></td><td>{fuente}</td></tr>'
            for fecha, tipo, titulo, url, fuente in por_ticker[ticker]
        )
        secciones.append(
            f"<h2>{ticker}</h2><table><tr><th>Fecha</th><th>Tipo</th><th>Hallazgo</th><th>Fuente</th></tr>{filas}</table>"
        )

    cuerpo = "".join(secciones) if secciones else "<p>Todavía no hay hallazgos.</p>"

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<title>Campaña de research #{campana_id} — {tickers_str}</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
table {{ width: 100%; border-collapse: collapse; margin-bottom: 2rem; }}
th, td {{ text-align: left; padding: 0.5rem; border-bottom: 1px solid #ddd; font-size: 0.9rem; }}
th {{ background: #f5f5f5; }}
h1 {{ margin-bottom: 0.2rem; }}
h2 {{ margin-top: 2rem; }}
a {{ color: #0645ad; }}
</style></head>
<body>
<h1>Campaña de research #{campana_id}</h1>
<p>Tickers: {tickers_str} — actualizado {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
{cuerpo}
</body></html>"""


def generar_html_campana(campana_id: int, tickers_str: str) -> str:
    """Trae los hallazgos de la DB, renderiza el HTML, y lo escribe a disco. Devuelve la ruta."""
    hallazgos = obtener_hallazgos_campana(campana_id)
    html = renderizar_html(campana_id, tickers_str, hallazgos)

    CARPETA_RESEARCH.mkdir(parents=True, exist_ok=True)
    ruta = CARPETA_RESEARCH / f"campana_{campana_id}.html"
    ruta.write_text(html, encoding="utf-8")
    return str(ruta)


# ─── Job diario ────────────────────────────────────────────────────────────────

def ejecutar_campanas_diarias() -> list:
    """
    Corre una vez por día (job de telegram_bot.py). Para cada campaña activa:
    busca novedades de cada ticker, guarda solo lo que no estaba ya guardado,
    regenera el HTML, y si ya pasaron los días pedidos la marca inactiva.
    Devuelve un resumen por campaña para el mensaje de Telegram.
    """
    resumen = []
    ahora = datetime.now()

    for campana_id, tickers_str, fecha_inicio, dias_totales, _ultima_corrida in obtener_campanas_activas():
        tickers = [t.strip() for t in tickers_str.split(",") if t.strip()]
        nuevos_total = 0

        for ticker in tickers:
            for h in buscar_novedades_ticker(ticker):
                if existe_hallazgo(campana_id, ticker, h["tipo"], h["clave_dedupe"]):
                    continue
                agregar_hallazgo(campana_id, ticker, h["tipo"], h["titulo"], h["url"], h["fuente"], h["clave_dedupe"])
                nuevos_total += 1

        marcar_corrida_campana(campana_id, ahora.isoformat())
        ruta_html = generar_html_campana(campana_id, tickers_str)

        transcurridos = dias_transcurridos(fecha_inicio, ahora)
        finalizada = esta_finalizada(transcurridos, dias_totales)
        if finalizada:
            desactivar_campana_research(campana_id)

        resumen.append({
            "campana_id": campana_id, "tickers": tickers_str,
            "nuevos": nuevos_total, "archivo_html": ruta_html,
            "dias_transcurridos": transcurridos, "dias_totales": dias_totales,
            "finalizada": finalizada
        })

    return resumen
