"""
salary_dca.py — Inversión automática de sueldo con split fijo (DCA).

Todo lo que es plata (porcentajes, redondeo, montos por ticker) vive acá como
funciones puras, sin red y sin tocar la DB — así se puede testear con pytest
sin depender de Wallbit ni de ninguna llamada a Claude. La única tool
expuesta al LLM es calcular_split_sueldo: la idea es que el modelo NUNCA
calcule los montos a mano (evita errores de redondeo), siempre llame a esta
tool y solo arme el texto del ticket con el resultado.

La detección de "esto parece un sueldo" y todo el resto del protocolo
(avisar, pedir el traspaso manual, pedir confirmación, ejecutar create_trade)
queda en el system prompt (ver PROMPT_MODULES["inversion_sueldo_dca"] en
agente.py) — es un juicio de texto libre sobre list_transactions, no algo
parseable de forma confiable con código (Wallbit no expone una API de
transferencias ni devuelve las transacciones en un formato fijo).
"""
import json

from tool_registry import tool

# Tope de tickers por split: más allá de esto el ticket de confirmación deja
# de ser algo que se pueda leer y decidir en 5 segundos (se vuelve un "SÍ"
# ciego, justo lo que la regla de confirmación quiere evitar), y el monto por
# ticker empieza a quedar muy chico si el sueldo no es enorme. Es un límite
# duro acá, no una sugerencia del LLM, para que no dependa de que el modelo
# se acuerde de respetarlo.
MAX_TICKERS_SPLIT = 10


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
    Parsea el JSON guardado en config (clave DCA_SUELDO_SPLIT) a una lista de
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
    o de menos que lo que el usuario transfirió.
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


def calcular_monto_a_invertir(monto_sueldo: float, modo: str, valor: float) -> float:
    """
    Función pura: dado el monto del sueldo detectado y la preferencia del
    usuario (invertir un % de cada sueldo, o un monto fijo en dólares),
    devuelve cuánto de ese sueldo hay que destinar al DCA — NO todo el
    depósito, salvo que el usuario haya elegido justamente 100%.

    modo="porcentaje": valor es un % (0-100] del sueldo detectado.
    modo="fijo": valor es un monto en USD, que no puede superar el sueldo
    detectado (no tiene sentido pedirle que transfiera más de lo que cobró).
    """
    if monto_sueldo <= 0:
        raise ValueError("El monto del sueldo tiene que ser mayor a 0")

    if modo == "porcentaje":
        if not isinstance(valor, (int, float)) or not (0 < valor <= 100):
            raise ValueError("El porcentaje a invertir tiene que ser un número entre 0 y 100")
        return round(monto_sueldo * valor / 100, 2)

    if modo == "fijo":
        if not isinstance(valor, (int, float)) or valor <= 0:
            raise ValueError("El monto fijo a invertir tiene que ser mayor a 0")
        if valor > monto_sueldo:
            raise ValueError(f"El monto fijo (${valor}) es mayor al sueldo detectado (${monto_sueldo}) — no se puede invertir más de lo que ingresó")
        return round(valor, 2)

    raise ValueError(f"Modo desconocido: '{modo}' (tiene que ser 'porcentaje' o 'fijo')")


def armar_texto_ticket(monto_total: float, asignaciones: list) -> str:
    """Texto determinístico del ticket, para no depender de que el LLM sume bien."""
    lineas = [f"Ticket de inversión de sueldo — ${monto_total:.2f} total:"]
    for a in asignaciones:
        lineas.append(f"- {a['ticker']}: ${a['monto']:.2f} ({a['pct']}%) — MARKET")
    lineas.append("¿Confirmás las {} compras? (SÍ/NO)".format(len(asignaciones)))
    return "\n".join(lineas)


@tool(
    "calcular_monto_a_invertir_sueldo",
    "Calcula cuánto de un sueldo detectado hay que destinar al DCA — NO se invierte el depósito completo, solo la porción configurada. "
    "SIEMPRE usar esta tool antes de pedir el traspaso manual y antes de calcular_split_sueldo — nunca calcular esto a mano. "
    "Si no se pasan 'modo' y 'valor', usa lo guardado en config (DCA_SUELDO_MODO_MONTO / DCA_SUELDO_MONTO_VALOR).",
    {
        "type": "object",
        "properties": {
            "monto_sueldo": {"type": "number", "description": "Monto del sueldo detectado en la transacción"},
            "modo": {"type": "string", "enum": ["porcentaje", "fijo"], "description": "'porcentaje' para invertir un % del sueldo, 'fijo' para un monto en USD constante"},
            "valor": {"type": "number", "description": "El % (si modo=porcentaje) o el monto en USD (si modo=fijo)"}
        },
        "required": ["monto_sueldo"]
    }
)
def _tool_calcular_monto_a_invertir_sueldo(inputs: dict):
    from database import obtener_config  # import diferido: evita ciclo con database.py

    monto_sueldo = inputs["monto_sueldo"]
    modo = inputs.get("modo")
    valor = inputs.get("valor")

    if not modo or valor is None:
        modo = modo or obtener_config("DCA_SUELDO_MODO_MONTO")
        valor_guardado = obtener_config("DCA_SUELDO_MONTO_VALOR")
        if valor is None and valor_guardado is not None:
            try:
                valor = float(valor_guardado)
            except ValueError:
                valor = None
        if not modo or valor is None:
            return {"ok": False, "error": "No hay preferencia guardada (DCA_SUELDO_MODO_MONTO / DCA_SUELDO_MONTO_VALOR) y no se pasó 'modo'/'valor'. Preguntale al usuario qué % o monto fijo de su sueldo quiere invertir."}

    try:
        monto_a_invertir = calcular_monto_a_invertir(monto_sueldo, modo, valor)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    return {
        "ok": True,
        "data": {
            "monto_sueldo": monto_sueldo,
            "modo": modo,
            "valor": valor,
            "monto_a_invertir": monto_a_invertir,
        }
    }


@tool(
    "calcular_split_sueldo",
    "Calcula el monto exacto en USD para cada ticker de un split fijo de inversión de sueldo, dado un monto total. "
    "SIEMPRE usar esta tool para los montos (nunca calcularlos a mano) — evita errores de redondeo. "
    "Reparto PERSONALIZADO: pasar 'split' con el % de cada ticker. Reparto EQUITATIVO: pasar 'tickers' (sin %) y se reparte en partes iguales. "
    "Si no se pasa ninguno de los dos, usa el guardado en config con save_config(leer, clave='DCA_SUELDO_SPLIT').",
    {
        "type": "object",
        "properties": {
            "monto_total": {"type": "number", "description": "Monto total en USD ya transferido a la cuenta de inversión"},
            "split": {
                "type": "array",
                "description": "Reparto personalizado: lista de asignaciones [{ticker, pct}], deben sumar 100.",
                "items": {
                    "type": "object",
                    "properties": {"ticker": {"type": "string"}, "pct": {"type": "number"}},
                    "required": ["ticker", "pct"]
                }
            },
            "tickers": {
                "type": "array",
                "description": "Reparto equitativo: lista de tickers sin porcentaje, se reparte 100% en partes iguales entre todos.",
                "items": {"type": "string"}
            }
        },
        "required": ["monto_total"]
    }
)
def _tool_calcular_split_sueldo(inputs: dict):
    from database import obtener_config  # import diferido: evita ciclo con database.py

    monto_total = inputs["monto_total"]
    split = inputs.get("split")
    tickers = inputs.get("tickers")

    if not split and tickers:
        try:
            split = split_equitativo(tickers)
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    if not split:
        valor_guardado = obtener_config("DCA_SUELDO_SPLIT")
        if not valor_guardado:
            return {"ok": False, "error": "No hay split guardado (DCA_SUELDO_SPLIT) y no se pasó 'split' ni 'tickers'. Preguntale al usuario qué tickers quiere y si el reparto es equitativo o personalizado."}
        try:
            split = parsear_split_json(valor_guardado)
        except ValueError as e:
            return {"ok": False, "error": f"Split guardado inválido: {e}"}

    try:
        asignaciones = calcular_montos(monto_total, split)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    return {
        "ok": True,
        "data": {
            "monto_total": monto_total,
            "asignaciones": asignaciones,
            "ticket_sugerido": armar_texto_ticket(monto_total, asignaciones),
        }
    }
