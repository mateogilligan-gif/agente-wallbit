import requests
import os
from typing import Optional

WALLBIT_BASE_URL = "https://mcp.wallbit.io/mcp"
_initialized = False

def get_headers():
    return {
        "X-API-Key": os.getenv("WALLBIT_API_KEY"),
        "Content-Type": "application/json",
        "Accept": "application/json"
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
    except Exception:
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
        result = response.json()

        if "error" in result:
            return {"ok": False, "error": result["error"].get("message", "Error desconocido de Wallbit")}

        if "result" in result:
            # El MCP devuelve content como array de objetos
            content = result["result"].get("content", [])
            if content and isinstance(content, list):
                texto = "\n".join([c.get("text", "") for c in content if c.get("type") == "text"])
                return {"ok": True, "data": texto}
            return {"ok": True, "data": result["result"]}

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

def get_full_portfolio() -> dict:
    """Obtiene checking + stocks. Llama ambos y devuelve juntos."""
    checking = get_checking_balance()
    stocks = get_stocks_balance()
    return {"checking": checking, "stocks": stocks}
