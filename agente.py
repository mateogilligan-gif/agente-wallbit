import os
import json
import anthropic
from datetime import datetime

from tool_registry import TOOL_REGISTRY, tool

# database.py y los módulos de dominio de abajo registran sus propias tools
# con @tool(...) al importarse (efecto de lado, ver tool_registry.py). Acá se
# importan también las funciones puntuales que agente.py sigue usando directo
# (historial de chat, watchlist/alertas para los jobs periódicos, etc).
from database import (
    guardar_mensaje, obtener_historial, obtener_config,
    registrar_bitacora, obtener_watchlist, obtener_alertas_activas,
    init_db, obtener_alertas_pct_activas,
)
import wallbit_client
import brave_client
import market_data
import web_reader        # noqa: F401 — registra la tool leer_pagina_web
import global_search     # noqa: F401 — registra la tool busqueda_global
import social_sentiment  # noqa: F401 — registra la tool sentimiento_social
import reddit_client     # noqa: F401 — registra la tool reddit_sentiment


# ─── Bull vs Bear ──────────────────────────────────────────────────────────
#
# La única tool que se queda en agente.py en vez de vivir en un módulo de
# dominio: usa el cliente de Anthropic directamente (dos llamadas a Claude
# Haiku para el debate bull/bear), que es orquestación del chat, no una
# fuente de datos externa como las demás.

def _ejecutar_bull_bear(ticker: str, contexto: str = "") -> str:
    """
    Hace dos llamadas separadas a Claude Haiku con instrucciones opuestas:
    una para el caso alcista y otra para el bajista. Devuelve el debate completo.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    prompt_base = f"Analizá {ticker} como analista financiero senior. {contexto}".strip()

    # Buscar datos básicos de noticias para ambos
    noticias = ""
    try:
        items = brave_client.search_news(f"{ticker} stock news {datetime.now().year}", count=4)
        if items:
            noticias = "\n".join([f"- {n.get('titulo', '')} ({n.get('fuente', '')})" for n in items[:4]])
    except Exception:
        pass

    contexto_mercado = f"\nNoticias recientes:\n{noticias}" if noticias else ""

    def llamar_claude(system: str) -> str:
        try:
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=600,
                system=system,
                messages=[{"role": "user", "content": prompt_base + contexto_mercado}]
            )
            return resp.content[0].text if resp.content else ""
        except Exception as e:
            return f"Error: {str(e)}"

    sistema_bull = (
        f"Sos un analista alcista de Wall Street. Tu trabajo es construir el caso MÁS FUERTE posible para comprar {ticker}. "
        "Buscá los argumentos más sólidos: ventaja competitiva, crecimiento, TAM, management, tendencia secular. "
        "Sé específico. No menciones riesgos. Directo, sin emojis, máximo 5 bullets concisos."
    )

    sistema_bear = (
        f"Sos un short seller. Tu trabajo es construir el caso MÁS FUERTE posible para NO comprar {ticker}. "
        "Buscá los argumentos más sólidos: riesgos reales, competencia, valuación cara, deuda, ejecución débil. "
        "Sé específico con datos. No menciones positivos. Directo, sin emojis, máximo 5 bullets concisos."
    )

    caso_bull = llamar_claude(sistema_bull)
    caso_bear = llamar_claude(sistema_bear)

    return (
        f"DEBATE {ticker}: BULL vs BEAR\n"
        f"{'─' * 40}\n"
        f"CASO ALCISTA (por qué comprar):\n{caso_bull}\n\n"
        f"{'─' * 40}\n"
        f"CASO BAJISTA (por qué no comprar):\n{caso_bear}\n\n"
        f"{'─' * 40}\n"
        f"El veredicto final es tuyo. Guardá tu decision con /debate si queres trackearla."
    )


@tool(
    "bull_bear_analysis",
    "Ejecuta un debate estructurado Bull vs Bear sobre un ticker: dos análisis opuestos con argumentos concretos. Usar cuando el usuario pide debate, análisis profundo, o 'convenceme/no me convenzas' de una acción.",
    {"type": "object", "properties": {"ticker": {"type": "string"}, "contexto": {"type": "string"}}, "required": ["ticker"]}
)
def _tool_bull_bear_analysis(inputs: dict):
    ticker = inputs["ticker"].upper()
    contexto = inputs.get("contexto", "")
    return {"ok": True, "data": _ejecutar_bull_bear(ticker, contexto)}


TOOLS = [entry["schema"] for entry in TOOL_REGISTRY.values()]


# ─── Executor de herramientas ──────────────────────────────────────────────────

def ejecutar_herramienta(nombre: str, inputs: dict) -> str:
    """Busca la tool en el registro y ejecuta su handler.

    Antes esto era una cadena de 31 elif de ~340 líneas que vivía separada
    de la lista TOOLS. Ahora cada tool trae su propio handler registrado
    junto a su schema (arriba); acá solo queda el lookup + el manejo de
    errores/formato, que es común a las 32 tools.
    """
    entry = TOOL_REGISTRY.get(nombre)
    if not entry:
        return f"Herramienta desconocida: {nombre}"

    try:
        resultado = entry["handler"](inputs)

        # Algunos handlers devuelven un string de error directo (validación
        # de inputs faltantes) en vez del dict {"ok": ..., "data"/"error": ...}
        if isinstance(resultado, str):
            return resultado

        if resultado.get("ok"):
            return json.dumps(resultado["data"], ensure_ascii=False, indent=2)
        else:
            return f"Error: {resultado.get('error', 'Error desconocido')}"

    except Exception as e:
        registrar_bitacora("error", f"Error en herramienta {nombre}: {str(e)}")
        return f"Error ejecutando {nombre}: {str(e)}"


# ─── System prompt modular ─────────────────────────────────────────────────────
#
# Antes esto era un solo string de ~9.700 caracteres con los 11 protocolos
# siempre presentes, en cada mensaje — incluso para un simple "cuál es mi
# saldo". PROMPT_CORE (estilo, reglas de seguridad, ticket, análisis de
# empresa) va siempre: son las reglas base y el caso de uso más común. Los
# protocolos especializados (bull/bear, screener, research profundo, etc.)
# viven en PROMPT_MODULES y se suman solo si el mensaje del usuario trae
# palabras clave de ese protocolo — así el prompt típico pesa una fracción
# de lo que pesaba y no se diluye entre reglas que no aplican a este mensaje.

PROMPT_CORE = """Agente financiero de Mateo. Buy & hold, largo plazo.

ESTILO: Directo, sin relleno, sin emojis. Priorizo entender el negocio sobre los números.

REGLAS:
1. create_trade: SOLO con SÍ/CONFIRMO explícito. Mostrar ticket antes.
2. Watchlist/alertas/metas: LLAMAR la herramienta, no prometérselo. Para alertas de % de movimiento usar manage_pct_alerts (precio siempre externo vía yfinance, no Wallbit). Wallbit hoy NO expone el costo promedio de compra en get_stocks_balance — si el usuario pide una alerta referencia="compra", PREGUNTALE su precio de compra si no lo mencionó, y pasalo en avg_cost_manual. Sin ese dato la alerta queda creada pero inerte. NUNCA inventes ni menciones un precio de compra específico que el usuario no te dio.
2b. ACCIONES EN LOTE (crear/editar varias cosas a la vez, ej "creá esto para todas mis posiciones"): llamá las herramientas DIRECTAMENTE una por una, sin narrar el plan completo en texto antes. Si son muchos ítems (10+), no expliques cada uno de antemano — actuá primero, resumí al final.
3. Detectar sesgos (FOMO, anclaje) y avisar.
4. DECISION LOG: Al terminar cualquier análisis de un ticker, usar decision_log(guardar) con el veredicto (alcista/bajista/neutral) y el razonamiento en 1 línea. Al iniciar un nuevo análisis del mismo ticker, leer primero el historial para comparar si la tesis anterior fue correcta.
5. PROFUNDIDAD: Si el mensaje dice "rápido" o "quick" → 1 brave_search + yf_info. Si dice "profundo" o "deep" → hasta 3 brave_search + yf_info + yf_financials + sec_filings. Por defecto: 1 brave_search + yf_info.

TICKET antes de create_trade:
Acción:[COMPRA/VENTA] Ticker:[X] Tipo:[MARKET/LIMIT] Monto:$[X] Riesgo:[X]
¿Confirmás? (SÍ/NO)

ANÁLISIS DE EMPRESA — estructura obligatoria cuando analizan un ticker:
Usá brave_search + yf_info. El foco es entender el negocio, no recitar balances.

1. QUÉ HACE: Explicá el producto o servicio en 2-3 líneas. Qué problema resuelve, cómo gana plata, quiénes son sus clientes.

2. PRODUCTOS Y PROYECTOS: Qué está construyendo ahora. Lanzamientos recientes, roadmap, contratos importantes, partnerships. Buscá con brave_search noticias de los últimos 6 meses. Si el snippet no alcanza para entender el detalle, usá leer_pagina_web sobre la URL más relevante (máximo 2) para sacar el texto completo antes de escribir la sección.

3. COMPETENCIA Y POSICIÓN: Quiénes son sus 2-3 competidores directos. Qué ventaja tiene esta empresa sobre ellos. Está ganando o perdiendo terreno.

4. POTENCIAL A LARGO PLAZO: Por qué esta empresa puede importar en 5 años. Qué tendencia secular la favorece. Cuál es el riesgo que podría destruir esa tesis.

5. NÚMEROS (resumido): Solo 4 métricas — revenue del último año, crecimiento YoY, si es rentable o quema caja, y deuda. Nada más. Si el negocio no convence, los números no importan."""


PROMPT_MODULES = {
    "sentimiento_social": {
        "keywords": ["reddit", "wallstreetbets", "hype", "sentimiento", "qué dice la gente", "que dice la gente", "stocktwits", "bullish", "bearish"],
        "texto": """SENTIMIENTO SOCIAL — solo si el usuario lo pide explícitamente ("qué dice la gente", "hype", "sentimiento del mercado", "qué dice reddit"):
Usar sentimiento_social (StockTwits) para el pulso rápido Bullish/Bearish, y reddit_sentiment cuando quieran más contexto o discusión (menciona el score/upvotes de cada post para que el usuario juzgue qué tan respaldado está). Aclarar SIEMPRE que es sentimiento de retail/comunidad, no un indicador fundamental — sirve para detectar euforia o pánico excesivo, no para tomar la decisión de inversión en sí."""
    },
    "filings_riesgo": {
        "keywords": ["10-k", "10-q", "8-k", "filing", "filings", "riesgo", "riesgos", "supply chain", "cadena de suministro", "concentración de clientes", "concentracion de clientes", "litigio"],
        "texto": """BÚSQUEDA DE RIESGOS EN FILINGS — cuando pidan "qué dice el 10-K sobre X riesgo", "buscá menciones de [tema] en los reportes", o quieran validar un riesgo puntual (cadena de suministro, concentración de clientes, litigios):
Usar sec_busqueda_texto con el ticker y la frase exacta a buscar (ej: "supply chain disruption", "customer concentration"). Esto busca DENTRO del contenido real de los documentos, no solo lista cuáles existen — mucho más preciso que sec_filings para encontrar un riesgo específico."""
    },
    "earnings": {
        "keywords": ["earnings", "resultados", "ganancias", "reportó", "reporto", "reporta", "guidance", "eps", "revenue"],
        "texto": """EARNINGS ANALYSIS — análisis post-earnings:
Usá brave_search para buscar el earnings call. Estructura: beat/miss vs consenso, qué dijo el CEO sobre productos y crecimiento futuro, si la tesis de largo plazo sigue intacta.

EARNINGS PREVIEW — antes de que reporte:
Usá brave_search. Qué espera el mercado, qué métricas mirar, si hay catalizadores de producto o contratos que puedan sorprender."""
    },
    "idea_generation": {
        "keywords": ["ideas", "recomendás", "recomendas", "qué comprar", "que comprar", "sugerime empresas", "sugerime acciones"],
        "texto": """IDEA GENERATION — cuando pidan ideas:
5 empresas con: qué hacen en una línea, por qué tienen potencial de largo plazo, en qué etapa están (temprana/consolidada), y el riesgo principal."""
    },
    "sector_overview": {
        "keywords": ["sector", "industria", "rubro"],
        "texto": """SECTOR OVERVIEW — análisis de un sector:
Qué problema resuelve el sector, quiénes son los líderes y por qué, qué empresa emergente vale la pena seguir, qué podría destruir el sector en 5 años."""
    },
    "thesis_tracker": {
        "keywords": ["tesis", "thesis"],
        "texto": """THESIS TRACKER — armar o revisar una tesis:
1) Por qué esta empresa en una línea, 2) Qué tiene que ser verdad para que funcione, 3) Qué señal concreta me diría que me equivoqué, 4) Catalizadores próximos 6 meses."""
    },
    "morning_note": {
        "keywords": ["morning", "briefing", "resumen matutino", "buenos días", "buenos dias", "buen día", "buen dia"],
        "texto": """MORNING NOTE — morning briefing:
Usá get_portfolio_summary + brave_search. Qué pasó en el mercado, alguna noticia de mis empresas, dato macro relevante, 1 acción concreta."""
    },
    "bull_bear": {
        "keywords": ["debate", "convenceme", "convencé", "convence", "no me convenzas"],
        "texto": """BULL VS BEAR — cuando pidan debate o "convenceme":
Usar bull_bear_analysis. Dos llamadas separadas, argumentos opuestos, veredicto es del usuario. Al terminar, sugerir guardar la decisión en decision_log."""
    },
    "screener_tesis": {
        "keywords": ["screener", "candidatos", "penny stock", "catalizador", "ideas basadas en"],
        "texto": """SCREENER DE TESIS — cuando el usuario describa una tesis y pida ideas/candidatos (ej: "empresas de defensa con contratos nuevos", "penny stocks de biotech con catalizador cerca"):
1. brave_search (1-2 búsquedas) para encontrar 8-15 empresas candidatas que mencionen medios o análisis recientes sobre esa tesis.
2. Extraer los tickers de esos candidatos (si no es obvio el ticker, usar get_asset o yf_info para confirmarlo antes de pasarlo al filtro).
3. Llamar thesis_screener con esos tickers. Definir criterios numéricos razonables según lo que pidió el usuario (si no especificó, usar defaults: min_revenue_growth 0.15, sin límite de market cap salvo que digan "chica/mediana/grande").
4. Presentar el TOP 5 de los que cumplieron: ticker, por qué encaja con la tesis (1 línea), la métrica que lo valida, y el riesgo principal. Mencionar cuántos candidatos fueron descartados y por qué (breve)."""
    },
    "research_profundo": {
        "keywords": ["metete en la web", "meterte en la web", "diario local", "diarios locales", "foro", "investigá", "investiga"],
        "texto": """RESEARCH PROFUNDO — cuando el usuario pida "metete en la web de [empresa]", "buscá en diarios locales/foros del rubro", o el análisis normal se quede corto:
1. Identificar primero el país y el rubro de la empresa (dónde cotiza, dónde tiene sede, industria). Esto define el código de país/idioma a usar — NO asumir que son medios argentinos salvo que la empresa opere en Argentina.
2. Web oficial de la empresa: buscar con brave_search "[empresa] official website news OR newsroom OR investor relations" y usar leer_pagina_web sobre la URL que encuentre.
3. Prensa local/global: usar busqueda_global con el código ISO de país e idioma correspondiente (ej empresa australiana → pais="AU" idioma="en", empresa alemana → pais="DE" idioma="de", empresa brasilera → pais="BR" idioma="pt"). Esto trae medios reales de ese mercado (Google News + GDELT), no solo lo que indexa brave_search en inglés.
4. Una vez identificada la URL relevante (medio local, foro especializado, o sitio oficial), usar leer_pagina_web para sacar el texto completo — no te quedes solo con el título.
5. Máximo 2-3 leer_pagina_web por consulta para no gastar tokens de más. Priorizar la fuente más reciente y relevante, en el idioma que sea (traducir el hallazgo al responder)."""
    },
}


def construir_system_prompt(mensaje_usuario: str, contexto_extra: str = "") -> str:
    """
    Arma el system prompt para ESTE mensaje: PROMPT_CORE va siempre completo
    (reglas de seguridad, estilo, ticket, análisis de empresa). A eso se le
    suman solo los módulos de PROMPT_MODULES cuyas palabras clave aparecen
    en el mensaje (o en el contexto extra, ej. el de morning_briefing_automatico).

    Si el mensaje pide profundidad ("profundo"/"deep" — la regla 5 ya usa
    esa palabra para pedir más tool calls), se suman TODOS los módulos como
    red de seguridad: el matching por palabra clave es simple y puede fallar
    un módulo puntual, pero un pedido explícito de profundidad no debería
    quedarse corto de protocolo.
    """
    texto = f"{contexto_extra} {mensaje_usuario}".lower()
    pide_profundidad = "profundo" in texto or "deep" in texto

    partes = [PROMPT_CORE]
    for modulo in PROMPT_MODULES.values():
        if pide_profundidad or any(kw in texto for kw in modulo["keywords"]):
            partes.append(modulo["texto"])

    return "\n\n".join(partes)

# ─── Función principal de chat con Tool Use ───────────────────────────────────

def _sanitizar_alternancia(mensajes: list) -> list:
    """
    La API de Anthropic exige turnos estrictamente alternados user/assistant.
    Si el historial guardado en la DB quedó con turnos repetidos seguidos
    (por ejemplo porque una respuesta anterior falló y no se guardó), esta
    función los fusiona para que la conversación quede siempre alternada
    antes de mandarla a la API.
    """
    if not mensajes:
        return mensajes
    limpios = [mensajes[0]]
    for m in mensajes[1:]:
        if m["role"] == limpios[-1]["role"]:
            # Mismo rol que el anterior: fusionar en vez de mandar duplicado
            if isinstance(limpios[-1]["content"], str) and isinstance(m["content"], str):
                limpios[-1]["content"] += f"\n\n{m['content']}"
            else:
                limpios[-1] = m  # contenido no-string (bloques de tool use): priorizar el más nuevo
        else:
            limpios.append(m)
    # Debe arrancar en "user"
    if limpios and limpios[0]["role"] != "user":
        limpios = limpios[1:]
    return limpios


def chat(mensaje_usuario: str, contexto_extra: str = "") -> str:
    """Procesa un mensaje usando Anthropic Tool Use para llamadas reales a Wallbit."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    guardar_mensaje("user", mensaje_usuario)
    historial = obtener_historial(limite=6)

    # Construir mensajes
    messages = []
    for h in historial[:-1]:
        messages.append({"role": h["role"], "content": h["content"]})

    contenido = mensaje_usuario
    if contexto_extra:
        contenido = f"{contexto_extra}\n\nMensaje: {mensaje_usuario}"
    messages.append({"role": "user", "content": contenido})

    # Defensa ante historial ya corrupto (turnos repetidos guardados en sesiones anteriores)
    messages = _sanitizar_alternancia(messages)

    # Se arma una sola vez por mensaje entrante (no por iteración del loop de abajo,
    # que puede llamar varias tools dentro del mismo turno con el mismo prompt).
    system_prompt = construir_system_prompt(mensaje_usuario, contexto_extra)

    # Loop de tool use: Claude puede llamar múltiples herramientas en secuencia
    MAX_ITERACIONES = 10
    for _ in range(MAX_ITERACIONES):
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=3072,
                system=system_prompt,
                tools=TOOLS,
                messages=messages
            )
        except anthropic.APIError as e:
            error = f"⚠️ Error de API: {str(e)}"
            registrar_bitacora("error", error)
            # Guardar SIEMPRE una respuesta, aunque sea de error — si no, el próximo
            # mensaje queda con dos turnos "user" seguidos y la API los rechaza.
            guardar_mensaje("assistant", error)
            return error

        # Claude terminó de responder (end_turn o max_tokens)
        if response.stop_reason in ("end_turn", "max_tokens"):
            texto_final = ""
            for bloque in response.content:
                if hasattr(bloque, "text"):
                    texto_final += bloque.text
            guardar_mensaje("assistant", texto_final)
            registrar_bitacora("chat", f"Usuario: {mensaje_usuario[:50]}...")
            return texto_final

        # Claude quiere usar herramientas
        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})

            resultados_tools = []
            for bloque in response.content:
                if bloque.type == "tool_use":
                    resultado = ejecutar_herramienta(bloque.name, bloque.input)
                    resultados_tools.append({
                        "type": "tool_result",
                        "tool_use_id": bloque.id,
                        "content": resultado
                    })
                    registrar_bitacora("tool", f"Ejecuté {bloque.name}: {str(resultado)[:100]}")

            messages.append({"role": "user", "content": resultados_tools})
            continue

        break

    fallback = "⚠️ No pude completar la respuesta. Intentá de nuevo."
    guardar_mensaje("assistant", fallback)
    return fallback

# ─── Funciones auxiliares ──────────────────────────────────────────────────────

def construir_contexto_inicial() -> str:
    watchlist = obtener_watchlist()
    alertas = obtener_alertas_activas()
    monto_sueldo = obtener_config("MONTO_SUELDO")
    partes = []
    if watchlist:
        tickers = [w[0] for w in watchlist]
        partes.append(f"📋 Watchlist: {', '.join(tickers)}")
    if alertas:
        partes.append(f"🔔 {len(alertas)} alertas de precio activas")
    if monto_sueldo:
        partes.append(f"💰 Inversión de sueldo configurada: ${monto_sueldo}")
    return "\n".join(partes)

def morning_briefing_automatico() -> str:
    return chat("Dame mi Morning Briefing completo con datos reales de mi portafolio y noticias del mercado de hoy.")

def verificar_earnings_portfolio(days: int = 7) -> list:
    """
    Extrae tickers del portafolio de Wallbit y verifica cuáles reportan
    earnings en los próximos `days` días. Retorna lista de strings listos
    para enviar por Telegram.
    """
    mensajes = []
    try:
        # Obtener tickers del portafolio
        res = wallbit_client.get_stocks_balance()
        if not res.get("ok"):
            return []

        data = res["data"]
        raw = data if isinstance(data, str) else json.dumps(data)

        # Usar el parser de wallbit_client para extraer tickers limpios
        posiciones = wallbit_client._parse_portfolio_text(raw)
        tickers = [p["ticker"] for p in posiciones if p.get("ticker")]

        # También chequear la watchlist
        watchlist = obtener_watchlist()
        for w in watchlist:
            if w[0] not in tickers:
                tickers.append(w[0])

        if not tickers:
            return []

        # Verificar earnings
        resultado = market_data.check_earnings_upcoming(tickers, days=days)
        if not resultado["ok"] or not resultado["data"]:
            return []

        for item in resultado["data"]:
            eps_str = f" | EPS est. ${item['eps_estimado']:.2f}" if item.get("eps_estimado") else ""
            dias_str = "HOY" if item["dias_faltan"] == 0 else f"en {item['dias_faltan']} dias"
            mensajes.append(
                f"[EARNINGS] {item['ticker']} ({item['nombre']}) reporta {dias_str} — {item['fecha']}{eps_str}"
            )

    except Exception as e:
        registrar_bitacora("error", f"Error verificando earnings: {str(e)}")

    return mensajes


def verificar_alertas() -> list:
    alertas_disparadas = []
    alertas = obtener_alertas_activas()
    for alerta_id, ticker, precio_objetivo, tipo in alertas:
        resultado = wallbit_client.get_asset(ticker)
        if resultado["ok"]:
            try:
                data = json.loads(resultado["data"]) if isinstance(resultado["data"], str) else resultado["data"]
                precio_actual = float(data.get("price", 0))
                if tipo == "minimo" and precio_actual <= precio_objetivo:
                    alertas_disparadas.append(f"🔔 {ticker} llegó a ${precio_actual:.2f} (objetivo: ${precio_objetivo:.2f})")
                elif tipo == "maximo" and precio_actual >= precio_objetivo:
                    alertas_disparadas.append(f"🔔 {ticker} llegó a ${precio_actual:.2f} (objetivo: ${precio_objetivo:.2f})")
            except Exception:
                pass
    return alertas_disparadas


def _evaluar_disparo_pct(precio_actual: float, precio_referencia: float, umbral_pct: float, direccion: str) -> tuple:
    """
    Lógica PURA de cálculo de % de cambio y si dispara o no una alerta.
    Separada del resto (que hace llamadas de red) para poder testearla sola.
    Devuelve (cambio_pct, dispara: bool).
    """
    cambio_pct = round((precio_actual / precio_referencia - 1) * 100, 2)
    dispara = (
        (direccion in ("sube", "ambas") and cambio_pct >= umbral_pct) or
        (direccion in ("baja", "ambas") and cambio_pct <= -umbral_pct)
    )
    return cambio_pct, dispara


def verificar_alertas_pct() -> list:
    """
    Chequea las alertas de porcentaje. El precio SIEMPRE sale de yfinance
    (externo, no depende de get_asset de Wallbit, que hoy está roto).
    Para alertas referencia='compra' se usa avg_cost de get_stocks_balance
    (esa herramienta de Wallbit sí funciona) combinado con el precio externo.
    """
    disparadas = []
    alertas = obtener_alertas_pct_activas()
    if not alertas:
        return disparadas

    # Traer avg_cost una sola vez si hace falta para alertas tipo "compra"
    avg_costs = {}
    if any(a[4] == "compra" for a in alertas):
        try:
            res = wallbit_client.get_stocks_balance()
            if res.get("ok"):
                raw = res["data"]
                raw_str = raw if isinstance(raw, str) else json.dumps(raw)
                posiciones = wallbit_client._parse_portfolio_text(raw_str)
                avg_costs = {p["ticker"]: p.get("avg_cost") for p in posiciones if p.get("ticker") and p.get("avg_cost")}
        except Exception:
            pass

    for alerta_id, ticker, umbral_pct, direccion, referencia, avg_cost_manual in alertas:
        info = market_data.yf_get_price_change(ticker)
        if not info["ok"]:
            continue
        precio_actual = info["data"]["precio_actual"]

        if referencia == "compra":
            # Wallbit no expone avg_cost hoy — priorizar el precio manual si existe
            avg_cost = avg_cost_manual or avg_costs.get(ticker)
            if not avg_cost:
                continue
            cambio_pct, dispara = _evaluar_disparo_pct(precio_actual, avg_cost, umbral_pct, direccion)
            ref_str = "desde tu compra"
        else:
            cierre_anterior = info["data"]["cierre_anterior"]
            cambio_pct, dispara = _evaluar_disparo_pct(precio_actual, cierre_anterior, umbral_pct, direccion)
            ref_str = "hoy"

        if dispara:
            signo = "+" if cambio_pct >= 0 else ""
            disparadas.append(
                f"📈 {ticker} se movió {signo}{cambio_pct:.2f}% {ref_str} "
                f"(umbral: {umbral_pct}%, precio actual ${precio_actual:.2f})"
            )

    return disparadas

# ─── Modo consola para testing ─────────────────────────────────────────────────

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv("config.env")
    init_db()

    print("🤖 Agente Wallbit iniciado en modo consola. Escribí 'salir' para terminar.\n")
    ctx = construir_contexto_inicial()
    if ctx:
        print(f"📋 Contexto:\n{ctx}\n")

    while True:
        try:
            user_input = input("Vos: ").strip()
            if user_input.lower() in ["salir", "exit"]:
                print("Agente: ¡Hasta luego!")
                break
            if not user_input:
                continue
            print("\nAgente: ", end="", flush=True)
            print(chat(user_input))
            print()
        except KeyboardInterrupt:
            print("\n\nAgente: Sesión interrumpida.")
            break
