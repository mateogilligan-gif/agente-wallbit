import os
import json
import anthropic
from datetime import datetime
from database import (
    guardar_mensaje, obtener_historial, guardar_config, obtener_config,
    registrar_bitacora, obtener_watchlist, obtener_alertas_activas,
    obtener_diario_trading, init_db,
    agregar_watchlist, eliminar_watchlist,
    crear_alerta, desactivar_alerta,
    crear_presupuesto, obtener_presupuestos, actualizar_gasto_presupuesto,
    crear_meta, obtener_metas, actualizar_progreso_meta,
    guardar_trade_diario,
    guardar_decision, obtener_decisiones_ticker, actualizar_resultado_decision,
    crear_alerta_pct, obtener_alertas_pct_activas, desactivar_alerta_pct
)
import wallbit_client
import brave_client
import market_data
import web_reader
import global_search
import social_sentiment
import reddit_client

# ─── Definición de herramientas para Anthropic Tool Use ───────────────────────

TOOLS = [
    {
        "name": "get_portfolio_summary",
        "description": "Portfolio completo: saldo corriente + todas las posiciones con ticker, cantidad de acciones, precio promedio, valor actual y P&L. Usar este en vez de get_checking_balance + get_stocks_balance por separado.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_checking_balance",
        "description": "Solo saldo cuenta corriente Wallbit (cash disponible).",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_stocks_balance",
        "description": "Solo posiciones de inversión crudas. Preferir get_portfolio_summary.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "list_transactions",
        "description": "Transacciones recientes Wallbit.",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}, "required": []}
    },
    {
        "name": "get_asset",
        "description": "Precio actual de un ticker.",
        "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}
    },
    {
        "name": "create_trade",
        "description": "Ejecuta orden. SOLO con SÍ/CONFIRMO explícito.",
        "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}, "side": {"type": "string", "enum": ["buy", "sell"]}, "amount": {"type": "number"}, "order_type": {"type": "string", "enum": ["market", "limit"]}, "price": {"type": "number"}}, "required": ["ticker", "side", "amount", "order_type"]}
    },
    {
        "name": "brave_search",
        "description": "Busca noticias financieras en tiempo real.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "tipo": {"type": "string", "enum": ["web", "news"]}}, "required": ["query"]}
    },
    {
        "name": "manage_watchlist",
        "description": "Watchlist: agregar/eliminar/listar tickers.",
        "input_schema": {"type": "object", "properties": {"accion": {"type": "string", "enum": ["agregar", "eliminar", "listar"]}, "ticker": {"type": "string"}, "notas": {"type": "string"}}, "required": ["accion"]}
    },
    {
        "name": "manage_alerts",
        "description": "Alertas de precio ABSOLUTO: crear/eliminar/listar (ej 'avisame si AAPL baja de $150'). Para alertas de PORCENTAJE de movimiento (ej 'avisame si sube más de 5%'), usar manage_pct_alerts.",
        "input_schema": {"type": "object", "properties": {"accion": {"type": "string", "enum": ["crear", "eliminar", "listar"]}, "ticker": {"type": "string"}, "precio": {"type": "number"}, "tipo": {"type": "string", "enum": ["minimo", "maximo"]}, "alerta_id": {"type": "integer"}}, "required": ["accion"]}
    },
    {
        "name": "manage_pct_alerts",
        "description": "Alertas de PORCENTAJE de movimiento sobre un ticker (crear/eliminar/listar). El precio actual siempre se obtiene de yfinance (fuente externa), no de Wallbit. Dos referencias: 'dia' (% vs cierre de ayer) o 'compra' (% vs precio de compra, para P&L). IMPORTANTE: Wallbit hoy NO expone el costo promedio de compra en ningún campo — para referencia='compra' hay que pedirle al usuario su precio de compra si no lo dijo, y pasarlo en avg_cost_manual. Sin ese dato la alerta se crea pero nunca podrá dispararse.",
        "input_schema": {
            "type": "object",
            "properties": {
                "accion": {"type": "string", "enum": ["crear", "eliminar", "listar"]},
                "ticker": {"type": "string"},
                "umbral_pct": {"type": "number", "description": "Ej 5 = 5%"},
                "direccion": {"type": "string", "enum": ["sube", "baja", "ambas"], "description": "Default: ambas"},
                "referencia": {"type": "string", "enum": ["dia", "compra"], "description": "Default: dia"},
                "avg_cost_manual": {"type": "number", "description": "Precio de compra dado por el usuario. Requerido en la práctica para referencia=compra porque Wallbit no lo expone hoy."},
                "alerta_id": {"type": "integer"}
            },
            "required": ["accion"]
        }
    },
    {
        "name": "manage_budget",
        "description": "Presupuesto mensual por categorías.",
        "input_schema": {"type": "object", "properties": {"accion": {"type": "string", "enum": ["crear", "listar", "actualizar_gasto"]}, "categoria": {"type": "string"}, "limite_usd": {"type": "number"}, "monto_adicional": {"type": "number"}}, "required": ["accion"]}
    },
    {
        "name": "manage_goals",
        "description": "Metas financieras: crear/listar/actualizar.",
        "input_schema": {"type": "object", "properties": {"accion": {"type": "string", "enum": ["crear", "listar", "actualizar_progreso"]}, "nombre": {"type": "string"}, "objetivo_usd": {"type": "number"}, "actual_usd": {"type": "number"}, "fecha_limite": {"type": "string"}}, "required": ["accion"]}
    },
    {
        "name": "save_config",
        "description": "Guarda/lee configuración (MONTO_SUELDO, PORCENTAJE_DCA, etc).",
        "input_schema": {"type": "object", "properties": {"accion": {"type": "string", "enum": ["guardar", "leer"]}, "clave": {"type": "string"}, "valor": {"type": "string"}}, "required": ["accion", "clave"]}
    },
    {
        "name": "trading_diary",
        "description": "Diario de trades: guardar/leer historial.",
        "input_schema": {"type": "object", "properties": {"accion": {"type": "string", "enum": ["guardar", "leer"]}, "ticker": {"type": "string"}, "accion_trade": {"type": "string"}, "precio": {"type": "number"}, "monto": {"type": "number"}, "razonamiento": {"type": "string"}, "sesgo": {"type": "string"}, "limite": {"type": "integer"}}, "required": ["accion"]}
    },
    {
        "name": "yf_info",
        "description": "Fundamentals de una acción: P/E, market cap, márgenes, crecimiento, consenso analistas.",
        "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}
    },
    {
        "name": "yf_history",
        "description": "Historial de precios y rendimiento. period: 1d,5d,1mo,3mo,6mo,1y,2y,5y.",
        "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}, "period": {"type": "string"}}, "required": ["ticker"]}
    },
    {
        "name": "yf_financials",
        "description": "Estado de resultados anual: ingresos, utilidad neta, EBITDA.",
        "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}
    },
    {
        "name": "yf_insiders",
        "description": "Compras y ventas de insiders (directivos) de una empresa.",
        "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}
    },
    {
        "name": "yf_dividends",
        "description": "Historial de dividendos de los últimos 5 años.",
        "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}
    },
    {
        "name": "fred_macro",
        "description": "Datos macroeconómicos de la Fed: inflacion_cpi, tasa_fed, desempleo, pib, rendimiento_10y, rendimiento_2y, indice_dolar, ventas_retail, confianza_consumidor.",
        "input_schema": {"type": "object", "properties": {"serie": {"type": "string"}, "observaciones": {"type": "integer"}}, "required": ["serie"]}
    },
    {
        "name": "sec_filings",
        "description": "Filings de SEC EDGAR: 10-K, 10-Q, 8-K. Busca por nombre de empresa.",
        "input_schema": {"type": "object", "properties": {"company": {"type": "string"}, "form_type": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["company"]}
    },
    {
        "name": "sec_facts",
        "description": "Datos financieros oficiales de SEC por ticker: ingresos, utilidad, activos históricos.",
        "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}
    },
    {
        "name": "sec_busqueda_texto",
        "description": "Búsqueda de TEXTO COMPLETO dentro del contenido real de los filings de SEC EDGAR (no solo lista documentos, busca DENTRO de ellos). Usar para encontrar frases o riesgos específicos, ej: buscar 'supply chain' o 'customer concentration' dentro de los 10-K de una empresa, o ver qué empresas mencionan un riesgo particular. Pasar ticker para limitar la búsqueda a una sola empresa, o dejarlo vacío para buscar en toda la base de EDGAR.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Frase o palabra clave a buscar dentro de los documentos"},
                "ticker": {"type": "string", "description": "Opcional, restringe la búsqueda a esta empresa"},
                "form_type": {"type": "string", "description": "Opcional, ej 10-K, 10-Q, 8-K"},
                "limit": {"type": "integer"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "yf_earnings_calendar",
        "description": "Próxima fecha de earnings de un ticker y estimados de EPS/Revenue del consenso.",
        "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}
    },
    {
        "name": "check_earnings_upcoming",
        "description": "Chequea qué tickers del portafolio/watchlist reportan earnings en los próximos N días.",
        "input_schema": {"type": "object", "properties": {"tickers": {"type": "array", "items": {"type": "string"}}, "days": {"type": "integer"}}, "required": ["tickers"]}
    },
    {
        "name": "decision_log",
        "description": "Guarda o lee el historial de análisis sobre un ticker. Guardar: registra veredicto (alcista/bajista/neutral) + razonamiento + precio actual. Leer: muestra análisis anteriores sobre ese ticker para validar si la tesis fue correcta.",
        "input_schema": {"type": "object", "properties": {"accion": {"type": "string", "enum": ["guardar", "leer"]}, "ticker": {"type": "string"}, "precio_momento": {"type": "number"}, "veredicto": {"type": "string", "enum": ["alcista", "bajista", "neutral"]}, "razonamiento": {"type": "string"}, "resultado": {"type": "string"}}, "required": ["accion", "ticker"]}
    },
    {
        "name": "bull_bear_analysis",
        "description": "Ejecuta un debate estructurado Bull vs Bear sobre un ticker: dos análisis opuestos con argumentos concretos. Usar cuando el usuario pide debate, análisis profundo, o 'convenceme/no me convenzas' de una acción.",
        "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}, "contexto": {"type": "string"}}, "required": ["ticker"]}
    },
    {
        "name": "thesis_screener",
        "description": "Filtra una lista de tickers candidatos con datos REALES de yfinance según criterios cuantitativos. Usar SIEMPRE después de brave_search cuando el usuario pida un screener/ideas basadas en una tesis: primero buscar 8-15 empresas candidatas con brave_search, extraer sus tickers, y después llamar esta herramienta para validarlas con números reales y descartar las que no cumplen.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tickers": {"type": "array", "items": {"type": "string"}, "description": "Tickers candidatos a validar"},
                "min_revenue_growth": {"type": "number", "description": "Ej 0.15 = mínimo 15% crecimiento YoY"},
                "max_pe": {"type": "number"},
                "min_market_cap": {"type": "number", "description": "En USD"},
                "max_market_cap": {"type": "number", "description": "En USD"},
                "min_profit_margin": {"type": "number", "description": "Ej 0.10 = mínimo 10% margen neto"},
                "max_debt_to_equity": {"type": "number"}
            },
            "required": ["tickers"]
        }
    },
    {
        "name": "busqueda_global",
        "description": "Motor de búsqueda de noticias GLOBAL (Google News + GDELT), cubre prensa de cualquier país del mundo, no solo medios en inglés/EEUU como brave_search. Usar cuando se necesite cobertura de prensa local de un país específico (empresa australiana, europea, asiática, latinoamericana) o cuando brave_search no traiga resultados relevantes de ese mercado. Pasar el código de país ISO (AU, DE, JP, AR, BR, etc) e idioma (en, de, ja, es, etc) según de dónde sea la empresa. Devuelve título, URL, fuente y país — después usar leer_pagina_web sobre la URL más relevante para el texto completo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Términos de búsqueda"},
                "pais": {"type": "string", "description": "Código ISO 2 letras del país, ej AU, DE, JP, AR, BR"},
                "idioma": {"type": "string", "description": "Código ISO 2 letras del idioma, ej en, de, ja, es"},
                "count": {"type": "integer"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "sentimiento_social",
        "description": "Sentimiento de la comunidad de StockTwits (red social 100% financiera) sobre un ticker: % de mensajes Bullish vs Bearish, etiquetados por los propios usuarios. Mucho menos ruido que X/Twitter porque es una comunidad exclusiva de trading. Usar cuando el usuario pregunte 'qué dice la gente', 'sentimiento del mercado minorista', 'hype', o quiera pulso social de una acción.",
        "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["ticker"]}
    },
    {
        "name": "reddit_sentiment",
        "description": "Busca menciones de un ticker/empresa en subreddits financieros (r/wallstreetbets, r/stocks, r/investing, r/StockMarket) de la última semana, rankeadas por score (upvotes). Complementa a sentimiento_social (StockTwits): Reddit trae discusión más larga y con contexto, StockTwits trae el pulso Bullish/Bearish más directo. Usar cuando pidan 'qué dice reddit', 'hay hype en wallstreetbets', o sentimiento retail más profundo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Ticker o nombre de empresa a buscar"},
                "subreddits": {"type": "array", "items": {"type": "string"}, "description": "Opcional, default: wallstreetbets, stocks, investing, StockMarket"},
                "limit": {"type": "integer"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "leer_pagina_web",
        "description": "Entra a una URL específica y devuelve el texto completo de la página (no solo título/resumen). Usar cuando: (1) brave_search o busqueda_global devolvieron un snippet insuficiente y hace falta más detalle, (2) el usuario pide explícitamente meterse en la web oficial de una empresa (sección 'News'/'Newsroom'/'Investor Relations'), o (3) hay que leer un diario o foro específico de cualquier país. Internamente prueba lectura directa primero y si el sitio renderiza con JavaScript (contenido vacío), cae automáticamente a un lector con motor de render — no hace falta pedirlo. Máximo 2-3 llamadas por consulta para no gastar tokens de más.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL completa a leer"},
                "max_chars": {"type": "integer", "description": "Límite de caracteres a extraer, default 4000"}
            },
            "required": ["url"]
        }
    }
]

# ─── Executor de herramientas ──────────────────────────────────────────────────

def ejecutar_herramienta(nombre: str, inputs: dict) -> str:
    """Ejecuta la herramienta solicitada por Claude y devuelve el resultado como string."""
    try:
        # ── Wallbit API ──
        if nombre == "get_portfolio_summary":
            resultado = wallbit_client.get_portfolio_summary()

        elif nombre == "get_checking_balance":
            resultado = wallbit_client.get_checking_balance()

        elif nombre == "get_stocks_balance":
            resultado = wallbit_client.get_stocks_balance()

        elif nombre == "list_transactions":
            limit = inputs.get("limit", 50)
            resultado = wallbit_client.list_transactions(limit)

        elif nombre == "get_asset":
            resultado = wallbit_client.get_asset(inputs["ticker"])

        elif nombre == "create_trade":
            resultado = wallbit_client.create_trade(
                ticker=inputs["ticker"],
                side=inputs["side"],
                amount=inputs["amount"],
                order_type=inputs.get("order_type", "market"),
                price=inputs.get("price")
            )

        # ── Búsqueda web ──
        elif nombre == "brave_search":
            tipo = inputs.get("tipo", "news")
            query = inputs["query"]
            if tipo == "news":
                items = brave_client.search_news(query, count=5)
            else:
                items = brave_client.search_web(query, count=5)
            if items:
                resultado = {"ok": True, "data": items}
            else:
                resultado = {"ok": False, "error": "Sin resultados"}

        # ── Watchlist ──
        elif nombre == "manage_watchlist":
            accion = inputs["accion"]
            if accion == "agregar":
                ticker = inputs.get("ticker", "").upper()
                if not ticker:
                    return "Error: se necesita un ticker para agregar"
                agregar_watchlist(ticker, notas=inputs.get("notas", ""))
                resultado = {"ok": True, "data": f"✅ {ticker} agregado a la watchlist"}
            elif accion == "eliminar":
                ticker = inputs.get("ticker", "").upper()
                if not ticker:
                    return "Error: se necesita un ticker para eliminar"
                ok = eliminar_watchlist(ticker)
                resultado = {"ok": True, "data": f"{'✅ ' + ticker + ' eliminado' if ok else '⚠️ ' + ticker + ' no estaba en la watchlist'}"}
            elif accion == "listar":
                wl = obtener_watchlist()
                if wl:
                    resultado = {"ok": True, "data": [{"ticker": r[0], "precio_alerta": r[1], "notas": r[2]} for r in wl]}
                else:
                    resultado = {"ok": True, "data": "La watchlist está vacía"}
            else:
                resultado = {"ok": False, "error": f"Acción desconocida para manage_watchlist: {accion}"}

        # ── Alertas ──
        elif nombre == "manage_alerts":
            accion = inputs["accion"]
            if accion == "crear":
                ticker = inputs.get("ticker", "").upper()
                precio = inputs.get("precio")
                tipo = inputs.get("tipo", "minimo")
                if not ticker or precio is None:
                    return "Error: se necesita ticker y precio para crear alerta"
                crear_alerta(ticker, precio, tipo)
                resultado = {"ok": True, "data": f"✅ Alerta creada: avisar si {ticker} {'baja de' if tipo == 'minimo' else 'sube a'} ${precio}"}
            elif accion == "eliminar":
                alerta_id = inputs.get("alerta_id")
                if alerta_id is None:
                    return "Error: se necesita alerta_id para eliminar"
                ok = desactivar_alerta(alerta_id)
                resultado = {"ok": True, "data": f"{'✅ Alerta #' + str(alerta_id) + ' desactivada' if ok else '⚠️ No se encontró la alerta'}"}
            elif accion == "listar":
                alertas = obtener_alertas_activas()
                if alertas:
                    resultado = {"ok": True, "data": [{"id": a[0], "ticker": a[1], "precio_objetivo": a[2], "tipo": a[3]} for a in alertas]}
                else:
                    resultado = {"ok": True, "data": "No hay alertas activas"}
            else:
                resultado = {"ok": False, "error": f"Acción desconocida para manage_alerts: {accion}"}

        # ── Alertas de porcentaje ──
        elif nombre == "manage_pct_alerts":
            accion = inputs["accion"]
            if accion == "crear":
                ticker = inputs.get("ticker", "").upper()
                umbral_pct = inputs.get("umbral_pct")
                direccion = inputs.get("direccion", "ambas")
                referencia = inputs.get("referencia", "dia")
                avg_cost_manual = inputs.get("avg_cost_manual")
                if not ticker or umbral_pct is None:
                    return "Error: se necesita ticker y umbral_pct para crear la alerta"
                crear_alerta_pct(ticker, umbral_pct, direccion, referencia, avg_cost_manual)
                ref_str = "hoy vs cierre anterior" if referencia == "dia" else "desde tu precio de compra"
                aviso = ""
                if referencia == "compra" and avg_cost_manual is None:
                    aviso = " ⚠️ No me diste tu precio de compra y Wallbit no lo expone — esta alerta no va a poder dispararse hasta que me lo pases."
                resultado = {"ok": True, "data": f"✅ Alerta creada: avisar si {ticker} se mueve {direccion} {umbral_pct}% ({ref_str}).{aviso}"}
            elif accion == "eliminar":
                alerta_id = inputs.get("alerta_id")
                if alerta_id is None:
                    return "Error: se necesita alerta_id para eliminar"
                ok = desactivar_alerta_pct(alerta_id)
                resultado = {"ok": True, "data": f"{'✅ Alerta #' + str(alerta_id) + ' desactivada' if ok else '⚠️ No se encontró la alerta'}"}
            elif accion == "listar":
                alertas_pct = obtener_alertas_pct_activas()
                if alertas_pct:
                    resultado = {"ok": True, "data": [
                        {
                            "id": a[0], "ticker": a[1], "umbral_pct": a[2], "direccion": a[3],
                            "referencia": a[4], "avg_cost_manual": a[5],
                            "funcional": a[4] == "dia" or a[5] is not None
                        }
                        for a in alertas_pct
                    ]}
                else:
                    resultado = {"ok": True, "data": "No hay alertas de porcentaje activas"}
            else:
                resultado = {"ok": False, "error": f"Acción desconocida para manage_pct_alerts: {accion}"}

        # ── Presupuesto ──
        elif nombre == "manage_budget":
            accion = inputs["accion"]
            if accion == "crear":
                categoria = inputs.get("categoria")
                limite = inputs.get("limite_usd")
                if not categoria or limite is None:
                    return "Error: se necesita categoría y límite_usd"
                crear_presupuesto(categoria, limite)
                resultado = {"ok": True, "data": f"✅ Presupuesto '{categoria}': ${limite}/mes"}
            elif accion == "listar":
                presupuestos = obtener_presupuestos()
                if presupuestos:
                    resultado = {"ok": True, "data": presupuestos}
                else:
                    resultado = {"ok": True, "data": "No hay presupuestos configurados"}
            elif accion == "actualizar_gasto":
                categoria = inputs.get("categoria")
                monto = inputs.get("monto_adicional")
                if not categoria or monto is None:
                    return "Error: se necesita categoría y monto_adicional"
                actualizar_gasto_presupuesto(categoria, monto)
                resultado = {"ok": True, "data": f"✅ Sumado ${monto} al gasto de '{categoria}'"}
            else:
                resultado = {"ok": False, "error": f"Acción desconocida para manage_budget: {accion}"}

        # ── Metas ──
        elif nombre == "manage_goals":
            accion = inputs["accion"]
            if accion == "crear":
                nombre_meta = inputs.get("nombre")
                objetivo = inputs.get("objetivo_usd")
                if not nombre_meta or objetivo is None:
                    return "Error: se necesita nombre y objetivo_usd"
                crear_meta(nombre_meta, objetivo, inputs.get("fecha_limite"))
                resultado = {"ok": True, "data": f"✅ Meta '{nombre_meta}': ${objetivo}"}
            elif accion == "listar":
                metas = obtener_metas()
                if metas:
                    resultado = {"ok": True, "data": metas}
                else:
                    resultado = {"ok": True, "data": "No hay metas configuradas"}
            elif accion == "actualizar_progreso":
                nombre_meta = inputs.get("nombre")
                actual = inputs.get("actual_usd")
                if not nombre_meta or actual is None:
                    return "Error: se necesita nombre y actual_usd"
                actualizar_progreso_meta(nombre_meta, actual)
                resultado = {"ok": True, "data": f"✅ Progreso de '{nombre_meta}' actualizado a ${actual}"}
            else:
                resultado = {"ok": False, "error": f"Acción desconocida para manage_goals: {accion}"}

        # ── Configuración ──
        elif nombre == "save_config":
            accion = inputs["accion"]
            clave = inputs["clave"]
            if accion == "guardar":
                valor = inputs.get("valor")
                if valor is None:
                    return "Error: se necesita un valor para guardar"
                guardar_config(clave, str(valor))
                resultado = {"ok": True, "data": f"✅ Guardado: {clave} = {valor}"}
            elif accion == "leer":
                valor = obtener_config(clave)
                resultado = {"ok": True, "data": {clave: valor if valor else "no configurado"}}
            else:
                resultado = {"ok": False, "error": f"Acción desconocida para save_config: {accion}"}

        # ── Diario de trading ──
        elif nombre == "trading_diary":
            accion = inputs["accion"]
            if accion == "guardar":
                ticker = inputs.get("ticker", "")
                accion_trade = inputs.get("accion_trade", "")
                precio = inputs.get("precio", 0)
                monto = inputs.get("monto", 0)
                razonamiento = inputs.get("razonamiento", "")
                sesgo = inputs.get("sesgo", "")
                guardar_trade_diario(ticker, accion_trade, precio, monto, razonamiento, sesgo)
                resultado = {"ok": True, "data": "✅ Entrada guardada en el diario de trading"}
            elif accion == "leer":
                limite = inputs.get("limite", 10)
                entradas = obtener_diario_trading(limite)
                if entradas:
                    resultado = {"ok": True, "data": [
                        {"fecha": e[0], "ticker": e[1], "accion": e[2], "precio": e[3], "monto": e[4], "razonamiento": e[5]}
                        for e in entradas
                    ]}
                else:
                    resultado = {"ok": True, "data": "El diario de trading está vacío"}
            else:
                resultado = {"ok": False, "error": f"Acción desconocida para trading_diary: {accion}"}

        elif nombre == "yf_info":
            resultado = market_data.yf_get_info(inputs["ticker"])
        elif nombre == "yf_history":
            resultado = market_data.yf_get_history(inputs["ticker"], inputs.get("period", "1y"))
        elif nombre == "yf_financials":
            resultado = market_data.yf_get_financials(inputs["ticker"])
        elif nombre == "yf_insiders":
            resultado = market_data.yf_get_insiders(inputs["ticker"])
        elif nombre == "yf_dividends":
            resultado = market_data.yf_get_dividends(inputs["ticker"])
        elif nombre == "fred_macro":
            resultado = market_data.fred_get_series(inputs["serie"], inputs.get("observaciones", 12))
        elif nombre == "sec_filings":
            resultado = market_data.sec_get_filings(inputs["company"], inputs.get("form_type", "10-K"), inputs.get("limit", 3))
        elif nombre == "sec_facts":
            resultado = market_data.sec_get_company_facts(inputs["ticker"])
        elif nombre == "sec_busqueda_texto":
            resultado = market_data.sec_search_fulltext(
                query=inputs["query"],
                ticker=inputs.get("ticker"),
                form_type=inputs.get("form_type"),
                limit=inputs.get("limit", 10)
            )

        elif nombre == "yf_earnings_calendar":
            resultado = market_data.yf_get_earnings_calendar(inputs["ticker"])

        elif nombre == "check_earnings_upcoming":
            resultado = market_data.check_earnings_upcoming(
                inputs["tickers"],
                inputs.get("days", 14)
            )

        # ── Decision Log ──
        elif nombre == "decision_log":
            accion = inputs["accion"]
            ticker = inputs["ticker"].upper()
            if accion == "guardar":
                veredicto = inputs.get("veredicto", "neutral")
                razonamiento = inputs.get("razonamiento", "")
                precio = inputs.get("precio_momento", 0)
                guardar_decision(ticker, precio, veredicto, razonamiento)
                resultado = {"ok": True, "data": f"Decision guardada: {ticker} — {veredicto}"}
            elif accion == "leer":
                historial = obtener_decisiones_ticker(ticker, limite=5)
                if historial:
                    resultado = {"ok": True, "data": historial}
                else:
                    resultado = {"ok": True, "data": f"Sin historial previo de decisiones para {ticker}"}
            else:
                resultado = {"ok": False, "error": f"Acción desconocida para decision_log: {accion}"}

        # ── Bull vs Bear ──
        elif nombre == "bull_bear_analysis":
            ticker = inputs["ticker"].upper()
            contexto = inputs.get("contexto", "")
            resultado = {"ok": True, "data": _ejecutar_bull_bear(ticker, contexto)}

        # ── Sentimiento social (StockTwits) ──
        elif nombre == "sentimiento_social":
            resultado = social_sentiment.stocktwits_sentiment(
                inputs["ticker"],
                inputs.get("limit", 30)
            )

        # ── Reddit ──
        elif nombre == "reddit_sentiment":
            resultado = reddit_client.search_reddit(
                inputs["query"],
                inputs.get("subreddits"),
                inputs.get("limit", 10)
            )

        # ── Búsqueda global de noticias ──
        elif nombre == "busqueda_global":
            resultado = global_search.busqueda_global(
                query=inputs["query"],
                pais=inputs.get("pais"),
                idioma=inputs.get("idioma"),
                count=inputs.get("count", 10)
            )

        # ── Lectura de páginas web completas ──
        elif nombre == "leer_pagina_web":
            resultado = web_reader.fetch_article_text(
                inputs["url"],
                inputs.get("max_chars", 4000)
            )

        # ── Screener de tesis ──
        elif nombre == "thesis_screener":
            resultado = market_data.screener_filtrar(
                tickers=inputs["tickers"],
                min_revenue_growth=inputs.get("min_revenue_growth"),
                max_pe=inputs.get("max_pe"),
                min_market_cap=inputs.get("min_market_cap"),
                max_market_cap=inputs.get("max_market_cap"),
                min_profit_margin=inputs.get("min_profit_margin"),
                max_debt_to_equity=inputs.get("max_debt_to_equity")
            )

        else:
            return f"Herramienta desconocida: {nombre}"

        if resultado.get("ok"):
            return json.dumps(resultado["data"], ensure_ascii=False, indent=2)
        else:
            return f"Error: {resultado.get('error', 'Error desconocido')}"

    except Exception as e:
        registrar_bitacora("error", f"Error en herramienta {nombre}: {str(e)}")
        return f"Error ejecutando {nombre}: {str(e)}"

# ─── Sistema prompt ────────────────────────────────────────────────────────────

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


SYSTEM_PROMPT = """Agente financiero de Mateo. Buy & hold, largo plazo.

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

5. NÚMEROS (resumido): Solo 4 métricas — revenue del último año, crecimiento YoY, si es rentable o quema caja, y deuda. Nada más. Si el negocio no convence, los números no importan.

SENTIMIENTO SOCIAL — solo si el usuario lo pide explícitamente ("qué dice la gente", "hype", "sentimiento del mercado", "qué dice reddit"):
Usar sentimiento_social (StockTwits) para el pulso rápido Bullish/Bearish, y reddit_sentiment cuando quieran más contexto o discusión (menciona el score/upvotes de cada post para que el usuario juzgue qué tan respaldado está). Aclarar SIEMPRE que es sentimiento de retail/comunidad, no un indicador fundamental — sirve para detectar euforia o pánico excesivo, no para tomar la decisión de inversión en sí.

BÚSQUEDA DE RIESGOS EN FILINGS — cuando pidan "qué dice el 10-K sobre X riesgo", "buscá menciones de [tema] en los reportes", o quieran validar un riesgo puntual (cadena de suministro, concentración de clientes, litigios):
Usar sec_busqueda_texto con el ticker y la frase exacta a buscar (ej: "supply chain disruption", "customer concentration"). Esto busca DENTRO del contenido real de los documentos, no solo lista cuáles existen — mucho más preciso que sec_filings para encontrar un riesgo específico.

EARNINGS ANALYSIS — análisis post-earnings:
Usá brave_search para buscar el earnings call. Estructura: beat/miss vs consenso, qué dijo el CEO sobre productos y crecimiento futuro, si la tesis de largo plazo sigue intacta.

EARNINGS PREVIEW — antes de que reporte:
Usá brave_search. Qué espera el mercado, qué métricas mirar, si hay catalizadores de producto o contratos que puedan sorprender.

IDEA GENERATION — cuando pidan ideas:
5 empresas con: qué hacen en una línea, por qué tienen potencial de largo plazo, en qué etapa están (temprana/consolidada), y el riesgo principal.

SECTOR OVERVIEW — análisis de un sector:
Qué problema resuelve el sector, quiénes son los líderes y por qué, qué empresa emergente vale la pena seguir, qué podría destruir el sector en 5 años.

THESIS TRACKER — armar o revisar una tesis:
1) Por qué esta empresa en una línea, 2) Qué tiene que ser verdad para que funcione, 3) Qué señal concreta me diría que me equivoqué, 4) Catalizadores próximos 6 meses.

MORNING NOTE — morning briefing:
Usá get_portfolio_summary + brave_search. Qué pasó en el mercado, alguna noticia de mis empresas, dato macro relevante, 1 acción concreta.

BULL VS BEAR — cuando pidan debate o "convenceme":
Usar bull_bear_analysis. Dos llamadas separadas, argumentos opuestos, veredicto es del usuario. Al terminar, sugerir guardar la decisión en decision_log.

SCREENER DE TESIS — cuando el usuario describa una tesis y pida ideas/candidatos (ej: "empresas de defensa con contratos nuevos", "penny stocks de biotech con catalizador cerca"):
1. brave_search (1-2 búsquedas) para encontrar 8-15 empresas candidatas que mencionen medios o análisis recientes sobre esa tesis.
2. Extraer los tickers de esos candidatos (si no es obvio el ticker, usar get_asset o yf_info para confirmarlo antes de pasarlo al filtro).
3. Llamar thesis_screener con esos tickers. Definir criterios numéricos razonables según lo que pidió el usuario (si no especificó, usar defaults: min_revenue_growth 0.15, sin límite de market cap salvo que digan "chica/mediana/grande").
4. Presentar el TOP 5 de los que cumplieron: ticker, por qué encaja con la tesis (1 línea), la métrica que lo valida, y el riesgo principal. Mencionar cuántos candidatos fueron descartados y por qué (breve).

RESEARCH PROFUNDO — cuando el usuario pida "metete en la web de [empresa]", "buscá en diarios locales/foros del rubro", o el análisis normal se quede corto:
1. Identificar primero el país y el rubro de la empresa (dónde cotiza, dónde tiene sede, industria). Esto define el código de país/idioma a usar — NO asumir que son medios argentinos salvo que la empresa opere en Argentina.
2. Web oficial de la empresa: buscar con brave_search "[empresa] official website news OR newsroom OR investor relations" y usar leer_pagina_web sobre la URL que encuentre.
3. Prensa local/global: usar busqueda_global con el código ISO de país e idioma correspondiente (ej empresa australiana → pais="AU" idioma="en", empresa alemana → pais="DE" idioma="de", empresa brasilera → pais="BR" idioma="pt"). Esto trae medios reales de ese mercado (Google News + GDELT), no solo lo que indexa brave_search en inglés.
4. Una vez identificada la URL relevante (medio local, foro especializado, o sitio oficial), usar leer_pagina_web para sacar el texto completo — no te quedes solo con el título.
5. Máximo 2-3 leer_pagina_web por consulta para no gastar tokens de más. Priorizar la fuente más reciente y relevante, en el idioma que sea (traducir el hallazgo al responder)."""

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

    # Loop de tool use: Claude puede llamar múltiples herramientas en secuencia
    MAX_ITERACIONES = 10
    for _ in range(MAX_ITERACIONES):
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=3072,
                system=SYSTEM_PROMPT,
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
