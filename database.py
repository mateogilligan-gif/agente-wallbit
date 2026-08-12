import sqlite3
import json
from datetime import datetime
from pathlib import Path

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

# ─── Bitácora ──────────────────────────────────────────────────────────────────

def registrar_bitacora(tipo, descripcion):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO bitacora (fecha, tipo, descripcion) VALUES (?, ?, ?)",
              (datetime.now().isoformat(), tipo, descripcion))
    conn.commit()
    conn.close()
