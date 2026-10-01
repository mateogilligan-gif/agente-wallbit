"""
fmp_client.py — Cliente opcional de Financial Modeling Prep (FMP), plan Starter.

Wallbit no tiene forma de encontrar empresas por sector/market cap (solo
valida tickers que el usuario ya conoce, ver market_data.screener_filtrar) y
las noticias por ticker vía brave_client son una búsqueda web genérica, con
ruido. FMP resuelve las dos cosas con datos estructurados, pero es un
servicio pago (~USD 19-22/mes el plan Starter) — por eso convive como un
MODO alternativo al gratis (Brave), elegido por el usuario y guardado en
config (clave MODO_DATOS_EMPRESA), nunca activado solo.

yfinance sigue siendo la única fuente de fundamentals/precios/histórico —
FMP acá NO los reemplaza en nada, solo cubre noticias por ticker y el
screener por sector/industria/market cap.

Verificación de endpoints (sin API key real, la prueba real queda pendiente
para cuando Mateo se suscriba):
- Auth: query param apikey, base https://financialmodelingprep.com/stable/.
- Confirmado EN VIVO contra la API real: cualquier ruta (incluida una
  inventada a propósito para probar) devuelve HTTP 401 con
  {"Error Message": "Invalid API KEY..."} si la key es inválida — FMP valida
  la key ANTES de resolver la ruta, así que no hay forma de confirmar por
  HTTP si una ruta puntual existe sin una key real. Por eso el parser mira
  la FORMA del error ("Error Message" en el JSON, o status 401/402/403), no
  un mensaje exacto — eso cubre tanto key inválida como key sin acceso al
  plan de un endpoint puntual.
- FMP_NEWS_PATH: /stable/news/stock con el parámetro "symbols". Confirmado
  en la página oficial de la doc "Search Stock News API"
  (site.financialmodelingprep.com/developer/docs/stable/search-stock-news),
  cuyo ejemplo de endpoint es literalmente
  https://financialmodelingprep.com/stable/news/stock?symbols=AAPL. Ojo:
  "search-stock-news" es el nombre de la PÁGINA de la doc, no la ruta de la
  API — no confundirlas. (/stable/news/stock-latest es el feed general sin
  filtro por ticker, no sirve para esto.) La prueba en vivo sin key no
  sirve para desambiguar rutas: FMP devuelve 401 "Invalid API KEY" para
  cualquier ruta, exista o no.
- FMP_SCREENER_PATH: /stable/company-screener, confirmado con ejemplo real
  de respuesta en la doc oficial (campos symbol, companyName, marketCap,
  sector, industry, country, exchange, beta, price, volume).
- Plan requerido: las noticias están confirmadas en el plan Starter. El
  company screener podría requerir un plan superior (Premium) — no se pudo
  confirmar con certeza. No bloquea nada: si la key no tiene acceso, cae en
  el mismo manejo de "plan insuficiente" de abajo.
"""
import os
import json
import requests
from datetime import datetime
from typing import Optional

from tool_registry import tool

FMP_BASE_URL = "https://financialmodelingprep.com/stable"
FMP_NEWS_PATH = "/news/stock"
FMP_NEWS_TICKER_PARAM = "symbols"
FMP_SCREENER_PATH = "/company-screener"

MODOS_VALIDOS = ("gratis", "fmp_pago")

MAX_LIMITE_NOTICIAS = 10
DEFAULT_LIMITE_NOTICIAS = 5
MAX_LIMITE_SCREENER = 25
DEFAULT_LIMITE_SCREENER = 10

AVISO_MODO_NO_CONFIGURADO = (
    "MODO_DATOS_EMPRESA no está configurado todavía (usando 'gratis'/Brave por default). "
    "Preguntale a Mateo UNA sola vez qué modo quiere para datos de empresa, explicando en una línea "
    "la diferencia: 'gratis' usa búsqueda web (Brave, con más ruido); 'fmp_pago' usa Financial Modeling Prep "
    "(noticias estructuradas y un screener real por sector/market cap, plan Starter confirmado en ~USD 19-22/mes "
    "para las noticias — el screener podría necesitar un plan superior, no confirmado). "
    "Guardá la respuesta con configurar_modo_datos_empresa y no vuelvas a preguntar."
)

_cache = {}


def _is_cached(key, max_minutes=30):
    if key not in _cache:
        return False
    return (datetime.now() - _cache[key]["timestamp"]).seconds / 60 < max_minutes


def clear_cache():
    _cache.clear()


# ─── Lógica pura (sin red, sin DB) ─────────────────────────────────────────────

def normalizar_ticker(ticker) -> str:
    """Mayúsculas, sin espacios. Tira ValueError si viene vacío o no es texto."""
    if not ticker or not isinstance(ticker, str) or not ticker.strip():
        raise ValueError("El ticker no puede estar vacío")
    return ticker.strip().upper().replace(" ", "")


def resolver_modo(valor_guardado: Optional[str]) -> tuple:
    """
    Decide qué modo usar dado lo que haya en config (MODO_DATOS_EMPRESA).
    Devuelve (modo, modo_no_configurado). Si no hay nada guardado, o lo
    guardado no es un modo válido (no debería pasar, configurar_modo_datos_empresa
    valida antes de guardar, pero por las dudas), cae a 'gratis' marcando
    modo_no_configurado=True para que la tool avise que hay que preguntar.
    """
    if valor_guardado not in MODOS_VALIDOS:
        return "gratis", True
    return valor_guardado, False


def validar_modo(modo) -> Optional[str]:
    """Devuelve el mensaje de error si el modo no es válido, o None si está bien."""
    if modo not in MODOS_VALIDOS:
        return f"Modo inválido: '{modo}' (tiene que ser 'gratis' o 'fmp_pago')"
    return None


def validar_params_screener(sector=None, industria=None, market_cap_min=None, market_cap_max=None, pais=None, limite=None) -> Optional[str]:
    """
    Valida los filtros del screener ANTES de llamar a la API. Devuelve el
    mensaje de error, o None si está todo bien. No se admite pedir "todo el
    mercado": al menos un filtro es obligatorio.
    """
    if not any([sector, industria, market_cap_min is not None, market_cap_max is not None, pais]):
        return "El screener necesita al menos un filtro (sector, industria, market_cap_min, market_cap_max o país) — no se puede pedir 'todo el mercado'."

    for nombre, valor in (("market_cap_min", market_cap_min), ("market_cap_max", market_cap_max)):
        if valor is not None:
            if not isinstance(valor, (int, float)) or isinstance(valor, bool):
                return f"{nombre} tiene que ser un número"
            if valor < 0:
                return f"{nombre} no puede ser negativo"

    if market_cap_min is not None and market_cap_max is not None and market_cap_min > market_cap_max:
        return f"market_cap_min (${market_cap_min}) no puede ser mayor a market_cap_max (${market_cap_max})"

    if limite is not None and (not isinstance(limite, (int, float)) or isinstance(limite, bool) or limite <= 0):
        return "limite tiene que ser un número mayor a 0"

    return None


def parse_noticias_fmp(raw: list) -> list:
    """
    Normaliza la respuesta de /news/stock al contrato {titulo, url,
    fuente, fecha} — el mismo shape que devuelve brave_client, para que al
    resto del bot le dé igual qué fuente respondió. Campos según la doc
    oficial de FMP (title, url, site, publishedDate) — si algún campo no
    viene, se devuelve vacío en vez de romper.
    """
    if not isinstance(raw, list):
        return []
    return [
        {
            "titulo": item.get("title", "") or "",
            "url": item.get("url", "") or "",
            "fuente": item.get("site", "") or "",
            "fecha": item.get("publishedDate", "") or "",
        }
        for item in raw
        if isinstance(item, dict)
    ]


def parse_screener_fmp(raw: list) -> list:
    """
    Normaliza la respuesta de /company-screener al contrato {ticker, nombre,
    sector, industria, market_cap, pais}. Campos según la doc oficial de FMP
    (symbol, companyName, sector, industry, marketCap, country) — si algún
    campo no viene, se devuelve None/vacío en vez de romper.
    """
    if not isinstance(raw, list):
        return []
    return [
        {
            "ticker": item.get("symbol", "") or "",
            "nombre": item.get("companyName", "") or "",
            "sector": item.get("sector"),
            "industria": item.get("industry"),
            "market_cap": item.get("marketCap"),
            "pais": item.get("country"),
        }
        for item in raw
        if isinstance(item, dict)
    ]


def _normalizar_brave(items: list) -> list:
    """Mismo contrato {titulo, url, fuente, fecha}, pero desde brave_client (ya viene casi así)."""
    if not isinstance(items, list):
        return []
    return [
        {
            "titulo": item.get("titulo", "") or "",
            "url": item.get("url", "") or "",
            "fuente": item.get("fuente", "") or "",
            "fecha": item.get("fecha", "") or "",
        }
        for item in items
        if isinstance(item, dict)
    ]


def _es_error_de_plan_o_auth(status_code, body) -> Optional[str]:
    """
    Detecta si la respuesta de FMP es un error de key inválida o de plan sin
    acceso a ese endpoint (confirmado en vivo: 401 + {"Error Message": "..."}
    para key inválida; para "plan sin acceso" FMP usa el mismo shape con
    401/402/403 según el endpoint). Devuelve el mensaje de error de FMP, o
    None si no es ese tipo de error.
    """
    if isinstance(body, dict) and "Error Message" in body:
        return str(body["Error Message"])
    if status_code in (401, 402, 403):
        return f"FMP respondió {status_code} (clave inválida o plan sin acceso a este endpoint)"
    return None


# ─── I/O: la única función que pega contra la red ──────────────────────────────

def _fmp_get(path: str, params: dict, timeout: int = 10) -> tuple:
    """
    Única función que llama a la API real de FMP. Devuelve (ok, data_o_None, error_o_None).
    Nunca tira una excepción sin manejar: timeout, error de red, JSON inválido,
    error de plan/auth y lista vacía quedan todos cubiertos acá.
    Cachea 30 min SOLO las respuestas exitosas (un error de key/plan no debería
    quedar pegado 30 minutos si Mateo corrige la key en el medio).
    """
    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        return False, None, "Falta FMP_API_KEY en el entorno"

    cache_key = f"{path}:{json.dumps(params, sort_keys=True)}"
    if _is_cached(cache_key):
        return True, _cache[cache_key]["data"], None

    query = dict(params)
    query["apikey"] = api_key

    try:
        r = requests.get(f"{FMP_BASE_URL}{path}", params=query, timeout=timeout)
    except requests.exceptions.RequestException as e:
        return False, None, f"Error de red/timeout llamando a FMP: {e}"

    try:
        body = r.json()
    except ValueError:
        return False, None, f"Respuesta inválida (no-JSON) de FMP (status {r.status_code})"

    error_plan = _es_error_de_plan_o_auth(r.status_code, body)
    if error_plan:
        return False, None, error_plan

    if r.status_code >= 400:
        return False, None, f"FMP respondió {r.status_code}"

    if not isinstance(body, list):
        return False, None, "Respuesta inesperada de FMP (se esperaba una lista)"

    _cache[cache_key] = {"data": body, "timestamp": datetime.now()}
    return True, body, None


def obtener_noticias_fmp(ticker: str, limite: int) -> tuple:
    """(ok, lista_normalizada_o_None, error_o_None) de noticias por ticker vía FMP."""
    ok, body, error = _fmp_get(FMP_NEWS_PATH, {FMP_NEWS_TICKER_PARAM: ticker, "limit": limite})
    if not ok:
        return False, None, error
    return True, parse_noticias_fmp(body)[:limite], None


def obtener_screener_fmp(params: dict, limite: int) -> tuple:
    """(ok, lista_normalizada_o_None, error_o_None) del company screener vía FMP."""
    ok, body, error = _fmp_get(FMP_SCREENER_PATH, params)
    if not ok:
        return False, None, error
    return True, parse_screener_fmp(body)[:limite], None


# ─── Tools (Anthropic Tool Use) ─────────────────────────────────────────────────

def _empaquetar_noticias(items: list, ticker: str, fuente_datos: str, modo_no_configurado: bool, aviso: Optional[str] = None) -> dict:
    data = {"noticias": items, "fuente_datos": fuente_datos}
    if not items:
        data["mensaje"] = f"Sin noticias recientes para {ticker}"
    if modo_no_configurado:
        data["modo_no_configurado"] = True
        aviso = aviso or AVISO_MODO_NO_CONFIGURADO
    if aviso:
        data["aviso"] = aviso
    return {"ok": True, "data": data}


@tool(
    "noticias_empresa",
    "Noticias recientes de UN ticker puntual. Usar esta tool (no brave_search directo) para noticias de una empresa específica — "
    "internamente usa FMP (datos estructurados) o Brave (búsqueda web) según el modo configurado (MODO_DATOS_EMPRESA). "
    "Si la respuesta trae 'modo_no_configurado': true o un campo 'aviso', seguir esa instrucción (preguntarle al usuario qué modo prefiere).",
    {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Ticker de la empresa, ej 'AAPL'"},
            "limite": {"type": "integer", "description": f"Máximo de noticias a devolver (default {DEFAULT_LIMITE_NOTICIAS}, tope {MAX_LIMITE_NOTICIAS})"}
        },
        "required": ["ticker"]
    }
)
def _tool_noticias_empresa(inputs: dict):
    from database import obtener_config  # import diferido: evita ciclo con database.py
    import brave_client

    try:
        ticker = normalizar_ticker(inputs.get("ticker"))
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    limite = inputs.get("limite") or DEFAULT_LIMITE_NOTICIAS
    if not isinstance(limite, (int, float)) or isinstance(limite, bool) or limite <= 0:
        return {"ok": False, "error": "limite tiene que ser un número mayor a 0"}
    limite = min(int(limite), MAX_LIMITE_NOTICIAS)

    modo, no_configurado = resolver_modo(obtener_config("MODO_DATOS_EMPRESA"))

    if modo == "fmp_pago":
        if not os.getenv("FMP_API_KEY"):
            items = _normalizar_brave(brave_client.search_ticker_news(ticker))[:limite]
            return _empaquetar_noticias(
                items, ticker, "brave", no_configurado,
                aviso="Estás en modo pago (fmp_pago) pero no hay FMP_API_KEY cargada en el entorno — usando Brave como fallback. Cargá FMP_API_KEY en config.env para usar FMP."
            )

        ok, items, error = obtener_noticias_fmp(ticker, limite)
        if not ok:
            items_fallback = _normalizar_brave(brave_client.search_ticker_news(ticker))[:limite]
            return _empaquetar_noticias(
                items_fallback, ticker, "brave", no_configurado,
                aviso=f"Estás en modo pago (fmp_pago) pero FMP falló (plan sin acceso, key inválida, o error de red) — usando Brave como fallback. Detalle: {error}"
            )
        return _empaquetar_noticias(items, ticker, "fmp", no_configurado)

    items = _normalizar_brave(brave_client.search_ticker_news(ticker))[:limite]
    return _empaquetar_noticias(items, ticker, "brave", no_configurado)


@tool(
    "screener_empresas",
    "Busca empresas por sector/industria/market cap/país (company screener real, NO una lista de tickers dada por el usuario). "
    "Solo funciona en modo fmp_pago — en modo gratis devuelve ok:false con una alternativa. "
    f"Pedir al menos un filtro. Tope de resultados: {MAX_LIMITE_SCREENER} (default {DEFAULT_LIMITE_SCREENER}).",
    {
        "type": "object",
        "properties": {
            "sector": {"type": "string", "description": "Ej 'Technology', 'Healthcare', 'Energy'"},
            "industria": {"type": "string", "description": "Ej 'Software', 'Banks', 'Semiconductors'"},
            "market_cap_min": {"type": "number", "description": "Market cap mínimo en USD"},
            "market_cap_max": {"type": "number", "description": "Market cap máximo en USD"},
            "pais": {"type": "string", "description": "Código de país, ej 'US', 'CA'"},
            "limite": {"type": "integer", "description": f"Máximo de empresas a devolver (default {DEFAULT_LIMITE_SCREENER}, tope {MAX_LIMITE_SCREENER})"}
        },
        "required": []
    }
)
def _tool_screener_empresas(inputs: dict):
    from database import obtener_config  # import diferido: evita ciclo con database.py

    sector = inputs.get("sector")
    industria = inputs.get("industria")
    market_cap_min = inputs.get("market_cap_min")
    market_cap_max = inputs.get("market_cap_max")
    pais = inputs.get("pais")
    limite = inputs.get("limite") or DEFAULT_LIMITE_SCREENER

    modo, _ = resolver_modo(obtener_config("MODO_DATOS_EMPRESA"))
    if modo != "fmp_pago":
        return {
            "ok": False,
            "error": "El screener de empresas por sector/market cap necesita modo fmp_pago (FMP) — en modo gratis no está disponible. "
                     "Alternativa ahora mismo: brave_search para encontrar candidatos + thesis_screener para validarlos con datos reales. "
                     "O pasate a modo pago con configurar_modo_datos_empresa('fmp_pago') — noticias confirmadas en el plan Starter (~USD 19-22/mes); "
                     "el screener podría necesitar un plan superior, no confirmado todavía."
        }

    error = validar_params_screener(sector, industria, market_cap_min, market_cap_max, pais, limite)
    if error:
        return {"ok": False, "error": error}

    limite = min(int(limite), MAX_LIMITE_SCREENER)

    if not os.getenv("FMP_API_KEY"):
        return {"ok": False, "error": "Estás en modo pago (fmp_pago) pero no hay FMP_API_KEY cargada en el entorno. Cargala en config.env para usar el screener."}

    params = {"limit": limite}
    if sector:
        params["sector"] = sector
    if industria:
        params["industry"] = industria
    if pais:
        params["country"] = pais
    if market_cap_min is not None:
        params["marketCapMoreThan"] = market_cap_min
    if market_cap_max is not None:
        params["marketCapLowerThan"] = market_cap_max

    ok, items, error = obtener_screener_fmp(params, limite)
    if not ok:
        return {"ok": False, "error": f"FMP falló (plan sin acceso, key inválida, o error de red): {error}"}

    return {"ok": True, "data": {"empresas": items}}


@tool(
    "configurar_modo_datos_empresa",
    "Guarda qué fuente de datos de empresa usar: 'gratis' (Brave, sin costo) o 'fmp_pago' (Financial Modeling Prep, pago). "
    "Usar SIEMPRE esta tool en vez de save_config directo para este dato — valida el valor antes de guardar.",
    {
        "type": "object",
        "properties": {
            "modo": {"type": "string", "enum": list(MODOS_VALIDOS)}
        },
        "required": ["modo"]
    }
)
def _tool_configurar_modo_datos_empresa(inputs: dict):
    from database import guardar_config  # import diferido: evita ciclo con database.py

    modo = inputs.get("modo")
    error = validar_modo(modo)
    if error:
        return {"ok": False, "error": error}

    guardar_config("MODO_DATOS_EMPRESA", modo)
    return {"ok": True, "data": {"modo": modo}}
