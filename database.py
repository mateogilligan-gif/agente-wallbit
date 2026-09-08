import sqlite3
import json
from datetime import datetime
from pathlib import Path

from tool_registry import tool

DB_PATH = Path.home() / "agente-wallbit" / "agente.db"

def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS conversaciones (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, rol TEXT, mensaje TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS watchlist (ticker TEXT PRIMARY KEY, fecha_agregado TEXT, precio_alerta REAL, notas TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS alertas (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, precio_objetivo REAL, tipo TEXT, activa INTEGER DEFAULT 1, fecha_creacion TEXT, fecha_disparada TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS metas (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT, objetivo_usd REAL, actual_usd REAL DEFAULT 0, fecha_creacion TEXT, fecha_limite TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS presupuestos (categoria TEXT PRIMARY KEY, limite_usd REAL, mes_actual REAL DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS diario_trading (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, ticker TEXT, accion TEXT, precio REAL, monto REAL, razonamiento TEXT, sesgo_detectado TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS configuracion (clave TEXT PRIMARY KEY, valor TEXT, actualizado TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS bitacora (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, tipo TEXT, descripcion TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS decision_log (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, ticker TEXT, precio_momento REAL, veredicto TEXT, razonamiento TEXT, resultado TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS alertas_pct (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, umbral_pct REAL, direccion TEXT, referencia TEXT, activa INTEGER DEFAULT 1, fecha_creacion TEXT, fecha_disparada TEXT)''')

    # Migración: agregar avg_cost_manual si la tabla ya existía de antes sin esa columna
    try:
        c.execute("ALTER TABLE alertas_pct ADD COLUMN avg_cost_manual REAL")
    except sqlite3.OperationalError:
        pass  # la columna ya existe

    conn.commit()
    conn.close()

# ─── Conversaciones ────────────────────────────────────────────────────────────

def guardar_mensaje(rol, mensaje):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO conversaciones (fecha, rol, mensaje) VALUES (?, ?, ?)", (datetime.now().isoformat(), rol, mensaje))
    conn.commit()
    conn.close()

def obtener_historial(limite=20):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT rol, mensaje FROM conversaciones ORDER BY id DESC LIMIT ?", (limite,))
    rows = c.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

# ─── Configuración ─────────────────────────────────────────────────────────────

def guardar_config(clave, valor):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO configuracion (clave, valor, actualizado) VALUES (?, ?, ?)", (clave, valor, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def obtener_config(clave):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT valor FROM configuracion WHERE clave = ?", (clave,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

# ─── Watchlist ─────────────────────────────────────────────────────────────────

def agregar_watchlist(ticker, precio_alerta=None, notas=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO watchlist (ticker, fecha_agregado, precio_alerta, notas) VALUES (?, ?, ?, ?)",
              (ticker.upper(), datetime.now().isoformat(), precio_alerta, notas))
    conn.commit()
    conn.close()

def eliminar_watchlist(ticker):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker.upper(),))
    eliminado = conn.total_changes > 0
    conn.commit()
    conn.close()
    return eliminado

def obtener_watchlist():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT ticker, precio_alerta, notas FROM watchlist")
    rows = c.fetchall()
    conn.close()
    return rows

# ─── Alertas ───────────────────────────────────────────────────────────────────

def crear_alerta(ticker, precio, tipo):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO alertas (ticker, precio_objetivo, tipo, fecha_creacion) VALUES (?, ?, ?, ?)",
              (ticker.upper(), precio, tipo, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def desactivar_alerta(alerta_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE alertas SET activa = 0, fecha_disparada = ? WHERE id = ?",
              (datetime.now().isoformat(), alerta_id))
    eliminado = conn.total_changes > 0
    conn.commit()
    conn.close()
    return eliminado

def obtener_alertas_activas():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, ticker, precio_objetivo, tipo FROM alertas WHERE activa = 1")
    rows = c.fetchall()
    conn.close()
    return rows

# ─── Presupuestos ──────────────────────────────────────────────────────────────

def crear_presupuesto(categoria, limite_usd):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO presupuestos (categoria, limite_usd, mes_actual) VALUES (?, ?, 0)",
              (categoria.lower(), limite_usd))
    conn.commit()
    conn.close()

def obtener_presupuestos():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT categoria, limite_usd, mes_actual FROM presupuestos")
    rows = c.fetchall()
    conn.close()
    return [{"categoria": r[0], "limite": r[1], "gastado": r[2]} for r in rows]

def actualizar_gasto_presupuesto(categoria, monto_adicional):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE presupuestos SET mes_actual = mes_actual + ? WHERE categoria = ?",
              (monto_adicional, categoria.lower()))
    conn.commit()
    conn.close()

def resetear_presupuesto_mensual():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE presupuestos SET mes_actual = 0")
    conn.commit()
    conn.close()

# ─── Metas ─────────────────────────────────────────────────────────────────────

def crear_meta(nombre, objetivo_usd, fecha_limite=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO metas (nombre, objetivo_usd, actual_usd, fecha_creacion, fecha_limite) VALUES (?, ?, 0, ?, ?)",
              (nombre, objetivo_usd, datetime.now().isoformat(), fecha_limite))
    conn.commit()
    conn.close()

def obtener_metas():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT nombre, objetivo_usd, actual_usd, fecha_limite FROM metas")
    rows = c.fetchall()
    conn.close()
    return [{"nombre": r[0], "objetivo": r[1], "actual": r[2], "fecha_limite": r[3]} for r in rows]

def actualizar_progreso_meta(nombre, actual_usd):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE metas SET actual_usd = ? WHERE nombre = ?", (actual_usd, nombre))
    conn.commit()
    conn.close()

# ─── Diario de trading ─────────────────────────────────────────────────────────

def guardar_trade_diario(ticker, accion, precio, monto, razonamiento, sesgo=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO diario_trading (fecha, ticker, accion, precio, monto, razonamiento, sesgo_detectado) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (datetime.now().isoformat(), ticker, accion, precio, monto, razonamiento, sesgo))
    conn.commit()
    conn.close()

def obtener_diario_trading(limite=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT fecha, ticker, accion, precio, monto, razonamiento FROM diario_trading ORDER BY id DESC LIMIT ?", (limite,))
    rows = c.fetchall()
    conn.close()
    return rows

# ─── Decision Log ──────────────────────────────────────────────────────────────

def guardar_decision(ticker, precio_momento, veredicto, razonamiento):
    """Guarda una decisión/análisis de un ticker para trackear si la tesis fue correcta."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO decision_log (fecha, ticker, precio_momento, veredicto, razonamiento, resultado) VALUES (?, ?, ?, ?, ?, ?)",
        (datetime.now().isoformat(), ticker.upper(), precio_momento, veredicto, razonamiento, "pendiente")
    )
    conn.commit()
    conn.close()

def obtener_decisiones_ticker(ticker, limite=5):
    """Obtiene el historial de decisiones sobre un ticker específico."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT fecha, precio_momento, veredicto, razonamiento, resultado FROM decision_log WHERE ticker = ? ORDER BY id DESC LIMIT ?",
        (ticker.upper(), limite)
    )
    rows = c.fetchall()
    conn.close()
    return [{"fecha": r[0], "precio": r[1], "veredicto": r[2], "razonamiento": r[3], "resultado": r[4]} for r in rows]

def actualizar_resultado_decision(ticker, resultado):
    """Actualiza el resultado de la última decisión sobre un ticker."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE decision_log SET resultado = ? WHERE ticker = ? AND id = (SELECT MAX(id) FROM decision_log WHERE ticker = ?)",
        (resultado, ticker.upper(), ticker.upper())
    )
    conn.commit()
    conn.close()

# ─── Alertas por porcentaje (precio externo, no depende de Wallbit) ───────────

def crear_alerta_pct(ticker, umbral_pct, direccion="ambas", referencia="dia", avg_cost_manual=None):
    """
    direccion: 'sube' | 'baja' | 'ambas'
    referencia: 'dia' (vs cierre anterior) | 'compra' (vs avg_cost)
    avg_cost_manual: precio de compra dado a mano, para cuando Wallbit no lo expone
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO alertas_pct (ticker, umbral_pct, direccion, referencia, fecha_creacion, avg_cost_manual) VALUES (?, ?, ?, ?, ?, ?)",
        (ticker.upper(), umbral_pct, direccion, referencia, datetime.now().isoformat(), avg_cost_manual)
    )
    conn.commit()
    conn.close()

def obtener_alertas_pct_activas():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, ticker, umbral_pct, direccion, referencia, avg_cost_manual FROM alertas_pct WHERE activa = 1")
    rows = c.fetchall()
    conn.close()
    return rows

def desactivar_alerta_pct(alerta_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE alertas_pct SET activa = 0, fecha_disparada = ? WHERE id = ?",
              (datetime.now().isoformat(), alerta_id))
    eliminado = conn.total_changes > 0
    conn.commit()
    conn.close()
    return eliminado

# ─── Bitácora ──────────────────────────────────────────────────────────────────

def registrar_bitacora(tipo, descripcion):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO bitacora (fecha, tipo, descripcion) VALUES (?, ?, ?)",
              (datetime.now().isoformat(), tipo, descripcion))
    conn.commit()
    conn.close()

# ─── Tools (Anthropic Tool Use) ────────────────────────────────────────────────
# Todo lo que gestiona estado local (watchlist, alertas, presupuesto, metas,
# config, diario, decision log) vive acá porque ya son funciones de este
# archivo — el handler de la tool es solo el "acción" (crear/listar/etc)
# sobre esas mismas funciones, sin depender de ningún otro módulo.

@tool(
    "manage_watchlist",
    "Watchlist: agregar/eliminar/listar tickers.",
    {"type": "object", "properties": {"accion": {"type": "string", "enum": ["agregar", "eliminar", "listar"]}, "ticker": {"type": "string"}, "notas": {"type": "string"}}, "required": ["accion"]}
)
def _tool_manage_watchlist(inputs: dict):
    accion = inputs["accion"]
    if accion == "agregar":
        ticker = inputs.get("ticker", "").upper()
        if not ticker:
            return "Error: se necesita un ticker para agregar"
        agregar_watchlist(ticker, notas=inputs.get("notas", ""))
        return {"ok": True, "data": f"✅ {ticker} agregado a la watchlist"}
    elif accion == "eliminar":
        ticker = inputs.get("ticker", "").upper()
        if not ticker:
            return "Error: se necesita un ticker para eliminar"
        ok = eliminar_watchlist(ticker)
        return {"ok": True, "data": f"{'✅ ' + ticker + ' eliminado' if ok else '⚠️ ' + ticker + ' no estaba en la watchlist'}"}
    elif accion == "listar":
        wl = obtener_watchlist()
        if wl:
            return {"ok": True, "data": [{"ticker": r[0], "precio_alerta": r[1], "notas": r[2]} for r in wl]}
        else:
            return {"ok": True, "data": "La watchlist está vacía"}
    else:
        return {"ok": False, "error": f"Acción desconocida para manage_watchlist: {accion}"}


@tool(
    "manage_alerts",
    "Alertas de precio ABSOLUTO: crear/eliminar/listar (ej 'avisame si AAPL baja de $150'). Para alertas de PORCENTAJE de movimiento (ej 'avisame si sube más de 5%'), usar manage_pct_alerts.",
    {"type": "object", "properties": {"accion": {"type": "string", "enum": ["crear", "eliminar", "listar"]}, "ticker": {"type": "string"}, "precio": {"type": "number"}, "tipo": {"type": "string", "enum": ["minimo", "maximo"]}, "alerta_id": {"type": "integer"}}, "required": ["accion"]}
)
def _tool_manage_alerts(inputs: dict):
    accion = inputs["accion"]
    if accion == "crear":
        ticker = inputs.get("ticker", "").upper()
        precio = inputs.get("precio")
        tipo = inputs.get("tipo", "minimo")
        if not ticker or precio is None:
            return "Error: se necesita ticker y precio para crear alerta"
        crear_alerta(ticker, precio, tipo)
        return {"ok": True, "data": f"✅ Alerta creada: avisar si {ticker} {'baja de' if tipo == 'minimo' else 'sube a'} ${precio}"}
    elif accion == "eliminar":
        alerta_id = inputs.get("alerta_id")
        if alerta_id is None:
            return "Error: se necesita alerta_id para eliminar"
        ok = desactivar_alerta(alerta_id)
        return {"ok": True, "data": f"{'✅ Alerta #' + str(alerta_id) + ' desactivada' if ok else '⚠️ No se encontró la alerta'}"}
    elif accion == "listar":
        alertas = obtener_alertas_activas()
        if alertas:
            return {"ok": True, "data": [{"id": a[0], "ticker": a[1], "precio_objetivo": a[2], "tipo": a[3]} for a in alertas]}
        else:
            return {"ok": True, "data": "No hay alertas activas"}
    else:
        return {"ok": False, "error": f"Acción desconocida para manage_alerts: {accion}"}


@tool(
    "manage_pct_alerts",
    "Alertas de PORCENTAJE de movimiento sobre un ticker (crear/eliminar/listar). El precio actual siempre se obtiene de yfinance (fuente externa), no de Wallbit. Dos referencias: 'dia' (% vs cierre de ayer) o 'compra' (% vs precio de compra, para P&L). IMPORTANTE: Wallbit hoy NO expone el costo promedio de compra en ningún campo — para referencia='compra' hay que pedirle al usuario su precio de compra si no lo dijo, y pasarlo en avg_cost_manual. Sin ese dato la alerta se crea pero nunca podrá dispararse.",
    {
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
)
def _tool_manage_pct_alerts(inputs: dict):
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
        return {"ok": True, "data": f"✅ Alerta creada: avisar si {ticker} se mueve {direccion} {umbral_pct}% ({ref_str}).{aviso}"}
    elif accion == "eliminar":
        alerta_id = inputs.get("alerta_id")
        if alerta_id is None:
            return "Error: se necesita alerta_id para eliminar"
        ok = desactivar_alerta_pct(alerta_id)
        return {"ok": True, "data": f"{'✅ Alerta #' + str(alerta_id) + ' desactivada' if ok else '⚠️ No se encontró la alerta'}"}
    elif accion == "listar":
        alertas_pct = obtener_alertas_pct_activas()
        if alertas_pct:
            return {"ok": True, "data": [
                {
                    "id": a[0], "ticker": a[1], "umbral_pct": a[2], "direccion": a[3],
                    "referencia": a[4], "avg_cost_manual": a[5],
                    "funcional": a[4] == "dia" or a[5] is not None
                }
                for a in alertas_pct
            ]}
        else:
            return {"ok": True, "data": "No hay alertas de porcentaje activas"}
    else:
        return {"ok": False, "error": f"Acción desconocida para manage_pct_alerts: {accion}"}


@tool(
    "manage_budget",
    "Presupuesto mensual por categorías.",
    {"type": "object", "properties": {"accion": {"type": "string", "enum": ["crear", "listar", "actualizar_gasto"]}, "categoria": {"type": "string"}, "limite_usd": {"type": "number"}, "monto_adicional": {"type": "number"}}, "required": ["accion"]}
)
def _tool_manage_budget(inputs: dict):
    accion = inputs["accion"]
    if accion == "crear":
        categoria = inputs.get("categoria")
        limite = inputs.get("limite_usd")
        if not categoria or limite is None:
            return "Error: se necesita categoría y límite_usd"
        crear_presupuesto(categoria, limite)
        return {"ok": True, "data": f"✅ Presupuesto '{categoria}': ${limite}/mes"}
    elif accion == "listar":
        presupuestos = obtener_presupuestos()
        if presupuestos:
            return {"ok": True, "data": presupuestos}
        else:
            return {"ok": True, "data": "No hay presupuestos configurados"}
    elif accion == "actualizar_gasto":
        categoria = inputs.get("categoria")
        monto = inputs.get("monto_adicional")
        if not categoria or monto is None:
            return "Error: se necesita categoría y monto_adicional"
        actualizar_gasto_presupuesto(categoria, monto)
        return {"ok": True, "data": f"✅ Sumado ${monto} al gasto de '{categoria}'"}
    else:
        return {"ok": False, "error": f"Acción desconocida para manage_budget: {accion}"}


@tool(
    "manage_goals",
    "Metas financieras: crear/listar/actualizar.",
    {"type": "object", "properties": {"accion": {"type": "string", "enum": ["crear", "listar", "actualizar_progreso"]}, "nombre": {"type": "string"}, "objetivo_usd": {"type": "number"}, "actual_usd": {"type": "number"}, "fecha_limite": {"type": "string"}}, "required": ["accion"]}
)
def _tool_manage_goals(inputs: dict):
    accion = inputs["accion"]
    if accion == "crear":
        nombre_meta = inputs.get("nombre")
        objetivo = inputs.get("objetivo_usd")
        if not nombre_meta or objetivo is None:
            return "Error: se necesita nombre y objetivo_usd"
        crear_meta(nombre_meta, objetivo, inputs.get("fecha_limite"))
        return {"ok": True, "data": f"✅ Meta '{nombre_meta}': ${objetivo}"}
    elif accion == "listar":
        metas = obtener_metas()
        if metas:
            return {"ok": True, "data": metas}
        else:
            return {"ok": True, "data": "No hay metas configuradas"}
    elif accion == "actualizar_progreso":
        nombre_meta = inputs.get("nombre")
        actual = inputs.get("actual_usd")
        if not nombre_meta or actual is None:
            return "Error: se necesita nombre y actual_usd"
        actualizar_progreso_meta(nombre_meta, actual)
        return {"ok": True, "data": f"✅ Progreso de '{nombre_meta}' actualizado a ${actual}"}
    else:
        return {"ok": False, "error": f"Acción desconocida para manage_goals: {accion}"}


@tool(
    "save_config",
    "Guarda/lee configuración (MONTO_SUELDO, PORCENTAJE_DCA, etc).",
    {"type": "object", "properties": {"accion": {"type": "string", "enum": ["guardar", "leer"]}, "clave": {"type": "string"}, "valor": {"type": "string"}}, "required": ["accion", "clave"]}
)
def _tool_save_config(inputs: dict):
    accion = inputs["accion"]
    clave = inputs["clave"]
    if accion == "guardar":
        valor = inputs.get("valor")
        if valor is None:
            return "Error: se necesita un valor para guardar"
        guardar_config(clave, str(valor))
        return {"ok": True, "data": f"✅ Guardado: {clave} = {valor}"}
    elif accion == "leer":
        valor = obtener_config(clave)
        return {"ok": True, "data": {clave: valor if valor else "no configurado"}}
    else:
        return {"ok": False, "error": f"Acción desconocida para save_config: {accion}"}


@tool(
    "trading_diary",
    "Diario de trades: guardar/leer historial.",
    {"type": "object", "properties": {"accion": {"type": "string", "enum": ["guardar", "leer"]}, "ticker": {"type": "string"}, "accion_trade": {"type": "string"}, "precio": {"type": "number"}, "monto": {"type": "number"}, "razonamiento": {"type": "string"}, "sesgo": {"type": "string"}, "limite": {"type": "integer"}}, "required": ["accion"]}
)
def _tool_trading_diary(inputs: dict):
    accion = inputs["accion"]
    if accion == "guardar":
        ticker = inputs.get("ticker", "")
        accion_trade = inputs.get("accion_trade", "")
        precio = inputs.get("precio", 0)
        monto = inputs.get("monto", 0)
        razonamiento = inputs.get("razonamiento", "")
        sesgo = inputs.get("sesgo", "")
        guardar_trade_diario(ticker, accion_trade, precio, monto, razonamiento, sesgo)
        return {"ok": True, "data": "✅ Entrada guardada en el diario de trading"}
    elif accion == "leer":
        limite = inputs.get("limite", 10)
        entradas = obtener_diario_trading(limite)
        if entradas:
            return {"ok": True, "data": [
                {"fecha": e[0], "ticker": e[1], "accion": e[2], "precio": e[3], "monto": e[4], "razonamiento": e[5]}
                for e in entradas
            ]}
        else:
            return {"ok": True, "data": "El diario de trading está vacío"}
    else:
        return {"ok": False, "error": f"Acción desconocida para trading_diary: {accion}"}


@tool(
    "decision_log",
    "Guarda o lee el historial de análisis sobre un ticker. Guardar: registra veredicto (alcista/bajista/neutral) + razonamiento + precio actual. Leer: muestra análisis anteriores sobre ese ticker para validar si la tesis fue correcta.",
    {"type": "object", "properties": {"accion": {"type": "string", "enum": ["guardar", "leer"]}, "ticker": {"type": "string"}, "precio_momento": {"type": "number"}, "veredicto": {"type": "string", "enum": ["alcista", "bajista", "neutral"]}, "razonamiento": {"type": "string"}, "resultado": {"type": "string"}}, "required": ["accion", "ticker"]}
)
def _tool_decision_log(inputs: dict):
    accion = inputs["accion"]
    ticker = inputs["ticker"].upper()
    if accion == "guardar":
        veredicto = inputs.get("veredicto", "neutral")
        razonamiento = inputs.get("razonamiento", "")
        precio = inputs.get("precio_momento", 0)
        guardar_decision(ticker, precio, veredicto, razonamiento)
        return {"ok": True, "data": f"Decision guardada: {ticker} — {veredicto}"}
    elif accion == "leer":
        historial = obtener_decisiones_ticker(ticker, limite=5)
        if historial:
            return {"ok": True, "data": historial}
        else:
            return {"ok": True, "data": f"Sin historial previo de decisiones para {ticker}"}
    else:
        return {"ok": False, "error": f"Acción desconocida para decision_log: {accion}"}
