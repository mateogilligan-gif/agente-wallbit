"""
planes_dca.py — Planes de DCA programados: el día X de cada mes, comprar un
monto fijo en USD repartido entre una lista fija de tickers.

DCA es disciplina, no análisis: el bot compra lo configurado, sin research.
Parte de que la plata ya está en la cuenta de Inversión (Wallbit no tiene
API para mover plata entre cuentas) — el bot solo chequea si alcanza, arma
el ticket y espera el SÍ.

Todo lo que decide algo (qué día toca, si un mes todavía está abierto,
cuánta plata alcanza para qué plan, si la confirmación es válida, el mínimo
por orden) son funciones puras acá, que reciben "hoy" como parámetro para
poder testearlas. El LLM solo conversa: las tools de abajo validan por
código y la ejecución pasa sí o sí por ejecutar_plan_dca.

Vocabulario:
- periodo: el mes al que corresponde una compra, 'YYYY-MM'. Puede
  ejecutarse en una fecha de otro mes (ej. día 31 de octubre que cae sábado
  se compra el lunes 2 de noviembre, pero cuenta como la de octubre).
- fecha programada: el día real de compra de un periodo, ya corrido por
  fin de mes y fin de semana (ver fecha_programada).
- periodo accionable: el periodo cuya compra se puede hacer hoy (ver
  periodo_accionable) — como mucho uno por plan, y nunca uno ya cerrado.
"""
import calendar
import contextlib
import contextvars
import json
import re
import unicodedata
from datetime import date, timedelta
from typing import Optional

import database
import wallbit_client
from tool_registry import tool

# Tope de tickers por split: más allá de esto el ticket de confirmación deja
# de ser algo que se pueda leer y decidir en 5 segundos (se vuelve un "SÍ"
# ciego, justo lo que la regla de confirmación quiere evitar), y el monto por
# ticker empieza a quedar muy chico. Es un límite duro acá, no una sugerencia
# del LLM, para que no dependa de que el modelo se acuerde de respetarlo.
MAX_TICKERS_SPLIT = 10

# Tope de planes por usuario.
MAX_PLANES_DCA = 5

# Compra mínima de Wallbit por orden. Se valida al configurar el plan (no el
# día de la compra) para que nunca llegue un ticket con una orden imposible.
MINIMO_POR_ORDEN_USD = 1.0

# Estados de una ejecución (fila de ejecuciones_dca) que "cierran" el mes de
# un plan: con cualquiera de estos el job no vuelve a armar ticket ese mes.
# 'sin_fondos' NO está: es el aviso de falta de plata, y se sigue reintentando.
ESTADOS_CERRADOS = {"pendiente", "ejecutando", "ejecutado", "descartado"}


# ─── Split (reparto entre tickers) ─────────────────────────────────────────

def validar_split(split: list) -> tuple:
    """
    Valida una lista de asignaciones [{"ticker": "NVDA", "pct": 50}, ...].
    Devuelve (True, None) si es válida, (False, "motivo") si no.
    """
    if not split or not isinstance(split, list):
        return False, "El split no puede estar vacío"

    if len(split) > MAX_TICKERS_SPLIT:
        return False, f"Máximo {MAX_TICKERS_SPLIT} tickers por split (pediste {len(split)}). Elegí menos o agrupá en un ETF."

    for item in split:
        if not isinstance(item, dict) or "ticker" not in item or "pct" not in item:
            return False, "Cada asignación necesita 'ticker' y 'pct'"
        if not isinstance(item["pct"], (int, float)) or item["pct"] <= 0:
            return False, f"Porcentaje inválido para {item.get('ticker', '?')}: debe ser un número > 0"

    suma = sum(item["pct"] for item in split)
    if abs(suma - 100) > 0.5:
        return False, f"Los porcentajes suman {suma}%, deberían sumar 100%"

    return True, None


def parsear_split_json(texto: str) -> list:
    """
    Parsea el split guardado en la DB (columna split_json) a una lista de
    dicts. Tira ValueError con un mensaje claro si el JSON es inválido o la
    validación de porcentajes falla.
    """
    try:
        split = json.loads(texto)
    except (json.JSONDecodeError, TypeError) as e:
        raise ValueError(f"Split guardado no es JSON válido: {e}")

    ok, motivo = validar_split(split)
    if not ok:
        raise ValueError(motivo)

    return split


def split_equitativo(tickers: list) -> list:
    """
    Función pura: dada una lista de tickers, devuelve un split con porcentajes
    iguales para cada uno. Igual que en calcular_montos, cuando 100 no es
    divisible exacto entre la cantidad de tickers (ej. 3 tickers -> 33.33 x3
    no da 100 justo), el resto de redondeo se le suma al último para que la
    suma de porcentajes sea siempre exactamente 100 — así el split que arma
    "reparto equitativo" siempre pasa validar_split sin ajustes manuales.
    """
    if not tickers or not isinstance(tickers, list):
        raise ValueError("Necesito al menos un ticker para armar un reparto equitativo")
    if len(tickers) > MAX_TICKERS_SPLIT:
        raise ValueError(f"Máximo {MAX_TICKERS_SPLIT} tickers por split (pediste {len(tickers)}). Elegí menos o agrupá en un ETF.")

    tickers_limpios = [t.upper() for t in tickers]
    n = len(tickers_limpios)
    pct_base = round(100 / n, 2)

    split = [{"ticker": t, "pct": pct_base} for t in tickers_limpios]
    resto = round(100 - sum(item["pct"] for item in split), 2)
    if resto != 0:
        split[-1]["pct"] = round(split[-1]["pct"] + resto, 2)

    return split


def calcular_montos(monto_total: float, split: list) -> list:
    """
    Función pura: dado un monto total y una lista de asignaciones por
    porcentaje, devuelve el monto en dólares exacto para cada ticker.

    El redondeo a 2 decimales de cada asignación puede dejar un resto de
    unos pocos centavos por errores de redondeo acumulados (ej. 33.33 x 3 =
    99.99, no 100.00) — ese resto se le suma a la asignación más grande para
    que la suma final sea EXACTAMENTE monto_total, nunca unos centavos de más
    o de menos.
    """
    ok, motivo = validar_split(split)
    if not ok:
        raise ValueError(motivo)
    if monto_total <= 0:
        raise ValueError("El monto total tiene que ser mayor a 0")

    asignaciones = []
    for item in split:
        monto = round(monto_total * item["pct"] / 100, 2)
        asignaciones.append({"ticker": item["ticker"].upper(), "pct": item["pct"], "monto": monto})

    resto = round(monto_total - sum(a["monto"] for a in asignaciones), 2)
    if resto != 0:
        mayor = max(asignaciones, key=lambda a: a["monto"])
        mayor["monto"] = round(mayor["monto"] + resto, 2)

    return asignaciones


def monto_minimo_para_split(split: list) -> float:
    """El monto total más chico (en centavos) con el que ninguna orden del split queda por debajo de MINIMO_POR_ORDEN_USD."""
    menor_pct = min(item["pct"] for item in split)
    centavos = int(MINIMO_POR_ORDEN_USD * 100 * 100 / menor_pct)  # punto de partida, se ajusta por redondeo abajo
    while True:
        monto = centavos / 100
        if monto > 0 and min(a["monto"] for a in calcular_montos(monto, split)) >= MINIMO_POR_ORDEN_USD:
            return monto
        centavos += 1


def armar_texto_ticket(monto_total: float, asignaciones: list, titulo: str = "Ticket de compra", respuesta_si: str = "SÍ", respuesta_no: str = "NO") -> str:
    """Texto determinístico del ticket, para no depender de que el LLM sume bien."""
    lineas = [f"{titulo} — USD {monto_total:.2f} total:"]
    for a in asignaciones:
        lineas.append(f"- {a['ticker']}: USD {a['monto']:.2f} ({a['pct']}%) — MARKET")
    lineas.append(f"¿Confirmás las {len(asignaciones)} compras? Respondé {respuesta_si} para comprar o {respuesta_no} para saltear este mes.")
    return "\n".join(lineas)


# ─── Validación de un plan ─────────────────────────────────────────────────

def validar_datos_plan(dia, monto_usd, split) -> Optional[str]:
    """Valida día, monto y split de un plan (sin red). Devuelve el mensaje de error, o None si está todo bien."""
    if not isinstance(dia, int) or isinstance(dia, bool) or not (1 <= dia <= 31):
        return f"El día tiene que ser un número entero entre 1 y 31 (recibí: {dia!r})"
    if not isinstance(monto_usd, (int, float)) or isinstance(monto_usd, bool) or monto_usd <= 0:
        return f"El monto tiene que ser un número mayor a 0 (recibí: {monto_usd!r})"

    ok, motivo = validar_split(split)
    if not ok:
        return motivo
    tickers = [item["ticker"].upper() for item in split]
    if len(set(tickers)) != len(tickers):
        return "Hay tickers repetidos en el reparto — cada ticker puede aparecer una sola vez"

    asignaciones = calcular_montos(monto_usd, split)
    chicas = [a for a in asignaciones if a["monto"] < MINIMO_POR_ORDEN_USD]
    if chicas:
        detalle = ", ".join(f"{a['ticker']} USD {a['monto']:.2f}" for a in chicas)
        minimo = monto_minimo_para_split(split)
        return (
            f"Con USD {monto_usd:.2f} repartidos así, algunas órdenes quedan por debajo del mínimo de Wallbit "
            f"(USD {MINIMO_POR_ORDEN_USD:.0f} por orden): {detalle}. "
            f"Subí el monto a al menos USD {minimo:.2f} o usá menos tickers."
        )
    return None


def resumen_plan(numero, nombre, dia, monto_usd, split) -> str:
    """Ej: 'Plan 1: día 5, USD 100.00, MELI 33.33% / NU 33.33% / AAPL 33.34%'."""
    etiqueta = f"Plan {numero}" + (f" ({nombre})" if nombre else "")
    reparto = " / ".join(f"{item['ticker'].upper()} {item['pct']}%" for item in split)
    return f"{etiqueta}: día {dia}, USD {monto_usd:.2f}, {reparto}"


def primer_numero_libre(numeros_usados) -> Optional[int]:
    """El número de plan más chico libre entre 1 y MAX_PLANES_DCA, o None si ya hay MAX_PLANES_DCA planes."""
    for n in range(1, MAX_PLANES_DCA + 1):
        if n not in numeros_usados:
            return n
    return None


# ─── Fechas ────────────────────────────────────────────────────────────────

def _sumar_meses(anio: int, mes: int, n: int) -> tuple:
    total = anio * 12 + (mes - 1) + n
    return total // 12, total % 12 + 1


def periodo_de(anio: int, mes: int) -> str:
    return f"{anio:04d}-{mes:02d}"


def fecha_programada(dia: int, anio: int, mes: int) -> date:
    """
    Fecha real de compra del plan en ese mes. Si el día no existe en el mes
    (31 en abril, 30 en febrero) se usa el último día del mes. Si cae sábado
    o domingo, pasa al lunes siguiente — aunque ese lunes sea del mes
    siguiente (sigue contando como la compra de este mes). Feriados de
    EE.UU. fuera de alcance: si Wallbit rechaza la orden, se informa el error.
    """
    ultimo = calendar.monthrange(anio, mes)[1]
    fecha = date(anio, mes, min(dia, ultimo))
    if fecha.weekday() == 5:      # sábado
        fecha += timedelta(days=2)
    elif fecha.weekday() == 6:    # domingo
        fecha += timedelta(days=1)
    return fecha


def periodo_accionable(dia: int, hoy: date) -> Optional[dict]:
    """
    El periodo cuya compra se puede hacer HOY, o None. Un periodo queda
    abierto desde su fecha programada hasta lo primero entre (a) el fin del
    mes calendario de esa fecha y (b) el día anterior a la fecha programada
    del periodo siguiente. Así:
    - si el bot estuvo apagado el día del plan, se pone al día dentro de ese
      mismo mes (atrasado=True), pero nunca recupera un mes anterior;
    - el lunes corrido al mes siguiente sigue contando como el mes original;
    - nunca hay dos periodos abiertos a la vez para el mismo plan.
    """
    for anio, mes in ((hoy.year, hoy.month), _sumar_meses(hoy.year, hoy.month, -1)):
        programada = fecha_programada(dia, anio, mes)
        fin_de_mes = date(programada.year, programada.month, calendar.monthrange(programada.year, programada.month)[1])
        siguiente = fecha_programada(dia, *_sumar_meses(anio, mes, 1))
        cierre = min(fin_de_mes, siguiente - timedelta(days=1))
        if programada <= hoy <= cierre:
            return {"periodo": periodo_de(anio, mes), "fecha_programada": programada, "atrasado": hoy > programada}
    return None


def primer_periodo_desde(dia: int, fecha: date) -> str:
    """
    Primer periodo que toma un plan creado (o reactivado) en esta fecha: el
    mes en curso si la fecha programada de este mes es hoy o todavía no
    llegó; si ya pasó, el mes siguiente. Así crear o reactivar un plan nunca
    dispara un ticket "atrasado" de inmediato.
    """
    if fecha <= fecha_programada(dia, fecha.year, fecha.month):
        return periodo_de(fecha.year, fecha.month)
    return periodo_de(*_sumar_meses(fecha.year, fecha.month, 1))


def proxima_fecha_compra(plan: dict, ejecuciones: list, hoy: date) -> date:
    """La próxima fecha en que el job va a intentar la compra de este plan (para mostrarla al listar)."""
    cerrados = {e["periodo"] for e in ejecuciones if e["plan_id"] == plan["id"] and e["estado"] in ESTADOS_CERRADOS}
    acc = periodo_accionable(plan["dia"], hoy)
    if acc and acc["periodo"] >= plan["desde_periodo"] and acc["periodo"] not in cerrados:
        return hoy
    anio, mes = hoy.year, hoy.month
    for _ in range(24):
        periodo = periodo_de(anio, mes)
        programada = fecha_programada(plan["dia"], anio, mes)
        if programada > hoy and periodo >= plan["desde_periodo"] and periodo not in cerrados:
            return programada
        anio, mes = _sumar_meses(anio, mes, 1)
    return fecha_programada(plan["dia"], anio, mes)


# ─── Qué hacer hoy (job diario) ────────────────────────────────────────────

def _ejecucion(ejecuciones: list, plan_id: int, periodo: str) -> Optional[dict]:
    for e in ejecuciones:
        if e["plan_id"] == plan_id and e["periodo"] == periodo:
            return e
    return None


def pendientes_vigentes(planes: list, ejecuciones: list, hoy: date) -> list:
    """
    Tickets pendientes que todavía se pueden confirmar hoy: estado
    'pendiente', plan activo, y su periodo sigue siendo el accionable. Un
    ticket de un mes que ya cerró queda vencido (no se ejecuta ni reserva plata).
    Devuelve [{"plan": plan, "ejecucion": ejecucion}] ordenado por número de plan.
    """
    vigentes = []
    for plan in sorted(planes, key=lambda p: p["numero"]):
        if not plan["activo"]:
            continue
        acc = periodo_accionable(plan["dia"], hoy)
        if not acc:
            continue
        e = _ejecucion(ejecuciones, plan["id"], acc["periodo"])
        if e and e["estado"] == "pendiente":
            vigentes.append({"plan": plan, "ejecucion": e})
    return vigentes


def cash_reservado(planes: list, ejecuciones: list, hoy: date) -> float:
    """Plata ya comprometida en tickets pendientes sin confirmar — no se puede usar para otro plan."""
    return round(sum(v["ejecucion"]["monto_usd"] for v in pendientes_vigentes(planes, ejecuciones, hoy)), 2)


def planes_que_tocan_hoy(planes: list, ejecuciones: list, hoy: date) -> list:
    """
    Planes activos con un periodo accionable hoy que todavía no se cerró
    (sin ticket, sin ejecución, sin descarte). Incluye los que ya recibieron
    el aviso de falta de plata ese mes (ya_avisado=True), para reintentar.
    Ordenados por número de plan — es el orden en que se reparte la plata.
    """
    candidatos = []
    for plan in sorted(planes, key=lambda p: p["numero"]):
        if not plan["activo"]:
            continue
        acc = periodo_accionable(plan["dia"], hoy)
        if not acc or acc["periodo"] < plan["desde_periodo"]:
            continue
        e = _ejecucion(ejecuciones, plan["id"], acc["periodo"])
        if e and e["estado"] in ESTADOS_CERRADOS:
            continue
        candidatos.append({**acc, "plan": plan, "ya_avisado": bool(e and e["estado"] == "sin_fondos")})
    return candidatos


def repartir_cash(candidatos: list, cash_disponible: float) -> list:
    """
    Reparte la plata disponible entre los planes que tocan hoy, en orden de
    número de plan. Cada plan se compra completo o no se compra (nunca
    parcial). Devuelve una acción por candidato:
    {"tipo": "ticket" | "falta_fondos", "faltante": X, "disponible": Y, ...candidato}.
    """
    acciones = []
    disponible = round(cash_disponible, 2)
    for c in sorted(candidatos, key=lambda c: c["plan"]["numero"]):
        monto = c["plan"]["monto_usd"]
        if monto <= disponible + 1e-9:
            acciones.append({**c, "tipo": "ticket", "faltante": 0.0, "disponible": disponible})
            disponible = round(disponible - monto, 2)
        else:
            acciones.append({**c, "tipo": "falta_fondos", "faltante": round(monto - max(disponible, 0), 2), "disponible": max(disponible, 0)})
    return acciones


def ejecuciones_interrumpidas(ejecuciones: list) -> list:
    """Ejecuciones que quedaron 'ejecutando' (el bot se cayó en medio de la compra) y todavía no se avisaron."""
    return [e for e in ejecuciones if e["estado"] == "ejecutando" and not e["avisado"]]


def instruccion_respuesta(numero: int, cantidad_pendientes: int) -> tuple:
    """Qué tiene que responder el usuario: 'SÍ' si hay un solo ticket pendiente, 'SÍ plan N' si hay más de uno."""
    if cantidad_pendientes > 1:
        return f"SÍ plan {numero}", f"NO plan {numero}"
    return "SÍ", "NO"


def _titulo_ticket(plan: dict, periodo: str, programada: date, atrasado: bool) -> str:
    titulo = f"Plan {plan['numero']}" + (f" ({plan['nombre']})" if plan.get("nombre") else "") + f" — compra programada de {periodo}"
    if atrasado:
        titulo += f" [EJECUCIÓN ATRASADA: tocaba el {programada.strftime('%d/%m')}, el bot no corrió ese día]"
    return titulo


def texto_falta_fondos(numero: int, monto: float, disponible: float, faltante: float) -> str:
    return (
        f"Plan {numero}: hoy toca la compra de USD {monto:.2f}, pero en la cuenta de Inversión hay "
        f"USD {disponible:.2f} libres (descontando lo reservado para otros planes). "
        f"Para el plan {numero} te faltan USD {faltante:.2f} en la cuenta de Inversión. "
        f"Transferí la diferencia desde la app de Wallbit: reviso de nuevo en los próximos días y te armo "
        f"el ticket cuando alcance. Este aviso no se repite este mes."
    )


def texto_interrumpida(e: dict) -> str:
    return (
        f"⚠️ El plan {e['plan_numero']} ({e['periodo']}) quedó a medio ejecutar: el bot se cortó mientras "
        f"mandaba las órdenes. No lo voy a reintentar solo, para no comprar dos veces. Revisá en la app de "
        f"Wallbit qué órdenes salieron y, si falta alguna, comprala a mano."
    )


def _split_del_plan(plan: dict) -> list:
    return parsear_split_json(plan["split_json"])


def correr_chequeo_diario(hoy: date) -> list:
    """
    Lo que hace el job diario (telegram_bot.chequear_planes_dca_diario). No
    llama al LLM nunca. Devuelve la lista de mensajes a mandar por Telegram.

    1. Avisa (una sola vez) las ejecuciones que quedaron a medio hacer.
    2. Si no hay planes activos, o ninguno toca hoy, termina sin llamar a Wallbit.
    3. Lee el efectivo de la cuenta de Inversión. Si no se pudo leer, no
       hace nada más (reintenta en la próxima corrida, sin aviso de falta).
    4. Reparte la plata por número de plan: ticket pendiente para los que
       alcanzan, aviso de falta (uno por mes por plan) para los demás.
    """
    mensajes = []
    ejecuciones = database.obtener_ejecuciones_dca()

    for e in ejecuciones_interrumpidas(ejecuciones):
        mensajes.append(texto_interrumpida(e))
        database.marcar_avisado_ejecucion_dca(e["id"])

    planes = database.obtener_planes_dca(solo_activos=True)
    if not planes:
        return mensajes

    candidatos = planes_que_tocan_hoy(planes, ejecuciones, hoy)
    if not candidatos:
        return mensajes

    cash = wallbit_client.obtener_cash_inversion(wallbit_client.get_stocks_balance())
    if cash is None:
        return mensajes

    reservado = cash_reservado(planes, ejecuciones, hoy)
    acciones = repartir_cash(candidatos, cash - reservado)

    tickets = [a for a in acciones if a["tipo"] == "ticket"]
    total_pendientes = len(pendientes_vigentes(planes, ejecuciones, hoy)) + len(tickets)

    for a in acciones:
        plan = a["plan"]
        if a["tipo"] == "ticket":
            split = _split_del_plan(plan)
            asignaciones = calcular_montos(plan["monto_usd"], split)
            si, no = instruccion_respuesta(plan["numero"], total_pendientes)
            texto = armar_texto_ticket(plan["monto_usd"], asignaciones,
                                       titulo=_titulo_ticket(plan, a["periodo"], a["fecha_programada"], a["atrasado"]),
                                       respuesta_si=si, respuesta_no=no)
            if database.guardar_ejecucion_dca(plan["id"], plan["numero"], a["periodo"], "pendiente", plan["monto_usd"],
                                              split_json=json.dumps(split), texto_ticket=texto):
                mensajes.append(texto)
        elif not a["ya_avisado"]:
            database.guardar_ejecucion_dca(plan["id"], plan["numero"], a["periodo"], "sin_fondos", plan["monto_usd"])
            mensajes.append(texto_falta_fondos(plan["numero"], plan["monto_usd"], a["disponible"], a["faltante"]))

    return mensajes


def contexto_tickets_pendientes(hoy: date) -> str:
    """
    Línea de contexto que telegram_bot.mensaje_libre le suma al chat cuando
    hay tickets de planes esperando respuesta — el ticket lo mandó el job,
    no el LLM, así que sin esto el modelo no sabría a qué se refiere un "SÍ".
    Solo lee la DB (no llama a Wallbit). Vacío si no hay nada pendiente.
    """
    planes = database.obtener_planes_dca(solo_activos=True)
    if not planes:
        return ""
    vigentes = pendientes_vigentes(planes, database.obtener_ejecuciones_dca(), hoy)
    if not vigentes:
        return ""
    partes = [f"plan {v['plan']['numero']} (USD {v['ejecucion']['monto_usd']:.2f}, periodo {v['ejecucion']['periodo']})" for v in vigentes]
    if len(vigentes) > 1:
        regla = "Hay MÁS DE UNO: solo vale 'SÍ plan N' / 'NO plan N'; ante un SÍ solo, pedí que aclare el número y no llames a ejecutar_plan_dca."
    else:
        regla = "Hay uno solo: alcanza con 'SÍ' o 'NO'."
    return f"PLANES_DCA_PENDIENTES: tickets esperando respuesta: {', '.join(partes)}. {regla}"


# ─── Confirmación (SÍ) ─────────────────────────────────────────────────────
#
# El texto real que llegó por Telegram se pasa con un ContextVar: lo setea
# telegram_bot.mensaje_libre alrededor de agente.chat (ver
# mensaje_real_del_usuario) y lo lee ejecutar_plan_dca. No se lee "el último
# mensaje de usuario" de la DB porque otros jobs y comandos llaman a
# agente.chat con mensajes sintéticos que también se guardan como rol user.
# Fuera de un mensaje real (un job, /balance, etc.) el valor es None y la
# ejecución se rechaza.

_mensaje_usuario_real = contextvars.ContextVar("mensaje_usuario_real", default=None)


@contextlib.contextmanager
def mensaje_real_del_usuario(texto: str):
    token = _mensaje_usuario_real.set(texto)
    try:
        yield
    finally:
        _mensaje_usuario_real.reset(token)


def mensaje_usuario_actual() -> Optional[str]:
    return _mensaje_usuario_real.get()


_PATRON_CONFIRMACION = re.compile(r"^(si|confirmo)(?: plan (\d+))?$")


def normalizar_texto(texto: str) -> str:
    """Minúsculas, sin tildes, sin signos de puntuación al principio/final y con espacios simples."""
    sin_tildes = "".join(ch for ch in unicodedata.normalize("NFD", texto) if unicodedata.category(ch) != "Mn")
    limpio = re.sub(r"\s+", " ", sin_tildes.lower()).strip()
    return limpio.strip(".,;:!?¡¿ ")


def parsear_confirmacion(texto: Optional[str]) -> Optional[dict]:
    """
    Matching ESTRICTO: solo "si", "confirmo", "si plan N" o "confirmo plan N"
    (después de normalizar). Cualquier otra cosa — "si querés cambiá el plan
    2", "no sé si", "dale" — devuelve None. Devuelve {"numero": N o None}.
    """
    if not texto or not isinstance(texto, str):
        return None
    m = _PATRON_CONFIRMACION.match(normalizar_texto(texto))
    if not m:
        return None
    return {"numero": int(m.group(2)) if m.group(2) else None}


def validar_confirmacion(texto_usuario: Optional[str], numero: int, numeros_pendientes: list) -> Optional[str]:
    """Devuelve None si el texto confirma la ejecución del plan 'numero', o el motivo del rechazo."""
    if texto_usuario is None:
        return "Un plan solo se ejecuta como respuesta directa a un mensaje real del usuario por Telegram — no desde un job ni un comando."
    conf = parsear_confirmacion(texto_usuario)
    if conf is None:
        si = instruccion_respuesta(numero, len(numeros_pendientes))[0]
        return f"El mensaje del usuario no es una confirmación válida. Para comprar tiene que responder exactamente '{si}'."
    if conf["numero"] is None:
        if len(numeros_pendientes) > 1:
            lista = ", ".join(f"'SÍ plan {n}'" for n in numeros_pendientes)
            return f"Hay {len(numeros_pendientes)} tickets pendientes: un SÍ solo es ambiguo. Pedile que responda {lista}."
        return None
    if conf["numero"] != numero:
        return f"El usuario confirmó el plan {conf['numero']}, no el plan {numero}."
    return None


# ─── Tools ─────────────────────────────────────────────────────────────────

def _hoy() -> date:
    """Fecha local de la máquina (Argentina). Función aparte para poder fijarla en los tests."""
    return date.today()


def verificar_tickers(tickers: list) -> list:
    """Devuelve los tickers que Wallbit no reconoce (get_asset con error o sin símbolo). Verificación, no research."""
    invalidos = []
    for t in tickers:
        res = wallbit_client.get_asset(t)
        if not res.get("ok"):
            invalidos.append(t)
            continue
        try:
            data = json.loads(res["data"]) if isinstance(res["data"], str) else res["data"]
            info = data.get("data", data) if isinstance(data, dict) else {}
            if not isinstance(info, dict) or not info.get("symbol"):
                invalidos.append(t)
        except (json.JSONDecodeError, TypeError, AttributeError):
            invalidos.append(t)
    return invalidos


def _split_desde_inputs(inputs: dict) -> tuple:
    """(split, error). 'split' con % = reparto personalizado; 'tickers' sin % = equitativo."""
    split = inputs.get("split")
    tickers = inputs.get("tickers")
    if split:
        if not isinstance(split, list):
            return None, "El split tiene que ser una lista de {ticker, pct}"
        return [{"ticker": str(i.get("ticker", "")).strip().upper(), "pct": i.get("pct")} if isinstance(i, dict) else i for i in split], None
    if tickers:
        try:
            return split_equitativo([str(t).strip() for t in tickers]), None
        except ValueError as e:
            return None, str(e)
    return None, None


def _validar_completo(dia, monto_usd, split) -> Optional[str]:
    error = validar_datos_plan(dia, monto_usd, split)
    if error:
        return error
    invalidos = verificar_tickers([item["ticker"] for item in split])
    if invalidos:
        return f"Wallbit no reconoce estos tickers: {', '.join(invalidos)}. Revisalos — el plan no se guardó."
    return None


def _plan_para_mostrar(plan: dict, ejecuciones: list, hoy: date) -> dict:
    split = _split_del_plan(plan)
    propias = [e for e in ejecuciones if e["plan_id"] == plan["id"] and e["estado"] in ("ejecutado", "ejecutando")]
    ultima = propias[-1] if propias else None
    return {
        "numero": plan["numero"],
        "resumen": resumen_plan(plan["numero"], plan["nombre"], plan["dia"], plan["monto_usd"], split),
        "estado": "activo" if plan["activo"] else "pausado",
        "proxima_compra": proxima_fecha_compra(plan, ejecuciones, hoy).isoformat() if plan["activo"] else None,
        "ultima_ejecucion": {"periodo": ultima["periodo"], "fecha": ultima["fecha_ejecucion"], "estado": ultima["estado"]} if ultima else None,
    }


def _accion_crear(inputs: dict, guardar: bool):
    hoy = _hoy()
    planes = database.obtener_planes_dca()
    numero = primer_numero_libre({p["numero"] for p in planes})
    if numero is None:
        return {"ok": False, "error": f"Ya tenés {MAX_PLANES_DCA} planes, que es el máximo. Borrá o editá uno existente antes de crear otro."}

    split, error = _split_desde_inputs(inputs)
    if error:
        return {"ok": False, "error": error}
    if split is None:
        return {"ok": False, "error": "Faltan los tickers: pasá 'tickers' (reparto equitativo) o 'split' con el % de cada uno."}
    dia = inputs.get("dia")
    monto = inputs.get("monto_usd")
    nombre = (inputs.get("nombre") or "").strip() or None

    error = _validar_completo(dia, monto, split)
    if error:
        return {"ok": False, "error": error}

    desde = primer_periodo_desde(dia, hoy)
    resumen = resumen_plan(numero, nombre, dia, monto, split)
    datos = {
        "numero": numero,
        "resumen": resumen,
        "montos_por_ticker": calcular_montos(monto, split),
        "arranca_en": desde,
        "primera_compra": fecha_programada(dia, *map(int, desde.split("-"))).isoformat(),
    }
    if not guardar:
        datos["siguiente_paso"] = "Mostrale el resumen al usuario y pedile confirmación. Solo si confirma, llamá gestionar_plan_dca(accion='crear') con los mismos datos."
        return {"ok": True, "data": datos}

    database.crear_plan_dca(numero, nombre, dia, float(monto), json.dumps(split), desde)
    datos["guardado"] = True
    return {"ok": True, "data": datos}


def _accion_editar(inputs: dict):
    hoy = _hoy()
    plan = database.obtener_plan_dca(inputs.get("numero"))
    if not plan:
        return {"ok": False, "error": f"No existe el plan {inputs.get('numero')}."}

    split, error = _split_desde_inputs(inputs)
    if error:
        return {"ok": False, "error": error}
    split = split or _split_del_plan(plan)
    dia = inputs["dia"] if inputs.get("dia") is not None else plan["dia"]
    monto = inputs["monto_usd"] if inputs.get("monto_usd") is not None else plan["monto_usd"]
    if inputs.get("nombre") is not None:
        nombre = inputs["nombre"].strip() or None
    else:
        nombre = plan["nombre"]

    error = _validar_completo(dia, monto, split)
    if error:
        return {"ok": False, "error": error}

    # Si el día nuevo ya pasó este mes, el cambio no dispara un ticket atrasado:
    # mismo criterio que al crear. Si el plan ya se compró este mes, ese mes
    # queda cerrado y el cambio aplica desde el siguiente.
    desde = max(plan["desde_periodo"], primer_periodo_desde(dia, hoy)) if dia != plan["dia"] else plan["desde_periodo"]
    database.borrar_ejecuciones_abiertas_dca(plan["id"])  # un ticket pendiente con los datos viejos se descarta
    database.actualizar_plan_dca(plan["numero"], nombre=nombre, dia=dia, monto_usd=float(monto),
                                 split_json=json.dumps(split), desde_periodo=desde)
    plan_nuevo = database.obtener_plan_dca(plan["numero"])
    return {"ok": True, "data": {**_plan_para_mostrar(plan_nuevo, database.obtener_ejecuciones_dca(), hoy), "editado": True}}


@tool(
    "gestionar_plan_dca",
    "Planes de DCA programados (compra fija el día X de cada mes, sin research). Acciones: "
    "'previsualizar' (valida día, monto, tickers con get_asset y mínimo de USD 1 por orden, y devuelve el resumen SIN guardar — usar SIEMPRE antes de crear), "
    "'crear' (solo después de que el usuario confirmó el resumen), 'listar', 'editar' (numero + campos a cambiar), "
    "'pausar', 'reactivar', 'borrar' (numero), 'descartar_ticket' (numero — cuando el usuario responde NO al ticket del mes). "
    "Reparto: 'tickers' sin % = partes iguales; 'split' con % = personalizado. Máximo 5 planes y 10 tickers por plan.",
    {
        "type": "object",
        "properties": {
            "accion": {"type": "string", "enum": ["previsualizar", "crear", "listar", "editar", "pausar", "reactivar", "borrar", "descartar_ticket"]},
            "numero": {"type": "integer", "description": "Número del plan (editar, pausar, reactivar, borrar, descartar_ticket)"},
            "nombre": {"type": "string", "description": "Nombre opcional del plan"},
            "dia": {"type": "integer", "description": "Día del mes de la compra (1-31)"},
            "monto_usd": {"type": "number", "description": "Monto fijo en USD por mes"},
            "tickers": {"type": "array", "items": {"type": "string"}, "description": "Reparto equitativo: tickers sin porcentaje"},
            "split": {
                "type": "array",
                "description": "Reparto personalizado: [{ticker, pct}], deben sumar 100",
                "items": {"type": "object", "properties": {"ticker": {"type": "string"}, "pct": {"type": "number"}}, "required": ["ticker", "pct"]}
            }
        },
        "required": ["accion"]
    }
)
def _tool_gestionar_plan_dca(inputs: dict):
    accion = inputs.get("accion")
    hoy = _hoy()

    if accion == "previsualizar":
        return _accion_crear(inputs, guardar=False)
    if accion == "crear":
        return _accion_crear(inputs, guardar=True)
    if accion == "listar":
        planes = database.obtener_planes_dca()
        if not planes:
            return {"ok": True, "data": "No hay planes DCA configurados."}
        ejecuciones = database.obtener_ejecuciones_dca()
        return {"ok": True, "data": [_plan_para_mostrar(p, ejecuciones, hoy) for p in planes]}
    if accion == "editar":
        return _accion_editar(inputs)

    numero = inputs.get("numero")
    if numero is None:
        return {"ok": False, "error": f"Para '{accion}' hace falta el número de plan."}
    plan = database.obtener_plan_dca(numero)
    if not plan:
        return {"ok": False, "error": f"No existe el plan {numero}."}

    if accion == "pausar":
        database.borrar_ejecuciones_abiertas_dca(plan["id"])
        database.actualizar_plan_dca(numero, activo=0)
        return {"ok": True, "data": f"Plan {numero} pausado. No se arman tickets hasta que lo reactives."}
    if accion == "reactivar":
        desde = primer_periodo_desde(plan["dia"], hoy)
        database.actualizar_plan_dca(numero, activo=1, desde_periodo=max(desde, plan["desde_periodo"]))
        primera = fecha_programada(plan["dia"], *map(int, max(desde, plan["desde_periodo"]).split("-")))
        return {"ok": True, "data": f"Plan {numero} reactivado. Próxima compra: {primera.isoformat()} (no se recuperan meses anteriores)."}
    if accion == "borrar":
        database.borrar_ejecuciones_abiertas_dca(plan["id"])
        database.borrar_plan_dca(numero)
        return {"ok": True, "data": f"Plan {numero} borrado."}
    if accion == "descartar_ticket":
        if mensaje_usuario_actual() is None:
            return {"ok": False, "error": "Un ticket solo se descarta como respuesta a un mensaje real del usuario."}
        vigentes = pendientes_vigentes(database.obtener_planes_dca(solo_activos=True), database.obtener_ejecuciones_dca(), hoy)
        e = next((v["ejecucion"] for v in vigentes if v["plan"]["numero"] == numero), None)
        if not e or not database.cambiar_estado_ejecucion_dca(e["id"], "pendiente", "descartado"):
            return {"ok": False, "error": f"El plan {numero} no tiene un ticket pendiente este mes."}
        database.registrar_bitacora("dca", f"Plan {numero} ({e['periodo']}): ticket descartado por el usuario")
        return {"ok": True, "data": f"Ticket del plan {numero} descartado para {e['periodo']}. El plan sigue activo para el mes siguiente."}

    return {"ok": False, "error": f"Acción desconocida: '{accion}'"}


@tool(
    "ejecutar_plan_dca",
    "Ejecuta las compras del ticket pendiente de un plan DCA para el mes en curso (una orden MARKET por ticker). "
    "ÚNICA forma de comprar un plan — nunca usar create_trade directo para un plan. Llamar SOLO cuando el usuario "
    "respondió 'SÍ' (un solo ticket pendiente) o 'SÍ plan N' (varios). El código verifica la confirmación y que no "
    "se haya ejecutado ya este mes; si rechaza, no reintentar: transmitirle el motivo al usuario.",
    {
        "type": "object",
        "properties": {"numero": {"type": "integer", "description": "Número del plan a ejecutar"}},
        "required": ["numero"]
    }
)
def _tool_ejecutar_plan_dca(inputs: dict):
    numero = inputs.get("numero")
    hoy = _hoy()
    texto_usuario = mensaje_usuario_actual()
    if texto_usuario is None:
        return {"ok": False, "error": "Un plan solo se ejecuta como respuesta directa a un mensaje real del usuario por Telegram — no desde un job ni un comando."}

    vigentes = pendientes_vigentes(database.obtener_planes_dca(solo_activos=True), database.obtener_ejecuciones_dca(), hoy)
    numeros_pendientes = [v["plan"]["numero"] for v in vigentes]
    actual = next((v for v in vigentes if v["plan"]["numero"] == numero), None)
    if actual is None:
        return {"ok": False, "error": f"El plan {numero} no tiene un ticket pendiente para este mes (puede que ya se haya ejecutado, descartado o vencido). No se compró nada."}

    error = validar_confirmacion(texto_usuario, numero, numeros_pendientes)
    if error:
        return {"ok": False, "error": error + " No se compró nada."}

    e = actual["ejecucion"]
    if not database.cambiar_estado_ejecucion_dca(e["id"], "pendiente", "ejecutando"):
        return {"ok": False, "error": f"El plan {numero} ya se está ejecutando o ya se ejecutó este mes. No se compró nada."}

    # Se compra exactamente lo que mostraba el ticket (la foto guardada), no el plan tal como esté hoy.
    asignaciones = calcular_montos(e["monto_usd"], parsear_split_json(e["split_json"]))
    resultados = []
    for a in asignaciones:
        res = wallbit_client.create_trade(ticker=a["ticker"], side="buy", amount=a["monto"], order_type="market")
        resultados.append({"ticker": a["ticker"], "monto": a["monto"], "ok": bool(res.get("ok")),
                           "detalle": res.get("data") if res.get("ok") else res.get("error")})

    database.cambiar_estado_ejecucion_dca(e["id"], "ejecutando", "ejecutado", resultado_json=json.dumps(resultados, ensure_ascii=False, default=str))
    fallidas = [r for r in resultados if not r["ok"]]
    detalle = "; ".join(f"{r['ticker']} USD {r['monto']:.2f} {'OK' if r['ok'] else 'FALLÓ: ' + str(r['detalle'])}" for r in resultados)
    database.registrar_bitacora("dca", f"{hoy.isoformat()} plan {numero} ({e['periodo']}) USD {e['monto_usd']:.2f}: {detalle}")

    return {
        "ok": True,
        "data": {
            "plan": numero,
            "periodo": e["periodo"],
            "monto_total": e["monto_usd"],
            "ordenes": resultados,
            "fallidas": [r["ticker"] for r in fallidas],
            "nota": ("Algunas órdenes fallaron y NO se reintentan solas: informale al usuario cuáles y que puede comprarlas a mano."
                     if fallidas else "Todas las órdenes se enviaron."),
        }
    }
