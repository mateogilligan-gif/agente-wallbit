"""
web_reader.py — Lector de páginas web completas.
Permite al agente entrar a una URL específica (sitio de una empresa, diario local,
artículo de noticias) y extraer el texto completo del contenido, no solo el
título/resumen que devuelve brave_search.
"""
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

TAGS_A_ELIMINAR = ["script", "style", "nav", "footer", "header", "aside", "form", "noscript", "iframe"]


def fetch_article_text(url: str, max_chars: int = 4000) -> dict:
    """
    Entra a una URL y devuelve el texto principal de la página (artículo, nota,
    sección de noticias de una empresa, etc.), limpio de scripts/menús/publicidad.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {
            "ok": False,
            "error": "Falta instalar beautifulsoup4. Correr: pip install beautifulsoup4 lxml --break-system-packages"
        }

    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")

        for tag_name in TAGS_A_ELIMINAR:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        titulo = soup.title.string.strip() if soup.title and soup.title.string else ""

        # Priorizar párrafos dentro de <article> si existe, sino todo el body
        contenedor = soup.find("article") or soup.body or soup
        parrafos = contenedor.find_all("p")
        texto = "\n".join(p.get_text(strip=True) for p in parrafos if len(p.get_text(strip=True)) > 40)

        if not texto:
            # Fallback: todo el texto plano de la página
            texto = contenedor.get_text(separator="\n", strip=True)

        if not texto:
            return {"ok": False, "error": "No se pudo extraer texto de la página"}

        texto = texto[:max_chars]

        return {
            "ok": True,
            "data": {
                "url": url,
                "titulo": titulo,
                "texto": texto,
                "truncado": len(texto) >= max_chars
            }
        }

    except requests.exceptions.Timeout:
        return {"ok": False, "error": "Timeout — la página tardó demasiado en responder"}
    except requests.exceptions.RequestException as e:
        return {"ok": False, "error": f"No se pudo acceder a la página: {str(e)}"}
    except Exception as e:
        return {"ok": False, "error": f"Error procesando la página: {str(e)}"}
