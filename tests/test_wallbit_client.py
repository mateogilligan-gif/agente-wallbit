"""
Tests del parser de portfolio de Wallbit. Corren sin red — solo lógica pura.

Cubren dos bugs reales que encontramos en auditoría y corregimos:
1. El parser confundía claves como "cash"/"updated_at" con tickers falsos.
2. Un saldo de $0 se trataba como "dato faltante" (bug de falsy en Python).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import wallbit_client


# ─── Validación local de create_trade (antes de tocar el servidor real) ────
# Todos estos casos se cortan ANTES de llamar a _call_tool, así que corren
# sin red — si algún día alguno empieza a intentar de verdad la llamada de
# red, el test fallaría por timeout/conexión en vez de por el assert.

def test_create_trade_rechaza_symbol_vacio():
    resultado = wallbit_client.create_trade("", "BUY", 100)
    assert resultado["ok"] is False
    assert "symbol" in resultado["error"].lower()


def test_create_trade_rechaza_direction_invalido():
    resultado = wallbit_client.create_trade("AAPL", "HODL", 100)
    assert resultado["ok"] is False
    assert "direction" in resultado["error"].lower()


def test_create_trade_rechaza_monto_cero_o_negativo():
    assert wallbit_client.create_trade("AAPL", "BUY", 0)["ok"] is False
    assert wallbit_client.create_trade("AAPL", "BUY", -50)["ok"] is False


def test_create_trade_rechaza_order_type_invalido():
    # Wallbit acepta STOP, pero el bot no lo usa: se corta acá
    resultado = wallbit_client.create_trade("AAPL", "BUY", 100, order_type="STOP")
    assert resultado["ok"] is False
    assert "order_type" in resultado["error"].lower()


def test_create_trade_rechaza_limit_sin_precio():
    resultado = wallbit_client.create_trade("AAPL", "BUY", 100, order_type="LIMIT")
    assert resultado["ok"] is False
    assert "limit_price" in resultado["error"]


def test_create_trade_rechaza_limit_con_precio_cero():
    resultado = wallbit_client.create_trade("AAPL", "BUY", 100, order_type="LIMIT", limit_price=0)
    assert resultado["ok"] is False


def test_create_trade_rechaza_time_in_force_invalido():
    resultado = wallbit_client.create_trade("AAPL", "BUY", 100, order_type="LIMIT", limit_price=150, time_in_force="IOC")
    assert resultado["ok"] is False
    assert "time_in_force" in resultado["error"]


# ─── Formato que llega a Wallbit (schema real del MCP) ─────────────────────
# _call_tool está mockeado: se captura lo que se mandaría, sin red y sin
# ninguna orden real.

def _capturar_llamadas(monkeypatch):
    llamadas = []
    monkeypatch.setattr(wallbit_client, "_call_tool", lambda nombre, params=None: llamadas.append((nombre, params)) or {"ok": True, "data": "ok"})
    return llamadas


def test_create_trade_market_usa_los_nombres_del_schema_real(monkeypatch):
    llamadas = _capturar_llamadas(monkeypatch)
    assert wallbit_client.create_trade("meli", "BUY", 33.33)["ok"]
    assert llamadas == [("create_trade", {"symbol": "MELI", "direction": "BUY", "amount": 33.33, "order_type": "MARKET", "currency": "USD"})]


def test_create_trade_limit_manda_limit_price_y_time_in_force_day_por_default(monkeypatch):
    llamadas = _capturar_llamadas(monkeypatch)
    wallbit_client.create_trade("AAPL", "SELL", 100, order_type="LIMIT", limit_price=210.5)
    params = llamadas[0][1]
    assert params["order_type"] == "LIMIT"
    assert params["limit_price"] == 210.5
    assert params["time_in_force"] == "DAY"
    assert "price" not in params and "ticker" not in params and "side" not in params


def test_create_trade_normaliza_minusculas(monkeypatch):
    llamadas = _capturar_llamadas(monkeypatch)
    wallbit_client.create_trade("AAPL", "buy", 100, order_type="limit", limit_price=150, time_in_force="gtc")
    params = llamadas[0][1]
    assert (params["direction"], params["order_type"], params["time_in_force"]) == ("BUY", "LIMIT", "GTC")


def test_create_trade_market_no_manda_campos_de_limit(monkeypatch):
    llamadas = _capturar_llamadas(monkeypatch)
    wallbit_client.create_trade("AAPL", "BUY", 100, limit_price=150, time_in_force="GTC")
    assert "limit_price" not in llamadas[0][1] and "time_in_force" not in llamadas[0][1]


def test_get_asset_manda_symbol(monkeypatch):
    llamadas = _capturar_llamadas(monkeypatch)
    wallbit_client.get_asset("MELI")
    assert llamadas == [("get_asset", {"symbol": "MELI"})]


def test_tool_create_trade_usa_el_schema_nuevo(monkeypatch):
    llamadas = _capturar_llamadas(monkeypatch)
    wallbit_client._tool_create_trade({"symbol": "NU", "direction": "BUY", "amount": 10, "order_type": "MARKET"})
    assert llamadas[0][1]["symbol"] == "NU" and llamadas[0][1]["direction"] == "BUY"


def test_parsea_formato_dict_de_tickers():
    """Formato {AAPL: {...}, MSFT: {...}}."""
    raw = '{"AAPL": {"shares": 10, "avg_cost": 150.0}, "MSFT": {"shares": 5, "avg_cost": 300.0}}'
    posiciones = wallbit_client._parse_portfolio_text(raw)
    tickers = {p["ticker"] for p in posiciones}
    assert tickers == {"AAPL", "MSFT"}


def test_no_confunde_campos_no_ticker_con_posiciones():
    """Bug real: 'cash', 'updated_at' no deben aparecer como tickers falsos."""
    raw = (
        '{"AAPL": {"shares": 10, "avg_cost": 150.0}, '
        '"cash": 500.0, "updated_at": "2026-08-25", '
        '"MSFT": {"shares": 5, "avg_cost": 300.0}}'
    )
    posiciones = wallbit_client._parse_portfolio_text(raw)
    tickers = {p["ticker"] for p in posiciones}
    assert "CASH" not in tickers
    assert "UPDATED_AT" not in tickers
    assert tickers == {"AAPL", "MSFT"}


def test_parsea_formato_array_positions():
    raw = '{"positions": [{"ticker": "NVDA", "shares": 3, "avg_cost": 400.0}]}'
    posiciones = wallbit_client._parse_portfolio_text(raw)
    assert len(posiciones) == 1
    assert posiciones[0]["ticker"] == "NVDA"


def test_texto_no_json_devuelve_lista_vacia():
    """Si Wallbit devuelve texto plano no parseable, no debe crashear."""
    posiciones = wallbit_client._parse_portfolio_text("esto no es JSON para nada")
    assert posiciones == []


def test_saldo_cero_no_se_trata_como_dato_faltante():
    """Bug real: `0 or d.get(...)` trataba un saldo de $0 como si faltara el dato."""
    checking_res = {"ok": True, "data": '{"balance": 0}'}
    stocks_res = {"ok": True, "data": "[]"}
    resumen = wallbit_client.format_portfolio_summary(checking_res, stocks_res)
    assert "CUENTA CORRIENTE: $0" in resumen


def test_saldo_normal_se_muestra_bien():
    checking_res = {"ok": True, "data": '{"balance": 1500.50}'}
    stocks_res = {"ok": True, "data": "[]"}
    resumen = wallbit_client.format_portfolio_summary(checking_res, stocks_res)
    assert "1500.5" in resumen


# ─── obtener_cash_inversion ─────────────────────────────────────────────────
# Los planes DCA lo usan para chequear si la plata del plan ya está en la
# cuenta de Inversión antes de armar el ticket. El campo "cash" ya se filtraba en
# _parse_portfolio_text para no confundirlo con un ticker falso — acá es
# donde se usa ese valor para algo real.

def test_obtener_cash_inversion_formato_simple():
    stocks_res = {"ok": True, "data": '{"cash": 250.75, "AAPL": {"shares": 10}}'}
    assert wallbit_client.obtener_cash_inversion(stocks_res) == 250.75


def test_obtener_cash_inversion_prueba_claves_alternativas():
    assert wallbit_client.obtener_cash_inversion({"ok": True, "data": '{"available_cash": 10}'}) == 10.0
    assert wallbit_client.obtener_cash_inversion({"ok": True, "data": '{"cash_balance": 20}'}) == 20.0
    assert wallbit_client.obtener_cash_inversion({"ok": True, "data": '{"available": 30}'}) == 30.0


def test_obtener_cash_inversion_formato_anidado():
    stocks_res = {"ok": True, "data": '{"data": {"cash": 99.9}}'}
    assert wallbit_client.obtener_cash_inversion(stocks_res) == 99.9


def test_obtener_cash_inversion_none_si_la_respuesta_es_error():
    assert wallbit_client.obtener_cash_inversion({"ok": False, "error": "timeout"}) is None


def test_obtener_cash_inversion_none_si_no_hay_ningun_campo_de_cash():
    assert wallbit_client.obtener_cash_inversion({"ok": True, "data": '{"AAPL": {"shares": 10}}'}) is None


def test_obtener_cash_inversion_none_si_no_es_json_valido():
    assert wallbit_client.obtener_cash_inversion({"ok": True, "data": "esto no es json"}) is None


# ─── list_transactions: limit redondeado hacia arriba, page y fechas ───────
# Wallbit solo acepta limit 10/20/50. Todo se valida antes de llamar: un
# input inválido devuelve ok False sin tocar _call_tool.

@pytest.mark.parametrize("pedido,enviado", [(1, 10), (5, 10), (10, 10), (11, 20), (20, 20), (21, 50), (30, 50), (50, 50), (200, 50)])
def test_list_transactions_redondea_limit_hacia_arriba(monkeypatch, pedido, enviado):
    llamadas = _capturar_llamadas(monkeypatch)
    wallbit_client.list_transactions(limit=pedido)
    assert llamadas == [("list_transactions", {"limit": enviado})]


def test_list_transactions_default_sigue_siendo_50(monkeypatch):
    llamadas = _capturar_llamadas(monkeypatch)
    wallbit_client.list_transactions()
    assert llamadas == [("list_transactions", {"limit": 50})]


def test_list_transactions_manda_page_y_fechas(monkeypatch):
    llamadas = _capturar_llamadas(monkeypatch)
    wallbit_client.list_transactions(limit=20, page=2, from_date="2026-09-01", to_date="2026-09-30")
    assert llamadas == [("list_transactions", {"limit": 20, "page": 2, "from_date": "2026-09-01", "to_date": "2026-09-30"})]


def test_list_transactions_acepta_una_sola_fecha_y_mismo_dia(monkeypatch):
    llamadas = _capturar_llamadas(monkeypatch)
    wallbit_client.list_transactions(from_date="2026-10-01")
    wallbit_client.list_transactions(from_date="2026-10-01", to_date="2026-10-01")
    assert llamadas[0][1] == {"limit": 50, "from_date": "2026-10-01"}
    assert llamadas[1][1] == {"limit": 50, "from_date": "2026-10-01", "to_date": "2026-10-01"}


@pytest.mark.parametrize("kwargs,campo", [
    ({"limit": 0}, "limit"), ({"limit": -5}, "limit"), ({"limit": "20"}, "limit"), ({"limit": True}, "limit"),
    ({"page": 0}, "page"), ({"page": -1}, "page"), ({"page": 1.5}, "page"), ({"page": "2"}, "page"),
    ({"from_date": "2026-02-30"}, "from_date"), ({"from_date": "01/10/2026"}, "from_date"),
    ({"to_date": "2026-13-01"}, "to_date"), ({"to_date": "2026-1-5"}, "to_date"), ({"to_date": 20261001}, "to_date"),
    ({"from_date": "2026-10-05", "to_date": "2026-10-01"}, "from_date"),
])
def test_list_transactions_invalido_no_llama_a_wallbit(monkeypatch, kwargs, campo):
    llamadas = _capturar_llamadas(monkeypatch)
    r = wallbit_client.list_transactions(**kwargs)
    assert r["ok"] is False and campo in r["error"]
    assert llamadas == []


def test_list_transactions_no_manda_filtros_no_expuestos(monkeypatch):
    llamadas = _capturar_llamadas(monkeypatch)
    wallbit_client._tool_list_transactions({"limit": 30, "page": 3, "currency": "USD", "status": "COMPLETED", "type": "TRADE", "from_amount": 10})
    assert llamadas == [("list_transactions", {"limit": 50, "page": 3})]


def test_tool_list_transactions_schema_expone_solo_page_y_fechas():
    from tool_registry import TOOL_REGISTRY
    props = TOOL_REGISTRY["list_transactions"]["schema"]["input_schema"]["properties"]
    assert set(props) == {"limit", "page", "from_date", "to_date"}
