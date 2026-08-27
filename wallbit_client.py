import requests
import os
import json
import re
from typing import Optional

# Claves que NUNCA son un ticker, aunque aparezcan como clave de nivel raíz
# en la respuesta de Wallbit (evita que el parser las confunda con posiciones).
CLAVES_NO_TICKER = {
    "cash", "balance", "available", "amount", "total", "total_value",
    "currency", "updated_at", "timestamp", "created_at", "date", "id",
    "user_id", "account_id", "status", "ok", "error", "message"
}

WALLBIT_BASE_URL = "https://mcp.wallbit.io/mcp"
_initialized = False

def get_headers():
    return {
        "X-API-Key": os.getenv("WALLBIT_API_KEY"),
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"  # MCP sobre HTTP/SSE requiere ambos
    }

def _initialize():
    """Inicializa la sesión MCP (handshake requerido por el protocolo)."""
    global _initialized
    if _initialized:
        return True
    payload = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "wallbit-agent", "version": "1.0.0"}
        }
    }
    try:
        response = requests.post(WALLBIT_BASE_URL, json=payload, headers=get_headers(), timeout=10)
        response.raise_for_status()
        _initialized = True
        return True
    except Exception as e:
        _initialized = False  # Siempre resetear para reintentar en el próximo mensaje
        return False

def _call_tool(tool_name: str, params: Optional[dict] = None) -> dict:
    """Llama a una herramienta del MCP de Wallbit."""
    if params is None:
        params = {}

    if not _initialize():
        return {"ok": False, "error": "⚠️ ERROR WALLBIT: No se pudo conectar al servidor MCP"}

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": params
        }
    }
    try:
        response = requests.post(WALLBIT_BASE_URL, json=payload, headers=get_headers(), timeout=15)
        response.raise_for_status()

        # Wallbit MCP responde en formato SSE: "event: message\ndata: {...}\n"
        # response.json() fallaría porque el body no es JSON puro.
        result = None
        for line in response.text.strip().split("\n"):
            if line.startswith("data:"):
                result = json.loads(line[5:].strip())
                break
        if result is None:
            return {"ok": False, "error": "⚠️ ERROR WALLBIT: Respuesta SSE inválida o vacía"}

        if "error" in result:
            return {"ok": False, "error": result["error"].get("message", "Error desconocido de Wallbit")}

        if "result" in result:
            res = result["result"]
            # isError=True significa que la herramienta devolvió un error lógico (ej: Zod validation)
            if res.get("isError"):
                content = res.get("content", [])
                error_text = content[0].get("text", "Error desconocido") if content else "Error desconocido"
                return {"ok": False, "error": f"⚠️ ERROR WALLBIT: {error_text}"}
            # Contenido normal: array de objetos {type, text}
            content = res.get("content", [])
            if content and isinstance(content, list):
                texto = "\n".join([c.get("text", "") for c in content if c.get("type") == "text"])
                return {"ok": True, "data": texto}
            return {"ok": True, "data": res}

        return {"ok": False, "error": "Respuesta inesperada del servidor Wallbit"}

    except requests.exceptions.Timeout:
        return {"ok": False, "error": "⚠️ ERROR WALLBIT: Timeout, el servidor no respondió en 15 segundos"}
    except requests.exceptions.RequestException as e:
        return {"ok": False, "error": f"⚠️ ERROR WALLBIT: Error de conexión — {str(e)}"}

def get_checking_balance() -> dict:
    return _call_tool("get_checking_balance")

def get_stocks_balance() -> dict:
    return _call_tool("get_stocks_balance")

def list_transactions(limit: int = 50) -> dict:
    return _call_tool("list_transactions", {"limit": limit})

def get_asset(ticker: str) -> dict:
    return _call_tool("get_asset", {"ticker": ticker})

def create_trade(ticker: str, side: str, amount: float, order_type: str = "market", price: Optional[float] = None) -> dict:
    """
    Ejecuta una orden. NUNCA llamar sin confirmación explícita del usuario.
    side: 'buy' o 'sell' | order_type: 'market' o 'limit'
    """
    params = {
        "ticker": ticker,
        "side": side,
        "amount": amount,
        "order_type": order_type
    }
    if price is not None and order_type == "limit":
        params["price"] = price
    return _call_tool("create_trade", params)

def _parse_portfolio_text(texto: str) -> list:
    """
    Intenta extraer posiciones del texto que devuelve Wallbit.
    Soporta JSON array, JSON object con positions/stocks/holdings, o texto plano.
    Retorna lista de dicts con: ticker, shares, avg_cost, current_price, market_value, pnl_pct
    """
    posiciones = []
    try:
        data = json.loads(texto)

        # Detectar dónde viven las posiciones
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = (
                data.get("positions") or data.get("stocks") or
                data.get("holdings") or data.get("assets") or
                data.get("portfolio") or data.get("data") or []  # Wallbit usa "data"
            )
            if not items and any(isinstance(v, (int, float, dict)) for v in data.values()):
                # Podría ser {AAPL: {...}, MSFT: {...}} — pero solo tratar una clave
                # como ticker si parece un ticker real (letras/dígitos, corto, no es
                # un campo conocido tipo "cash"/"balance"/"updated_at").
                items = []
                for k, v in data.items():
                    clave_valida = (
                        k.lower() not in CLAVES_NO_TICKER
                        and re.fullmatch(r"[A-Za-z]{1,6}", k) is not None
                    )
                    if not clave_valida:
                        continue
                    if isinstance(v, dict):
                        items.append({"ticker": k, **v})
                    else:
                        items.append({"ticker": k, "market_value": v})
        else:
            items = []

        for item in items:
            if not isinstance(item, dict):
                continue
            ticker = (
                item.get("ticker") or item.get("symbol") or
                item.get("asset") or item.get("name") or ""
            ).upper().strip()
            if not ticker:
                continue
            # Filtrar entradas de cash/moneda que Wallbit incluye mezcladas con acciones
            if ticker in {"USD", "ARS", "EUR", "GBP", "BTC", "ETH", "USDT", "USDC", "BUSD"}:
                continue

            pos = {"ticker": ticker}
            # Cantidad de acciones
            for k in ("shares", "quantity", "qty", "amount", "units", "cantidad"):
                if item.get(k) is not None:
                    try:
                        pos["shares"] = float(item[k])
                    except (ValueError, TypeError):
                        pass
                    break
            # Precio promedio de compra
            for k in ("avg_cost", "average_cost", "cost_basis", "avg_price", "purchase_price", "precio_compra"):
                if item.get(k) is not None:
                    try:
                        pos["avg_cost"] = float(item[k])
                    except (ValueError, TypeError):
                        pass
                    break
            # Precio actual
            for k in ("current_price", "price", "last_price", "market_price", "precio"):
                if item.get(k) is not None:
                    try:
                        pos["current_price"] = float(item[k])
                    except (ValueError, TypeError):
                        pass
                    break
            # Valor de mercado
            for k in ("market_value", "total_value", "value", "valor"):
                if item.get(k) is not None:
                    try:
                        pos["market_value"] = float(item[k])
                    except (ValueError, TypeError):
                        pass
                    break
            # P&L
            for k in ("pnl_pct", "pnl_percent", "return_pct", "gain_loss_pct", "rendimiento"):
                if item.get(k) is not None:
                    try:
                        pos["pnl_pct"] = float(item[k])
                    except (ValueError, TypeError):
                        pass
                    break

            # Calcular lo que falte
            if pos.get("shares") and pos.get("avg_cost") and not pos.get("market_value"):
                if pos.get("current_price"):
                    pos["market_value"] = round(pos["shares"] * pos["current_price"], 2)
            if pos.get("avg_cost") and pos.get("current_price") and not pos.get("pnl_pct"):
                pos["pnl_pct"] = round((pos["current_price"] / pos["avg_cost"] - 1) * 100, 2)

            posiciones.append(pos)

    except (json.JSONDecodeError, Exception):
        # Fallback: texto plano, devolver sin parsear
        pass

    return posiciones


def format_portfolio_summary(checking_res: dict, stocks_res: dict) -> str:
    """
    Formatea el portfolio completo como texto compacto para Claude.
    Reduce tokens al eliminar JSON crudo y presentar solo lo relevante.
    """
    lines = []

    # Saldo en cuenta corriente
    if checking_res.get("ok"):
        raw = checking_res["data"]
        try:
            d = json.loads(raw) if isinstance(raw, str) else raw
            balance = None
            # Formato plano: {"balance": 183.81}
            for clave in ("balance", "available", "amount", "cash"):
                if isinstance(d, dict) and d.get(clave) is not None:
                    balance = d[clave]
                    break
            # Formato anidado de Wallbit: {"data": [{"currency": "USD", "balance": 183.81}]}
            if balance is None and isinstance(d, dict) and isinstance(d.get("data"), list):
                for entry in d["data"]:
                    if isinstance(entry, dict):
                        for clave in ("balance", "available", "amount", "cash"):
                            if entry.get(clave) is not None:
                                balance = entry[clave]
                                break
                    if balance is not None:
                        break
            if balance is None:
                balance = raw
            lines.append(f"CUENTA CORRIENTE: ${balance}")
        except Exception:
            lines.append(f"CUENTA CORRIENTE: {raw}")
    else:
        lines.append(f"CUENTA CORRIENTE: error — {checking_res.get('error')}")

    # Posiciones de inversión
    if stocks_res.get("ok"):
        raw = stocks_res["data"]
        posiciones = _parse_portfolio_text(raw if isinstance(raw, str) else json.dumps(raw))

        if posiciones:
            lines.append(f"\nINVERSIONES ({len(posiciones)} posiciones):")
            total_mv = 0
            for p in posiciones:
                partes = [p["ticker"]]
                if p.get("shares"):
                    partes.append(f"{p['shares']:.4f} acciones")
                if p.get("avg_cost"):
                    partes.append(f"costo ${p['avg_cost']:.2f}")
                if p.get("current_price"):
                    partes.append(f"precio ${p['current_price']:.2f}")
                if p.get("market_value"):
                    partes.append(f"valor ${p['market_value']:.2f}")
                    total_mv += p["market_value"]
                if p.get("pnl_pct") is not None:
                    signo = "+" if p["pnl_pct"] >= 0 else ""
                    partes.append(f"P&L {signo}{p['pnl_pct']:.1f}%")
                lines.append("  " + " | ".join(partes))
            if total_mv:
                lines.append(f"\nTOTAL INVERSIONES: ${total_mv:.2f}")
        else:
            # No se pudo parsear — devolver texto crudo pero limpio
            lines.append(f"\nINVERSIONES:\n{raw}")
    else:
        lines.append(f"\nINVERSIONES: error — {stocks_res.get('error')}")

    return "\n".join(lines)


def get_full_portfolio() -> dict:
    """Obtiene checking + stocks. Llama ambos y devuelve juntos."""
    checking = get_checking_balance()
    stocks = get_stocks_balance()
    return {"checking": checking, "stocks": stocks}


def get_portfolio_summary() -> dict:
    """Portfolio completo formateado y listo para Claude. Ahorra tokens vs llamar por separado."""
    checking = get_checking_balance()
    stocks = get_stocks_balance()
    summary = format_portfolio_summary(checking, stocks)
    return {"ok": True, "data": summary}
