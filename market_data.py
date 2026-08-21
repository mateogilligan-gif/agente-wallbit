"""
market_data.py — Fuentes de datos gratuitas: yfinance, FRED, SEC EDGAR
"""
import json
import re
import requests
from datetime import datetime, timedelta

# ─── yfinance ─────────────────────────────────────────────────────────────────

def yf_get_info(ticker: str) -> dict:
    """Fundamentals, precio, dividendos, P/E, 52w high/low, market cap."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info
        keys = [
            "shortName", "sector", "industry", "marketCap", "trailingPE",
            "forwardPE", "priceToBook", "trailingEps", "forwardEps",
            "dividendYield", "payoutRatio", "beta", "fiftyTwoWeekHigh",
            "fiftyTwoWeekLow", "currentPrice", "targetMeanPrice",
            "recommendationMean", "recommendationKey", "numberOfAnalystOpinions",
            "totalRevenue", "grossMargins", "operatingMargins", "profitMargins",
            "returnOnEquity", "debtToEquity", "freeCashflow", "totalCash",
            "totalDebt", "revenueGrowth", "earningsGrowth"
        ]
        result = {k: info.get(k) for k in keys if info.get(k) is not None}
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def yf_get_history(ticker: str, period: str = "1y") -> dict:
    """Historial de precios. period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period=period)
        if hist.empty:
            return {"ok": False, "error": "Sin datos"}
        result = {
            "inicio": str(hist.index[0].date()),
            "fin": str(hist.index[-1].date()),
            "precio_inicio": round(float(hist["Close"].iloc[0]), 2),
            "precio_actual": round(float(hist["Close"].iloc[-1]), 2),
            "maximo": round(float(hist["High"].max()), 2),
            "minimo": round(float(hist["Low"].min()), 2),
            "variacion_pct": round((float(hist["Close"].iloc[-1]) / float(hist["Close"].iloc[0]) - 1) * 100, 2),
            "volumen_promedio": int(hist["Volume"].mean())
        }
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def yf_get_financials(ticker: str) -> dict:
    """Estado de resultados anual: ingresos, utilidad, EBITDA."""
    try:
        import yfinance as yf
        import pandas as pd
        t = yf.Ticker(ticker)
        inc = t.financials
        if inc is None or inc.empty:
            return {"ok": False, "error": "Sin datos financieros"}
        rows = ["Total Revenue", "Gross Profit", "EBITDA", "Net Income", "Operating Income"]
        result = {}
        for row in rows:
            if row in inc.index:
                result[row] = {str(col.year): int(inc.loc[row, col]) for col in inc.columns if pd.notna(inc.loc[row, col])}
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def yf_get_insiders(ticker: str) -> dict:
    """Compras y ventas de insiders (directivos)."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        insider = t.insider_transactions
        if insider is None or insider.empty:
            return {"ok": False, "error": "Sin datos de insiders"}
        insider = insider.head(15)
        result = []
        for _, row in insider.iterrows():
            result.append({
                "fecha": str(row.get("startDate", ""))[:10],
                "nombre": str(row.get("filerName", "")),
                "cargo": str(row.get("filerRelation", "")),
                "accion": str(row.get("transactionText", "")),
                "acciones": int(row.get("shares", 0)),
                "valor_usd": int(row.get("value", 0)) if row.get("value") else None
            })
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def yf_get_dividends(ticker: str) -> dict:
    """Historial de dividendos de los últimos 5 años."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        divs = t.dividends
        if divs is None or divs.empty:
            return {"ok": True, "data": "Esta empresa no paga dividendos"}
        divs = divs[divs.index >= (datetime.now() - timedelta(days=1825))]
        result = [{"fecha": str(d.date()), "monto": round(float(v), 4)} for d, v in divs.items()]
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def yf_get_earnings_calendar(ticker: str) -> dict:
    """Próxima fecha de earnings y estimados de EPS/Revenue del consenso."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        cal = t.calendar
        info = t.info

        if cal is None or (hasattr(cal, 'empty') and cal.empty):
            return {"ok": False, "error": f"Sin datos de earnings para {ticker}"}

        result = {}

        # calendar puede ser dict o DataFrame según versión de yfinance
        if isinstance(cal, dict):
            earnings_dates = cal.get("Earnings Date", [])
            if earnings_dates:
                if isinstance(earnings_dates, list):
                    fecha = str(earnings_dates[0])[:10]
                else:
                    fecha = str(earnings_dates)[:10]
                result["fecha_earnings"] = fecha
            result["eps_estimado_avg"] = cal.get("Earnings Average")
            result["eps_estimado_low"] = cal.get("Earnings Low")
            result["eps_estimado_high"] = cal.get("Earnings High")
            result["revenue_estimado_avg"] = cal.get("Revenue Average")
        else:
            # DataFrame: columnas son las fechas, filas son las métricas
            try:
                cols = [str(c)[:10] for c in cal.columns.tolist()]
                result["fecha_earnings"] = cols[0] if cols else None
                if "Earnings Average" in cal.index:
                    result["eps_estimado_avg"] = float(cal.loc["Earnings Average"].iloc[0])
                if "Revenue Average" in cal.index:
                    result["revenue_estimado_avg"] = float(cal.loc["Revenue Average"].iloc[0])
            except Exception:
                pass

        # Enriquecer con datos del info
        result["nombre"] = info.get("shortName", ticker)
        result["eps_ultimo_real"] = info.get("trailingEps")
        result["eps_proximo_estimado"] = info.get("forwardEps")
        result["precio_actual"] = info.get("currentPrice")

        if not result.get("fecha_earnings"):
            return {"ok": False, "error": f"No hay fecha de earnings próxima para {ticker}"}

        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_earnings_upcoming(tickers: list, days: int = 14) -> dict:
    """Verifica cuáles de los tickers dados tienen earnings en los próximos N días."""
    from datetime import date, timedelta
    hoy = date.today()
    limite = hoy + timedelta(days=days)
    upcoming = []

    for ticker in tickers:
        try:
            res = yf_get_earnings_calendar(ticker)
            if res["ok"] and res["data"].get("fecha_earnings"):
                fecha_str = res["data"]["fecha_earnings"]
                fecha = date.fromisoformat(fecha_str[:10])
                if hoy <= fecha <= limite:
                    upcoming.append({
                        "ticker": ticker,
                        "nombre": res["data"].get("nombre", ticker),
                        "fecha": fecha_str[:10],
                        "dias_faltan": (fecha - hoy).days,
                        "eps_estimado": res["data"].get("eps_estimado_avg"),
                        "revenue_estimado": res["data"].get("revenue_estimado_avg"),
                        "precio_actual": res["data"].get("precio_actual")
                    })
        except Exception:
            continue

    upcoming.sort(key=lambda x: x["fecha"])
    return {"ok": True, "data": upcoming if upcoming else []}


def screener_filtrar(
    tickers: list,
    min_revenue_growth: float = None,
    max_pe: float = None,
    min_market_cap: float = None,
    max_market_cap: float = None,
    min_profit_margin: float = None,
    max_debt_to_equity: float = None
) -> dict:
    """
    Screener básico: toma una lista de tickers candidatos (encontrados vía brave_search)
    y los valida/filtra con datos reales de yfinance. Devuelve solo los que cumplen
    los criterios, rankeados por crecimiento de revenue descendente.

    Criterios (todos opcionales, None = sin filtro):
    - min_revenue_growth: ej 0.15 = mínimo 15% YoY
    - max_pe: P/E máximo aceptable
    - min_market_cap / max_market_cap: en USD
    - min_profit_margin: ej 0.10 = mínimo 10% margen neto
    - max_debt_to_equity: deuda/patrimonio máximo
    """
    resultados = []
    descartados = []

    for ticker in tickers:
        ticker = ticker.strip().upper()
        if not ticker:
            continue
        info = yf_get_info(ticker)
        if not info["ok"]:
            descartados.append({"ticker": ticker, "razon": "sin datos en yfinance"})
            continue

        d = info["data"]
        revenue_growth = d.get("revenueGrowth")
        pe = d.get("trailingPE")
        market_cap = d.get("marketCap")
        profit_margin = d.get("profitMargins")
        debt_to_equity = d.get("debtToEquity")

        motivos_descarte = []
        if min_revenue_growth is not None and (revenue_growth is None or revenue_growth < min_revenue_growth):
            motivos_descarte.append(f"revenue growth {revenue_growth} < {min_revenue_growth}")
        if max_pe is not None and (pe is None or pe > max_pe):
            motivos_descarte.append(f"P/E {pe} > {max_pe}")
        if min_market_cap is not None and (market_cap is None or market_cap < min_market_cap):
            motivos_descarte.append(f"market cap {market_cap} < {min_market_cap}")
        if max_market_cap is not None and (market_cap is None or market_cap > max_market_cap):
            motivos_descarte.append(f"market cap {market_cap} > {max_market_cap}")
        if min_profit_margin is not None and (profit_margin is None or profit_margin < min_profit_margin):
            motivos_descarte.append(f"margen {profit_margin} < {min_profit_margin}")
        if max_debt_to_equity is not None and (debt_to_equity is None or debt_to_equity > max_debt_to_equity):
            motivos_descarte.append(f"deuda/equity {debt_to_equity} > {max_debt_to_equity}")

        if motivos_descarte:
            descartados.append({"ticker": ticker, "razon": "; ".join(motivos_descarte)})
            continue

        resultados.append({
            "ticker": ticker,
            "nombre": d.get("shortName", ticker),
            "sector": d.get("sector"),
            "industry": d.get("industry"),
            "market_cap": market_cap,
            "pe": pe,
            "revenue_growth": revenue_growth,
            "profit_margin": profit_margin,
            "debt_to_equity": debt_to_equity,
            "precio_actual": d.get("currentPrice"),
            "recomendacion_analistas": d.get("recommendationKey")
        })

    resultados.sort(key=lambda x: x.get("revenue_growth") or -999, reverse=True)

    return {
        "ok": True,
        "data": {
            "cumplen_criterios": resultados,
            "descartados": descartados
        }
    }


def yf_get_options(ticker: str) -> dict:
    """Fechas de vencimiento de opciones disponibles."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        expirations = t.options
        if not expirations:
            return {"ok": False, "error": "Sin opciones disponibles"}
        # Traer la cadena de opciones más próxima
        chain = t.option_chain(expirations[0])
        calls_top = chain.calls.nlargest(5, "openInterest")[["strike", "lastPrice", "openInterest", "impliedVolatility"]].to_dict("records")
        puts_top = chain.puts.nlargest(5, "openInterest")[["strike", "lastPrice", "openInterest", "impliedVolatility"]].to_dict("records")
        return {"ok": True, "data": {
            "vencimiento_proximo": expirations[0],
            "calls_mayor_oi": calls_top,
            "puts_mayor_oi": puts_top
        }}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ─── FRED (Federal Reserve Economic Data) ─────────────────────────────────────

FRED_BASE = "https://api.stlouisfed.org/fred"
FRED_KEY = "abcdefghijklmnop"  # FRED permite acceso sin key para series públicas via alternativa

FRED_SERIES = {
    "inflacion_cpi": "CPIAUCSL",
    "inflacion_pce": "PCEPI",
    "tasa_fed": "FEDFUNDS",
    "desempleo": "UNRATE",
    "pib": "GDP",
    "rendimiento_10y": "GS10",
    "rendimiento_2y": "GS2",
    "indice_dolar": "DTWEXBGS",
    "ventas_retail": "RSAFS",
    "confianza_consumidor": "UMCSENT"
}

def fred_get_series(serie: str, observaciones: int = 12) -> dict:
    """
    Obtiene datos macroeconómicos de la Fed.
    serie puede ser: inflacion_cpi, tasa_fed, desempleo, pib, rendimiento_10y,
                     rendimiento_2y, indice_dolar, ventas_retail, confianza_consumidor
    """
    try:
        series_id = FRED_SERIES.get(serie.lower(), serie.upper())
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        lines = r.text.strip().split("\n")
        data_lines = [l for l in lines[1:] if l and "." in l][-observaciones:]
        result = []
        for line in data_lines:
            parts = line.split(",")
            if len(parts) == 2 and parts[1].strip() != ".":
                result.append({"fecha": parts[0].strip(), "valor": float(parts[1].strip())})
        if not result:
            return {"ok": False, "error": "Sin datos disponibles"}
        ultimo = result[-1]
        anterior = result[-2] if len(result) >= 2 else None
        return {"ok": True, "data": {
            "serie": serie,
            "ultimo_valor": ultimo["valor"],
            "ultima_fecha": ultimo["fecha"],
            "variacion": round(ultimo["valor"] - anterior["valor"], 4) if anterior else None,
            "historial": result
        }}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ─── SEC EDGAR ────────────────────────────────────────────────────────────────

EDGAR_FULLTEXT_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_HEADERS = {"User-Agent": "agente-wallbit mateo@wallbit.io"}

_cik_cache = None


def _get_cik(ticker_o_nombre: str) -> str:
    """
    Resuelve un ticker o nombre de empresa a su CIK (identificador de SEC),
    usando el archivo público company_tickers.json (se cachea en memoria
    después de la primera consulta para no repetir la descarga).
    """
    global _cik_cache
    try:
        if _cik_cache is None:
            r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=EDGAR_HEADERS, timeout=15)
            r.raise_for_status()
            _cik_cache = r.json()

        clave = ticker_o_nombre.strip().upper()

        # 1) match exacto de ticker
        for item in _cik_cache.values():
            if item.get("ticker", "").upper() == clave:
                return str(item["cik_str"]).zfill(10)

        # 2) match parcial de nombre de empresa
        for item in _cik_cache.values():
            if ticker_o_nombre.lower() in item.get("title", "").lower():
                return str(item["cik_str"]).zfill(10)

        return None
    except Exception:
        return None


def sec_get_filings(company: str, form_type: str = "10-K", limit: int = 3) -> dict:
    """
    Lista los filings más recientes de una empresa en SEC EDGAR (por nombre o ticker).
    form_type: 10-K (anual), 10-Q (trimestral), 8-K (eventos), DEF 14A (proxy)
    """
    try:
        r = requests.get(
            "https://www.sec.gov/cgi-bin/browse-edgar",
            params={
                "company": company, "CIK": "", "type": form_type, "dateb": "",
                "owner": "include", "count": limit, "search_text": "",
                "action": "getcompany", "output": "atom"
            },
            headers=EDGAR_HEADERS,
            timeout=10
        )

        if r.status_code == 200 and "<entry>" in r.text:
            entries = re.findall(r'<entry>(.*?)</entry>', r.text, re.DOTALL)[:limit]
            results = []
            for entry in entries:
                title = re.search(r'<title>(.*?)</title>', entry)
                updated = re.search(r'<updated>(.*?)</updated>', entry)
                link = re.search(r'<link[^>]+href="([^"]+)"', entry)
                results.append({
                    "titulo": title.group(1) if title else "",
                    "fecha": updated.group(1)[:10] if updated else "",
                    "url": link.group(1) if link else ""
                })
            return {"ok": True, "data": results}
        return {"ok": False, "error": "No se encontraron filings"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def sec_search_fulltext(query: str, ticker: str = None, form_type: str = None, limit: int = 10) -> dict:
    """
    Búsqueda de TEXTO COMPLETO real dentro del contenido de los filings de SEC EDGAR
    (usa el EDGAR Full-Text Search System oficial). Permite buscar una frase o
    palabra clave específica DENTRO de los documentos, no solo listarlos.

    Ejemplos de uso: buscar "supply chain" dentro de los 10-K de una empresa,
    o "customer concentration" en toda la base para ver qué empresas lo mencionan.

    query: frase o palabra clave a buscar dentro de los documentos
    ticker: opcional, restringe la búsqueda a una sola empresa
    form_type: opcional, ej "10-K", "10-Q", "8-K"
    """
    try:
        params = {"q": f'"{query}"' if " " in query else query}
        if form_type:
            params["forms"] = form_type

        empresa_filtrada = None
        if ticker:
            cik = _get_cik(ticker)
            if cik:
                params["ciks"] = cik
                empresa_filtrada = ticker.upper()

        r = requests.get(EDGAR_FULLTEXT_URL, params=params, headers=EDGAR_HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()

        hits = data.get("hits", {}).get("hits", [])[:limit]
        total = data.get("hits", {}).get("total", {}).get("value", 0)

        resultados = []
        for h in hits:
            src = h.get("_source", {})
            id_field = h.get("_id", "")
            accession, _, filename = id_field.partition(":")
            accession_sin_guiones = accession.replace("-", "")

            display_names = src.get("display_names", [])
            cik_match = re.search(r"\((\d+)\)", display_names[0]) if display_names else None
            cik_num = cik_match.group(1) if cik_match else None

            url_doc = None
            if cik_num and accession_sin_guiones and filename:
                url_doc = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{accession_sin_guiones}/{filename}"

            resultados.append({
                "empresa": display_names[0] if display_names else "",
                "form_type": src.get("form_type") or src.get("file_type"),
                "fecha": src.get("file_date"),
                "url": url_doc
            })

        return {
            "ok": True,
            "data": {
                "query": query,
                "empresa_filtrada": empresa_filtrada,
                "total_encontrados": total,
                "resultados": resultados
            }
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

def sec_get_company_facts(ticker: str) -> dict:
    """Obtiene datos financieros clave del CIK de la empresa en SEC."""
    try:
        # Primero obtener CIK
        cik_r = requests.get(
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=&CIK={ticker}&type=&dateb=&owner=include&count=1&search_text=&output=atom",
            headers=EDGAR_HEADERS, timeout=10
        )
        cik_match = re.search(r'/cgi-bin/browse-edgar\?action=getcompany&CIK=(\d+)', cik_r.text)
        if not cik_match:
            return {"ok": False, "error": f"No se encontró CIK para {ticker}"}

        cik = cik_match.group(1).zfill(10)
        facts_r = requests.get(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
            headers=EDGAR_HEADERS, timeout=15
        )
        facts_r.raise_for_status()
        facts = facts_r.json()

        # Extraer métricas clave
        us_gaap = facts.get("facts", {}).get("us-gaap", {})
        metrics = {}
        keys_wanted = {
            "Revenues": "ingresos",
            "NetIncomeLoss": "utilidad_neta",
            "EarningsPerShareBasic": "eps_basico",
            "Assets": "activos_totales",
            "LiabilitiesAndStockholdersEquity": "pasivos_y_patrimonio",
            "ResearchAndDevelopmentExpense": "i_mas_d",
            "OperatingIncomeLoss": "ingreso_operativo"
        }
        for gaap_key, label in keys_wanted.items():
            if gaap_key in us_gaap:
                units = us_gaap[gaap_key].get("units", {})
                usd_data = units.get("USD", units.get("shares", []))
                if usd_data:
                    annual = [x for x in usd_data if x.get("form") == "10-K"]
                    if annual:
                        last = sorted(annual, key=lambda x: x.get("end", ""))[-1]
                        metrics[label] = {"valor": last.get("val"), "periodo": last.get("end")}

        return {"ok": True, "data": {"ticker": ticker, "cik": cik, "metricas": metrics}}
    except Exception as e:
        return {"ok": False, "error": str(e)}
