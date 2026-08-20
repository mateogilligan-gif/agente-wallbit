"""
global_search.py — Motor de búsqueda de noticias globales.

Combina dos fuentes gratuitas y sin API key para encontrar prensa de
CUALQUIER país del mundo (no solo medios en inglés o de EEUU):

- Google News RSS: permite filtrar por país + idioma con códigos ISO
  (ej: pais="AU" idioma="en" para Australia, pais="DE" idioma="de" para Alemania).
- GDELT Project: base de datos global de noticias, indexa medios de
  prácticamente todos los países, se usa como refuerzo/fallback.

Uso típico: busqueda_global("Empresa XYZ contrato nuevo", pais="AU") y después
web_reader.fetch_article_text(url) sobre el resultado más relevante para sacar
el texto completo del artículo.
"""
import requests
import urllib.parse

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}


def google_news_search(query: str, pais: str = None, idioma: str = None, count: int = 10) -> dict:
    """
    Busca en Google News RSS, filtrando por país (código ISO ej AU, DE, AR, JP)
    e idioma (código ISO ej en, es, de, ja). Sin API key.
    """
    try:
        from bs4 import BeautifulSoup

        idioma = (idioma or "en").lower()
        pais = (pais or "US").upper()
        ceid = f"{pais}:{idioma}"
        q = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={q}&hl={idioma}&gl={pais}&ceid={ceid}"

        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()

        soup = BeautifulSoup(r.content, "xml")
        items = soup.find_all("item")[:count]

        resultados = []
        for it in items:
            titulo = it.title.get_text(strip=True) if it.title else ""
            link = it.link.get_text(strip=True) if it.link else ""
            fecha = it.pubDate.get_text(strip=True) if it.pubDate else ""
            fuente_tag = it.find("source")
            fuente = fuente_tag.get_text(strip=True) if fuente_tag else ""
            resultados.append({
                "titulo": titulo, "url": link, "fuente": fuente,
                "fecha": fecha, "pais": pais, "idioma": idioma
            })

        return {"ok": True, "data": resultados}
    except ImportError:
        return {"ok": False, "error": "Falta beautifulsoup4/lxml instalado"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def gdelt_search(query: str, count: int = 10, dias: int = 30) -> dict:
    """
    Busca en GDELT (base de datos global de noticias, cubre prensa de
    prácticamente todos los países). Sin API key.
    """
    try:
        q = urllib.parse.quote(query)
        url = (
            f"https://api.gdeltproject.org/api/v2/doc/doc"
            f"?query={q}&mode=ArtList&maxrecords={count}&format=json"
            f"&sort=DateDesc&timespan={dias}d"
        )
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        articulos = data.get("articles", [])
        resultados = [{
            "titulo": a.get("title", ""),
            "url": a.get("url", ""),
            "fuente": a.get("domain", ""),
            "fecha": a.get("seendate", ""),
            "pais": a.get("sourcecountry", ""),
            "idioma": a.get("language", "")
        } for a in articulos]
        return {"ok": True, "data": resultados}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def busqueda_global(query: str, pais: str = None, idioma: str = None, count: int = 10) -> dict:
    """
    Motor unificado: prueba Google News RSS primero (mejor targeting por país/idioma),
    y completa con GDELT si hay pocos resultados. Dedupea por URL.
    """
    resultados = []
    vistos = set()

    g_news = google_news_search(query, pais=pais, idioma=idioma, count=count)
    if g_news["ok"]:
        for item in g_news["data"]:
            if item["url"] and item["url"] not in vistos:
                vistos.add(item["url"])
                item["motor"] = "google_news"
                resultados.append(item)

    if len(resultados) < 5:
        gdelt = gdelt_search(query, count=count)
        if gdelt["ok"]:
            for item in gdelt["data"]:
                if item["url"] and item["url"] not in vistos:
                    vistos.add(item["url"])
                    item["motor"] = "gdelt"
                    resultados.append(item)

    if not resultados:
        return {"ok": False, "error": "Sin resultados en Google News ni GDELT para esta búsqueda"}

    return {"ok": True, "data": resultados[:count]}
