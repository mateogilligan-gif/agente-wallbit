"""
Tests de planes_dca.py — planes de DCA programados.

Sin red: get_asset, get_stocks_balance y create_trade de wallbit_client están
mockeados en cada test (NUNCA se manda una orden real), y la DB es una sqlite
temporal. La fecha de "hoy" se fija mockeando planes_dca._hoy o pasándola
como parámetro a las funciones puras.
"""
import sys
import os
import json
from pathlib import Path
from datetime import date
import tempfile
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
_tmp_dir = tempfile.mkdtemp()
database.DB_PATH = Path(_tmp_dir) / "test_agente.db"
database.init_db()

import planes_dca


@pytest.fixture(autouse=True)
def _limpiar_planes(monkeypatch):
    """
    database.DB_PATH es un global compartido por todos los archivos de test
    (termina apuntando al último que lo reasigna), así que cada test arranca
    con las tablas de planes vacías. Además, por seguridad, create_trade y
    get_stocks_balance quedan bloqueados salvo que el test los mockee.
    """
    database.init_db()
    import sqlite3
    conn = sqlite3.connect(database.DB_PATH)
    conn.execute("DELETE FROM planes_dca")
    conn.execute("DELETE FROM ejecuciones_dca")
    conn.commit()
    conn.close()

    def prohibido(*a, **k):
        raise AssertionError("create_trade real llamado en un test")

    monkeypatch.setattr(planes_dca.wallbit_client, "create_trade", prohibido)
    monkeypatch.setattr(planes_dca.wallbit_client, "get_asset", _get_asset_falso)
    yield


TICKERS_INEXISTENTES = {"ZZZQX", "NOEXISTE"}


def _get_asset_falso(ticker):
    if ticker.upper() in TICKERS_INEXISTENTES:
        return {"ok": False, "error": "⚠️ ERROR WALLBIT: Request failed with status code 404"}
    return {"ok": True, "data": json.dumps({"data": {"symbol": ticker.upper(), "price": 10.0, "asset_type": "us_equity"}})}


def _fijar_hoy(monkeypatch, hoy):
    monkeypatch.setattr(planes_dca, "_hoy", lambda: hoy)


def _cash(monkeypatch, valor):
    llamadas = []

    def falso():
        llamadas.append(1)
        if valor is None:
            return {"ok": False, "error": "timeout"}
        return {"ok": True, "data": json.dumps({"cash": valor})}

    monkeypatch.setattr(planes_dca.wallbit_client, "get_stocks_balance", falso)
    return llamadas


def _crear(monkeypatch, hoy, dia, monto, tickers=None, split=None, nombre=None):
    _fijar_hoy(monkeypatch, hoy)
    inputs = {"accion": "crear", "dia": dia, "monto_usd": monto}
    if tickers:
        inputs["tickers"] = tickers
    if split:
        inputs["split"] = split
    if nombre:
        inputs["nombre"] = nombre
    return planes_dca._tool_gestionar_plan_dca(inputs)


def _trades_falsos(monkeypatch, fallan=()):
    ordenes = []

    def falso(ticker, side, amount, order_type="market", price=None):
        ordenes.append({"ticker": ticker, "side": side, "amount": amount, "order_type": order_type})
        if ticker in fallan:
            return {"ok": False, "error": "⚠️ ERROR WALLBIT: rechazada"}
        return {"ok": True, "data": "orden ok"}

    monkeypatch.setattr(planes_dca.wallbit_client, "create_trade", falso)
    return ordenes


def _ejecutar(numero, texto_usuario):
    with planes_dca.mensaje_real_del_usuario(texto_usuario):
        return planes_dca._tool_ejecutar_plan_dca({"numero": numero})


# ─── validar_split (reusada) ────────────────────────────────────────────────

def test_validar_split_ok_cuando_suma_100():
    ok, motivo = planes_dca.validar_split([{"ticker": "NVDA", "pct": 50}, {"ticker": "MSFT", "pct": 50}])
    assert ok is True
    assert motivo is None


def test_validar_split_rechaza_vacio():
    ok, motivo = planes_dca.validar_split([])
    assert ok is False


def test_validar_split_rechaza_suma_distinta_de_100():
    ok, motivo = planes_dca.validar_split([{"ticker": "NVDA", "pct": 50}, {"ticker": "MSFT", "pct": 30}])
    assert ok is False
    assert "80" in motivo


def test_validar_split_tolera_pequenos_errores_de_redondeo():
    ok, motivo = planes_dca.validar_split([{"ticker": "A", "pct": 33.33}, {"ticker": "B", "pct": 33.33}, {"ticker": "C", "pct": 33.34}])
    assert ok is True


def test_validar_split_rechaza_pct_negativo_o_cero():
    ok, motivo = planes_dca.validar_split([{"ticker": "NVDA", "pct": 0}, {"ticker": "MSFT", "pct": 100}])
    assert ok is False


def test_validar_split_rechaza_item_sin_ticker():
    ok, motivo = planes_dca.validar_split([{"pct": 100}])
    assert ok is False


def test_validar_split_rechaza_mas_de_10_tickers():
    split_11 = [{"ticker": f"T{i}", "pct": 100 / 11} for i in range(11)]
    ok, motivo = planes_dca.validar_split(split_11)
    assert ok is False
    assert "10" in motivo


def test_validar_split_acepta_justo_10_tickers():
    split_10 = [{"ticker": f"T{i}", "pct": 10} for i in range(10)]
    ok, motivo = planes_dca.validar_split(split_10)
    assert ok is True, motivo


# ─── calcular_montos / split_equitativo / parsear_split_json (reusadas) ─────

def test_calcular_montos_split_simple():
    asignaciones = planes_dca.calcular_montos(500, [{"ticker": "nvda", "pct": 50}, {"ticker": "msft", "pct": 25}, {"ticker": "pltr", "pct": 25}])
    por_ticker = {a["ticker"]: a["monto"] for a in asignaciones}
    assert por_ticker == {"NVDA": 250.0, "MSFT": 125.0, "PLTR": 125.0}


def test_calcular_montos_suma_exacta_al_monto_total_pese_al_redondeo():
    asignaciones = planes_dca.calcular_montos(100, [{"ticker": "A", "pct": 33.33}, {"ticker": "B", "pct": 33.33}, {"ticker": "C", "pct": 33.34}])
    assert round(sum(a["monto"] for a in asignaciones), 2) == 100.0


def test_calcular_montos_rechaza_monto_cero_o_negativo():
    with pytest.raises(ValueError):
        planes_dca.calcular_montos(0, [{"ticker": "NVDA", "pct": 100}])


def test_calcular_montos_rechaza_split_invalido():
    with pytest.raises(ValueError):
        planes_dca.calcular_montos(100, [{"ticker": "NVDA", "pct": 50}])


def test_split_equitativo_dos_tickers():
    split = planes_dca.split_equitativo(["nvda", "msft"])
    assert split == [{"ticker": "NVDA", "pct": 50.0}, {"ticker": "MSFT", "pct": 50.0}]


def test_split_equitativo_tres_tickers_suma_exacto_100():
    split = planes_dca.split_equitativo(["meli", "nu", "aapl"])
    assert [s["pct"] for s in split] == [33.33, 33.33, 33.34]


def test_split_equitativo_pasa_validar_split():
    split = planes_dca.split_equitativo(["a", "b", "c", "d", "e", "f", "g"])
    ok, motivo = planes_dca.validar_split(split)
    assert ok is True, motivo


def test_split_equitativo_rechaza_lista_vacia():
    with pytest.raises(ValueError):
        planes_dca.split_equitativo([])


def test_split_equitativo_rechaza_mas_de_10_tickers():
    with pytest.raises(ValueError):
        planes_dca.split_equitativo([f"T{i}" for i in range(11)])


def test_parsear_split_json_valido():
    split = planes_dca.parsear_split_json('[{"ticker":"NVDA","pct":50},{"ticker":"MSFT","pct":50}]')
    assert len(split) == 2


def test_parsear_split_json_invalido_tira_value_error():
    with pytest.raises(ValueError):
        planes_dca.parsear_split_json("esto no es json")


def test_armar_texto_ticket_incluye_cada_ticker_y_pide_respuesta_explicita():
    asignaciones = [{"ticker": "NVDA", "pct": 50, "monto": 250.0}, {"ticker": "MSFT", "pct": 50, "monto": 250.0}]
    texto = planes_dca.armar_texto_ticket(500, asignaciones, titulo="Plan 1", respuesta_si="SÍ plan 1", respuesta_no="NO plan 1")
    assert "NVDA" in texto and "MSFT" in texto
    assert "USD 250.00" in texto
    assert "Respondé SÍ plan 1" in texto


# ─── Fechas (casos borde 2 y 3) ─────────────────────────────────────────────

def test_dia_31_en_abril_usa_el_ultimo_dia_del_mes():
    assert planes_dca.fecha_programada(31, 2026, 4) == date(2026, 4, 30)  # jueves


def test_dia_30_en_febrero_bisiesto():
    assert planes_dca.fecha_programada(30, 2028, 2) == date(2028, 2, 29)  # martes


def test_dia_30_en_febrero_no_bisiesto():
    assert planes_dca.fecha_programada(30, 2025, 2) == date(2025, 2, 28)  # viernes


def test_dia_30_en_febrero_no_bisiesto_que_cae_domingo_pasa_al_lunes_de_marzo():
    assert planes_dca.fecha_programada(30, 2027, 2) == date(2027, 3, 1)


def test_sabado_pasa_al_lunes():
    assert planes_dca.fecha_programada(3, 2026, 10) == date(2026, 10, 5)


def test_domingo_pasa_al_lunes():
    assert planes_dca.fecha_programada(4, 2026, 10) == date(2026, 10, 5)


def test_fin_de_semana_con_lunes_en_el_mes_siguiente():
    # 31/10/2026 es sábado -> lunes 2/11, pero cuenta como la compra de octubre
    assert planes_dca.fecha_programada(31, 2026, 10) == date(2026, 11, 2)
    acc = planes_dca.periodo_accionable(31, date(2026, 11, 2))
    assert acc["periodo"] == "2026-10"
    assert acc["atrasado"] is False


def test_periodo_accionable_antes_del_dia_no_hay_nada():
    assert planes_dca.periodo_accionable(5, date(2026, 10, 2)) is None


def test_periodo_accionable_el_dia_del_plan():
    acc = planes_dca.periodo_accionable(5, date(2026, 10, 5))
    assert acc == {"periodo": "2026-10", "fecha_programada": date(2026, 10, 5), "atrasado": False}


def test_periodo_accionable_atrasado_dentro_del_mismo_mes():
    acc = planes_dca.periodo_accionable(5, date(2026, 10, 20))
    assert acc["periodo"] == "2026-10" and acc["atrasado"] is True


def test_periodo_accionable_nunca_recupera_el_mes_anterior():
    # 4/11: el periodo de octubre ya cerró (fin de mes) y el de noviembre todavía no llegó
    assert planes_dca.periodo_accionable(5, date(2026, 11, 4)) is None


def test_periodo_accionable_lunes_corrido_y_mes_siguiente_no_se_pisan():
    assert planes_dca.periodo_accionable(31, date(2026, 11, 1)) is None
    assert planes_dca.periodo_accionable(31, date(2026, 11, 29))["periodo"] == "2026-10"
    assert planes_dca.periodo_accionable(31, date(2026, 11, 30))["periodo"] == "2026-11"


def test_primer_periodo_desde_mismo_dia_o_antes_arranca_este_mes():
    assert planes_dca.primer_periodo_desde(5, date(2026, 10, 5)) == "2026-10"
    assert planes_dca.primer_periodo_desde(5, date(2026, 10, 1)) == "2026-10"


def test_primer_periodo_desde_despues_del_dia_arranca_el_mes_siguiente():
    assert planes_dca.primer_periodo_desde(5, date(2026, 10, 6)) == "2026-11"


def test_primer_periodo_desde_diciembre_pasa_a_enero():
    assert planes_dca.primer_periodo_desde(5, date(2026, 12, 20)) == "2027-01"


# ─── Confirmación estricta ──────────────────────────────────────────────────

@pytest.mark.parametrize("texto,numero", [
    ("SÍ", None), ("si", None), ("Sí.", None), ("  SI!  ", None), ("CONFIRMO", None),
    ("SÍ plan 2", 2), ("si plan 2", 2), ("Confirmo plan 3.", 3), ("¡Sí plan 1!", 1),
])
def test_parsear_confirmacion_acepta_solo_las_formas_validas(texto, numero):
    assert planes_dca.parsear_confirmacion(texto) == {"numero": numero}


@pytest.mark.parametrize("texto", [
    "si querés cambiá el plan 2", "no sé si", "dale", "sí, pero mañana", "NO", "si plan", "plan 2", "sisi", "", None,
])
def test_parsear_confirmacion_rechaza_todo_lo_demas(texto):
    assert planes_dca.parsear_confirmacion(texto) is None


def test_validar_confirmacion_si_ambiguo_con_dos_pendientes():
    error = planes_dca.validar_confirmacion("SÍ", 1, [1, 2])
    assert error and "SÍ plan 1" in error and "SÍ plan 2" in error


def test_validar_confirmacion_numero_equivocado():
    assert planes_dca.validar_confirmacion("SÍ plan 2", 1, [1, 2]) is not None


def test_validar_confirmacion_sin_mensaje_real_rechaza():
    assert planes_dca.validar_confirmacion(None, 1, [1]) is not None


def test_mensaje_real_del_usuario_solo_vale_adentro_del_bloque():
    assert planes_dca.mensaje_usuario_actual() is None
    with planes_dca.mensaje_real_del_usuario("SÍ"):
        assert planes_dca.mensaje_usuario_actual() == "SÍ"
    assert planes_dca.mensaje_usuario_actual() is None


# ─── Alta, edición y validación (casos borde 1, 4, 5) ───────────────────────

def test_previsualizar_no_guarda_y_devuelve_resumen(monkeypatch):
    _fijar_hoy(monkeypatch, date(2026, 10, 2))
    r = planes_dca._tool_gestionar_plan_dca({"accion": "previsualizar", "dia": 5, "monto_usd": 100, "tickers": ["meli", "nu", "aapl"]})
    assert r["ok"]
    assert r["data"]["resumen"] == "Plan 1: día 5, USD 100.00, MELI 33.33% / NU 33.33% / AAPL 33.34%"
    assert r["data"]["primera_compra"] == "2026-10-05"
    assert database.obtener_planes_dca() == []


def test_crear_plan_guarda(monkeypatch):
    r = _crear(monkeypatch, date(2026, 10, 2), 5, 100, tickers=["MELI", "NU", "AAPL"], nombre="LatAm")
    assert r["ok"] and r["data"]["guardado"]
    planes = database.obtener_planes_dca()
    assert len(planes) == 1 and planes[0]["numero"] == 1 and planes[0]["nombre"] == "LatAm"


def test_sexto_plan_se_rechaza(monkeypatch):
    for _ in range(5):
        assert _crear(monkeypatch, date(2026, 10, 2), 5, 10, tickers=["NU"])["ok"]
    r = _crear(monkeypatch, date(2026, 10, 2), 5, 10, tickers=["NU"])
    assert not r["ok"]
    assert "5" in r["error"] and "máximo" in r["error"]
    assert len(database.obtener_planes_dca()) == 5


def test_numero_de_plan_borrado_se_reusa(monkeypatch):
    for _ in range(3):
        _crear(monkeypatch, date(2026, 10, 2), 5, 10, tickers=["NU"])
    planes_dca._tool_gestionar_plan_dca({"accion": "borrar", "numero": 2})
    r = _crear(monkeypatch, date(2026, 10, 2), 5, 10, tickers=["NU"])
    assert r["data"]["numero"] == 2


def test_monto_por_ticker_menor_a_1_usd_se_rechaza_al_crear_con_el_calculo(monkeypatch):
    r = _crear(monkeypatch, date(2026, 10, 2), 5, 2, tickers=["MELI", "NU", "AAPL"])
    assert not r["ok"]
    assert "USD 0.67" in r["error"]
    assert "USD 3.00" in r["error"]  # monto mínimo para que las 3 órdenes lleguen a USD 1
    assert database.obtener_planes_dca() == []


def test_monto_por_ticker_menor_a_1_usd_se_rechaza_al_editar(monkeypatch):
    _crear(monkeypatch, date(2026, 10, 2), 5, 30, tickers=["MELI", "NU", "AAPL"])
    r = planes_dca._tool_gestionar_plan_dca({"accion": "editar", "numero": 1, "monto_usd": 2.5})
    assert not r["ok"] and "mínimo" in r["error"]
    assert database.obtener_plan_dca(1)["monto_usd"] == 30


def test_split_personalizado_con_un_ticker_por_debajo_del_minimo(monkeypatch):
    r = _crear(monkeypatch, date(2026, 10, 2), 5, 10, split=[{"ticker": "MELI", "pct": 95}, {"ticker": "NU", "pct": 5}])
    assert not r["ok"] and "NU USD 0.50" in r["error"]


def test_ticker_inexistente_al_crear_no_guarda(monkeypatch):
    r = _crear(monkeypatch, date(2026, 10, 2), 5, 100, tickers=["MELI", "ZZZQX"])
    assert not r["ok"] and "ZZZQX" in r["error"]
    assert database.obtener_planes_dca() == []


def test_ticker_inexistente_al_editar_no_guarda(monkeypatch):
    _crear(monkeypatch, date(2026, 10, 2), 5, 100, tickers=["MELI"])
    r = planes_dca._tool_gestionar_plan_dca({"accion": "editar", "numero": 1, "tickers": ["NOEXISTE"]})
    assert not r["ok"]
    assert "MELI" in database.obtener_plan_dca(1)["split_json"]


def test_dia_invalido_se_rechaza(monkeypatch):
    assert not _crear(monkeypatch, date(2026, 10, 2), 32, 100, tickers=["MELI"])["ok"]
    assert not _crear(monkeypatch, date(2026, 10, 2), 0, 100, tickers=["MELI"])["ok"]


def test_tickers_repetidos_se_rechazan(monkeypatch):
    r = _crear(monkeypatch, date(2026, 10, 2), 5, 100, split=[{"ticker": "NU", "pct": 50}, {"ticker": "nu", "pct": 50}])
    assert not r["ok"] and "repetidos" in r["error"]


def test_plan_creado_despues_de_su_dia_arranca_el_mes_siguiente(monkeypatch):
    r = _crear(monkeypatch, date(2026, 10, 20), 5, 100, tickers=["MELI"])
    assert r["data"]["arranca_en"] == "2026-11"
    _cash(monkeypatch, 1000)
    assert planes_dca.correr_chequeo_diario(date(2026, 10, 20)) == []  # nada atrasado de octubre


def test_listar_muestra_estado_y_proxima_compra(monkeypatch):
    _crear(monkeypatch, date(2026, 10, 2), 5, 100, tickers=["MELI"])
    r = planes_dca._tool_gestionar_plan_dca({"accion": "listar"})
    assert r["data"][0]["estado"] == "activo"
    assert r["data"][0]["proxima_compra"] == "2026-10-05"


# ─── Job diario (casos borde 6, 7, 12, 13) ──────────────────────────────────

def test_sin_planes_activos_no_llama_a_wallbit(monkeypatch):
    llamadas = _cash(monkeypatch, 1000)
    assert planes_dca.correr_chequeo_diario(date(2026, 10, 5)) == []
    assert llamadas == []


def test_si_ningun_plan_toca_hoy_no_llama_a_wallbit(monkeypatch):
    _crear(monkeypatch, date(2026, 10, 2), 20, 100, tickers=["MELI"])
    llamadas = _cash(monkeypatch, 1000)
    assert planes_dca.correr_chequeo_diario(date(2026, 10, 5)) == []
    assert llamadas == []


def test_dia_del_plan_con_plata_arma_ticket_pendiente(monkeypatch):
    _crear(monkeypatch, date(2026, 10, 2), 5, 100, tickers=["MELI", "NU", "AAPL"], nombre="LatAm")
    _cash(monkeypatch, 150)
    mensajes = planes_dca.correr_chequeo_diario(date(2026, 10, 5))
    assert len(mensajes) == 1
    assert "Plan 1 (LatAm)" in mensajes[0]
    assert "MELI: USD 33.33" in mensajes[0] and "AAPL: USD 33.34" in mensajes[0]
    assert "Respondé SÍ para comprar" in mensajes[0]
    assert "ATRASADA" not in mensajes[0]
    e = database.obtener_ejecuciones_dca()[0]
    assert e["estado"] == "pendiente" and e["periodo"] == "2026-10"
    # una segunda corrida el mismo día no repite el ticket
    assert planes_dca.correr_chequeo_diario(date(2026, 10, 5)) == []


def test_bot_apagado_el_dia_del_plan_se_pone_al_dia_marcando_atrasado(monkeypatch):
    _crear(monkeypatch, date(2026, 10, 2), 5, 100, tickers=["MELI"])
    _cash(monkeypatch, 150)
    mensajes = planes_dca.correr_chequeo_diario(date(2026, 10, 9))
    assert len(mensajes) == 1 and "ATRASADA" in mensajes[0]


def test_bot_apagado_todo_el_mes_no_recupera_meses_anteriores(monkeypatch):
    _crear(monkeypatch, date(2026, 10, 2), 5, 100, tickers=["MELI"])
    _cash(monkeypatch, 150)
    assert planes_dca.correr_chequeo_diario(date(2026, 11, 3)) == []  # octubre cerrado, noviembre todavía no
    mensajes = planes_dca.correr_chequeo_diario(date(2026, 11, 5))
    assert len(mensajes) == 1 and "2026-11" in mensajes[0]


def test_efectivo_insuficiente_avisa_una_vez_y_compra_cuando_alcanza(monkeypatch):
    _crear(monkeypatch, date(2026, 10, 2), 5, 50, tickers=["NU", "AXTI"])
    _cash(monkeypatch, 18)
    mensajes = planes_dca.correr_chequeo_diario(date(2026, 10, 5))
    assert len(mensajes) == 1
    assert "Para el plan 1 te faltan USD 32.00" in mensajes[0]

    # al día siguiente sigue sin alcanzar: reintento silencioso
    assert planes_dca.correr_chequeo_diario(date(2026, 10, 6)) == []
    assert database.obtener_ejecuciones_dca()[0]["estado"] == "sin_fondos"

    # llegó la plata: ahora sí, ticket
    _cash(monkeypatch, 60)
    mensajes = planes_dca.correr_chequeo_diario(date(2026, 10, 7))
    assert len(mensajes) == 1 and "Respondé SÍ" in mensajes[0]
    assert database.obtener_ejecuciones_dca()[0]["estado"] == "pendiente"


def test_dos_planes_mismo_dia_con_plata_para_uno_solo(monkeypatch):
    _crear(monkeypatch, date(2026, 10, 2), 5, 100, tickers=["MELI", "NU", "AAPL"])
    _crear(monkeypatch, date(2026, 10, 2), 5, 50, tickers=["NU", "CRML", "AXTI"])
    _cash(monkeypatch, 120)
    mensajes = planes_dca.correr_chequeo_diario(date(2026, 10, 5))
    assert len(mensajes) == 2
    assert mensajes[0].startswith("Plan 1") and "Respondé SÍ para comprar" in mensajes[0]
    assert "Para el plan 2 te faltan USD 30.00" in mensajes[1]
    estados = {e["plan_numero"]: e["estado"] for e in database.obtener_ejecuciones_dca()}
    assert estados == {1: "pendiente", 2: "sin_fondos"}


def test_dos_tickets_el_mismo_dia_piden_si_plan_n(monkeypatch):
    _crear(monkeypatch, date(2026, 10, 2), 5, 100, tickers=["MELI"])
    _crear(monkeypatch, date(2026, 10, 2), 5, 50, tickers=["NU"])
    _cash(monkeypatch, 500)
    mensajes = planes_dca.correr_chequeo_diario(date(2026, 10, 5))
    assert "Respondé SÍ plan 1" in mensajes[0]
    assert "Respondé SÍ plan 2" in mensajes[1]


def test_plata_reservada_por_ticket_pendiente_no_se_usa_para_otro_plan(monkeypatch):
    _crear(monkeypatch, date(2026, 10, 2), 5, 100, tickers=["MELI"])
    _crear(monkeypatch, date(2026, 10, 2), 6, 50, tickers=["NU"])
    _cash(monkeypatch, 120)
    planes_dca.correr_chequeo_diario(date(2026, 10, 5))  # plan 1 queda pendiente sin confirmar
    mensajes = planes_dca.correr_chequeo_diario(date(2026, 10, 6))
    assert len(mensajes) == 1 and "Para el plan 2 te faltan USD 30.00" in mensajes[0]


def test_cash_ilegible_no_arma_ticket_ni_avisa_falta_y_reintenta(monkeypatch):
    _crear(monkeypatch, date(2026, 10, 2), 5, 100, tickers=["MELI"])
    _cash(monkeypatch, None)
    assert planes_dca.correr_chequeo_diario(date(2026, 10, 5)) == []
    assert database.obtener_ejecuciones_dca() == []
    _cash(monkeypatch, 150)
    assert len(planes_dca.correr_chequeo_diario(date(2026, 10, 6))) == 1


def test_plan_pausado_no_se_toma_y_reactivado_no_recupera(monkeypatch):
    _crear(monkeypatch, date(2026, 10, 2), 5, 100, tickers=["MELI"])
    planes_dca._tool_gestionar_plan_dca({"accion": "pausar", "numero": 1})
    llamadas = _cash(monkeypatch, 500)
    assert planes_dca.correr_chequeo_diario(date(2026, 10, 5)) == []
    assert llamadas == []  # sin planes activos ni siquiera se lee el cash

    # reactivado después de su fecha de octubre: arranca en noviembre, sin ticket atrasado
    _fijar_hoy(monkeypatch, date(2026, 10, 10))
    r = planes_dca._tool_gestionar_plan_dca({"accion": "reactivar", "numero": 1})
    assert r["ok"] and "2026-11-05" in r["data"]
    assert planes_dca.correr_chequeo_diario(date(2026, 10, 10)) == []
    assert len(planes_dca.correr_chequeo_diario(date(2026, 11, 5))) == 1


def test_plan_reactivado_antes_de_su_fecha_toma_el_mes_en_curso(monkeypatch):
    _crear(monkeypatch, date(2026, 10, 2), 20, 100, tickers=["MELI"])
    planes_dca._tool_gestionar_plan_dca({"accion": "pausar", "numero": 1})
    _fijar_hoy(monkeypatch, date(2026, 10, 10))
    planes_dca._tool_gestionar_plan_dca({"accion": "reactivar", "numero": 1})
    _cash(monkeypatch, 500)
    assert len(planes_dca.correr_chequeo_diario(date(2026, 10, 20))) == 1


def test_pausar_descarta_el_ticket_pendiente(monkeypatch):
    _crear(monkeypatch, date(2026, 10, 2), 5, 100, tickers=["MELI"])
    _cash(monkeypatch, 500)
    planes_dca.correr_chequeo_diario(date(2026, 10, 5))
    _fijar_hoy(monkeypatch, date(2026, 10, 5))
    planes_dca._tool_gestionar_plan_dca({"accion": "pausar", "numero": 1})
    _trades_falsos(monkeypatch)
    assert not _ejecutar(1, "SÍ")["ok"]


def test_ejecucion_interrumpida_avisa_una_sola_vez_y_no_reintenta(monkeypatch):
    _crear(monkeypatch, date(2026, 10, 2), 5, 100, tickers=["MELI"])
    _cash(monkeypatch, 500)
    planes_dca.correr_chequeo_diario(date(2026, 10, 5))
    e = database.obtener_ejecuciones_dca()[0]
    database.cambiar_estado_ejecucion_dca(e["id"], "pendiente", "ejecutando")  # el bot se cayó acá

    mensajes = planes_dca.correr_chequeo_diario(date(2026, 10, 6))
    assert len(mensajes) == 1
    assert "plan 1" in mensajes[0] and "medio ejecutar" in mensajes[0] and "app de" in mensajes[0]
    assert planes_dca.correr_chequeo_diario(date(2026, 10, 7)) == []  # el aviso no se repite
    assert database.obtener_ejecuciones_dca()[0]["estado"] == "ejecutando"  # nunca se reintenta solo

    _fijar_hoy(monkeypatch, date(2026, 10, 7))
    _trades_falsos(monkeypatch)
    assert not _ejecutar(1, "SÍ")["ok"]


# ─── Ejecución (casos borde 8, 9, 10, 11, 14) ───────────────────────────────

def _plan_con_ticket(monkeypatch, tickers=("MELI", "NU", "AAPL"), monto=100, hoy=date(2026, 10, 5)):
    _crear(monkeypatch, date(2026, 10, 2), hoy.day, monto, tickers=list(tickers))
    _cash(monkeypatch, 1000)
    planes_dca.correr_chequeo_diario(hoy)
    _fijar_hoy(monkeypatch, hoy)


def test_si_ejecuta_una_orden_market_por_ticker(monkeypatch):
    _plan_con_ticket(monkeypatch)
    ordenes = _trades_falsos(monkeypatch)
    r = _ejecutar(1, "SÍ")
    assert r["ok"]
    assert [(o["ticker"], o["amount"], o["side"], o["order_type"]) for o in ordenes] == [
        ("MELI", 33.33, "buy", "market"), ("NU", 33.33, "buy", "market"), ("AAPL", 33.34, "buy", "market")]
    assert r["data"]["fallidas"] == []
    assert database.obtener_ejecuciones_dca()[0]["estado"] == "ejecutado"


def test_ejecucion_registra_en_bitacora(monkeypatch):
    import sqlite3
    _plan_con_ticket(monkeypatch)
    _trades_falsos(monkeypatch)
    _ejecutar(1, "SÍ")
    conn = sqlite3.connect(database.DB_PATH)
    fila = conn.execute("SELECT descripcion FROM bitacora WHERE tipo = 'dca' ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert "plan 1" in fila[0] and "USD 100.00" in fila[0] and "MELI" in fila[0]


def test_si_repetido_no_compra_dos_veces(monkeypatch):
    _plan_con_ticket(monkeypatch)
    ordenes = _trades_falsos(monkeypatch)
    assert _ejecutar(1, "SÍ")["ok"]
    r = _ejecutar(1, "SÍ")
    assert not r["ok"] and "No se compró nada" in r["error"]
    assert len(ordenes) == 3


def test_si_ambiguo_con_dos_tickets_pendientes_no_ejecuta(monkeypatch):
    _crear(monkeypatch, date(2026, 10, 2), 5, 100, tickers=["MELI"])
    _crear(monkeypatch, date(2026, 10, 2), 5, 50, tickers=["NU"])
    _cash(monkeypatch, 500)
    planes_dca.correr_chequeo_diario(date(2026, 10, 5))
    _fijar_hoy(monkeypatch, date(2026, 10, 5))
    ordenes = _trades_falsos(monkeypatch)

    r = _ejecutar(1, "SÍ")
    assert not r["ok"] and "SÍ plan 1" in r["error"]
    assert ordenes == []

    assert _ejecutar(2, "SÍ plan 2")["ok"]
    assert [o["ticker"] for o in ordenes] == ["NU"]


def test_confirmacion_no_estricta_no_ejecuta(monkeypatch):
    _plan_con_ticket(monkeypatch)
    ordenes = _trades_falsos(monkeypatch)
    for texto in ["si querés cambiá el plan 2", "no sé si", "dale"]:
        assert not _ejecutar(1, texto)["ok"]
    assert ordenes == []


def test_ejecutar_fuera_de_un_mensaje_real_rechaza(monkeypatch):
    _plan_con_ticket(monkeypatch)
    ordenes = _trades_falsos(monkeypatch)
    r = planes_dca._tool_ejecutar_plan_dca({"numero": 1})  # sin mensaje_real_del_usuario: como desde un job
    assert not r["ok"]
    assert ordenes == []


def test_ejecutar_sin_ticket_pendiente_rechaza(monkeypatch):
    _crear(monkeypatch, date(2026, 10, 2), 5, 100, tickers=["MELI"])
    _fijar_hoy(monkeypatch, date(2026, 10, 5))
    ordenes = _trades_falsos(monkeypatch)
    r = _ejecutar(1, "SÍ")
    assert not r["ok"] and "no tiene un ticket pendiente" in r["error"]
    assert ordenes == []


def test_ejecutar_ticket_de_un_mes_anterior_rechaza(monkeypatch):
    _plan_con_ticket(monkeypatch)  # ticket de octubre, nunca confirmado
    _fijar_hoy(monkeypatch, date(2026, 11, 3))
    ordenes = _trades_falsos(monkeypatch)
    assert not _ejecutar(1, "SÍ")["ok"]
    assert ordenes == []


def test_una_orden_falla_las_otras_se_ejecutan_y_se_informa(monkeypatch):
    _plan_con_ticket(monkeypatch)
    ordenes = _trades_falsos(monkeypatch, fallan={"NU"})
    r = _ejecutar(1, "SÍ")
    assert r["ok"]
    assert len(ordenes) == 3  # siguió con AAPL después de que NU falló
    assert r["data"]["fallidas"] == ["NU"]
    assert "NO se reintentan" in r["data"]["nota"]
    assert database.obtener_ejecuciones_dca()[0]["estado"] == "ejecutado"  # no se reintenta solo


def test_no_descarta_el_ticket_y_el_plan_sigue_para_el_mes_siguiente(monkeypatch):
    _plan_con_ticket(monkeypatch)
    ordenes = _trades_falsos(monkeypatch)
    with planes_dca.mensaje_real_del_usuario("NO"):
        r = planes_dca._tool_gestionar_plan_dca({"accion": "descartar_ticket", "numero": 1})
    assert r["ok"]
    assert not _ejecutar(1, "SÍ")["ok"]
    assert ordenes == []
    assert planes_dca.correr_chequeo_diario(date(2026, 10, 6)) == []  # no vuelve a armarlo este mes
    assert len(planes_dca.correr_chequeo_diario(date(2026, 11, 5))) == 1


def test_editar_plan_ya_ejecutado_este_mes_aplica_desde_el_siguiente(monkeypatch):
    _plan_con_ticket(monkeypatch)
    _trades_falsos(monkeypatch)
    _ejecutar(1, "SÍ")
    r = planes_dca._tool_gestionar_plan_dca({"accion": "editar", "numero": 1, "monto_usd": 200})
    assert r["ok"]
    assert planes_dca.correr_chequeo_diario(date(2026, 10, 6)) == []  # octubre ya está cerrado
    mensajes = planes_dca.correr_chequeo_diario(date(2026, 11, 5))
    assert len(mensajes) == 1 and "USD 200.00 total" in mensajes[0]


def test_editar_con_ticket_pendiente_lo_reemplaza_con_los_datos_nuevos(monkeypatch):
    _plan_con_ticket(monkeypatch)
    planes_dca._tool_gestionar_plan_dca({"accion": "editar", "numero": 1, "monto_usd": 60})
    ordenes = _trades_falsos(monkeypatch)
    assert not _ejecutar(1, "SÍ")["ok"]  # el ticket viejo de USD 100 ya no existe
    mensajes = planes_dca.correr_chequeo_diario(date(2026, 10, 6))
    assert len(mensajes) == 1 and "USD 60.00 total" in mensajes[0]
    assert ordenes == []


def test_ejecucion_usa_la_foto_del_ticket_no_el_plan_actual(monkeypatch):
    # Si el plan cambiara por fuera del flujo de edición, se compra lo que el usuario vio en el ticket.
    _plan_con_ticket(monkeypatch, tickers=("MELI",), monto=100)
    database.actualizar_plan_dca(1, monto_usd=999)
    ordenes = _trades_falsos(monkeypatch)
    _ejecutar(1, "SÍ")
    assert [o["amount"] for o in ordenes] == [100.0]


def test_contexto_tickets_pendientes(monkeypatch):
    assert planes_dca.contexto_tickets_pendientes(date(2026, 10, 5)) == ""
    _crear(monkeypatch, date(2026, 10, 2), 5, 100, tickers=["MELI"])
    _crear(monkeypatch, date(2026, 10, 2), 5, 50, tickers=["NU"])
    _cash(monkeypatch, 500)
    planes_dca.correr_chequeo_diario(date(2026, 10, 5))
    ctx = planes_dca.contexto_tickets_pendientes(date(2026, 10, 5))
    assert ctx.startswith("PLANES_DCA_PENDIENTES")
    assert "plan 1" in ctx and "plan 2" in ctx and "SÍ plan N" in ctx
