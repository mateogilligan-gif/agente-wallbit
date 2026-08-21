"""
web_reader.py — Lector de páginas web completas.
Permite al agente entrar a una URL específica (sitio de una empresa, diario local,
artículo de noticias) y extraer el texto completo del contenido, no solo el
título/resumen que devuelve brave_search.

PROBLEMA QUE RESUELVE ESTE MÓDULO:
Muchos sitios de noticias modernos renderizan el contenido con JavaScript.
Si solo hacemos un request HTTP plano, a veces llega una página casi vacía
(el HTML crudo sin el artículo, que se arma recién en el navegador). Antes
esto fallaba en silencio: devolvía "texto extraído" pero era basura.

Ahora, si el intento directo trae muy poco texto, se usa automáticamente
Jina Reader (r.jina.ai) como respaldo — un servicio gratuito, sin API key,
que renderiza la página del lado del servidor (ejecuta el JavaScript) y
devuelve el contenido ya limpio. No requiere instalar un navegador headless.
"""
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

TAGS_A_ELIMINAR = ["script", "style", "nav", "footer", "header", "aside", "form", "noscript", "iframe"]

# Si el intento directo trae menos texto que esto, asumimos que la página
# es JS-heavy y probamos con Jina Reader como respaldo.
MIN_TEXTO_VALIDO = 250

JINA_READER_URL = "https://r.jina.ai/{url}"


def _fetch_directo(url: str, max_chars: int) -> dict:
    """Intento 1: request HTTP plano + BeautifulSoup. Rápido, pero falla en sitios JS-heavy."""
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

        contenedor = soup.find("article") or soup.body or soup
        parrafos = contenedor.find_all("p")
        texto = "\n".join(p.get_text(strip=True) for p in parrafos if len(p.get_text(strip=True)) > 40)

        if not texto:
            texto = contenedor.get_text(separator="\n", strip=True)

        if not texto:
            return {"ok": False, "error": "No se pudo extraer texto de la página"}

        texto = texto[:max_chars]

        return {
            "ok": True,
            "data": {"url": url, "titulo": titulo, "texto": texto, "truncado": len(texto) >= max_chars}
        }

    except requests.exceptions.Timeout:
        return {"ok": False, "error": "Timeout — la página tardó demasiado en responder"}
    except requests.exceptions.RequestException as e:
        return {"ok": False, "error": f"No se pudo acceder a la página: {str(e)}"}
    except Exception as e:
        return {"ok": False, "error": f"Error procesando la página: {str(e)}"}


def _fetch_via_jina(url: str, max_chars: int) -> dict:
    """Intento 2 (respaldo): Jina Reader renderiza la página con JS del lado del servidor."""
    try:
        jina_url = JINA_READER_URL.format(url=url)
        r = requests.get(jina_url, headers=HEADERS, timeout=20)
        r.raise_for_status()

        contenido = r.text.strip()
        if not contenido:
            return {"ok": False, "error": "Jina Reader no devolvió contenido"}

        titulo = ""
        texto = contenido
        if contenido.startswith("Title:"):
            titulo = contenido.split("\n", 1)[0].replace("Title:", "").strip()
        if "Markdown Content:" in contenido:
            texto = contenido.split("Markdown Content:", 1)[1].strip()

        texto = texto[:max_chars]
        return {
            "ok": True,
            "data": {"url": url, "titulo": titulo, "texto": texto, "truncado": len(texto) >= max_chars}
        }

    except requests.exceptions.Timeout:
        return {"ok": False, "error": "Timeout consultando Jina Reader"}
    except Exception as e:
        return {"ok": False, "error": f"Jina Reader falló: {str(e)}"}


def fetch_article_text(url: str, max_chars: int = 4000) -> dict:
    """
    Entra a una URL y devuelve el texto principal de la página. Prueba primero
    un request directo (rápido); si trae muy poco texto (típico de sitios que
    renderizan con JavaScript), usa Jina Reader como respaldo automático.
    """
    directo = _fetch_directo(url, max_chars)

    if directo["ok"] and len(directo["data"]["texto"]) >= MIN_TEXTO_VALIDO:
        directo["data"]["metodo"] = "directo"
        return directo

    # El intento directo falló o trajo muy poco texto — probar con Jina Reader
    via_jina = _fetch_via_jina(url, max_chars)
    if via_jina["ok"] and len(via_jina["data"]["texto"]) >= MIN_TEXTO_VALIDO:
        via_jina["data"]["metodo"] = "jina_reader (fallback JS)"
        return via_jina

    # Ninguno de los dos trajo suficiente texto: devolver lo mejor que haya
    if directo["ok"]:
        directo["data"]["metodo"] = "directo (posible contenido incompleto)"
        return directo
    if via_jina["ok"]:
        via_jina["data"]["metodo"] = "jina_reader (posible contenido incompleto)"
        return via_jina

    return {"ok": False, "error": f"No se pudo leer la página ni directo ni con Jina Reader. Error directo: {directo.get('error')}"}
