import os
import logging
from datetime import time as dtime, date
from typing import Optional
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from database import init_db, obtener_config, guardar_config
import agente
import research_campaigns
import salary_dca
import wallbit_client

load_dotenv("config.env")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AUTHORIZED_USER_ID = int(os.getenv("TELEGRAM_USER_ID", "0"))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def es_autorizado(update: Update) -> bool:
    return update.effective_user.id == AUTHORIZED_USER_ID


async def enviar_respuesta_larga(update: Update, texto: str):
    """Envía mensajes largos dividiéndolos en chunks de 4000 caracteres."""
    MAX_LEN = 4000
    if len(texto) <= MAX_LEN:
        await update.message.reply_text(texto)
    else:
        partes = [texto[i:i+MAX_LEN] for i in range(0, len(texto), MAX_LEN)]
        for parte in partes:
            await update.message.reply_text(parte)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_autorizado(update):
        return
    ctx = agente.construir_contexto_inicial()
    bienvenida = "🤖 *Agente Wallbit activo.*\n\nEscribime lo que necesitás o usá los comandos:\n/briefing – Morning Briefing\n/balance – Ver saldo\n/alertas – Ver alertas activas\n/watchlist – Ver watchlist\n/ayuda – Lista de comandos"
    if ctx:
        bienvenida += f"\n\n{ctx}"
    await update.message.reply_text(bienvenida, parse_mode="Markdown")


async def briefing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_autorizado(update):
        return
    await update.message.reply_text("⏳ Armando tu Morning Briefing con datos reales...")
    respuesta = agente.morning_briefing_automatico()
    await enviar_respuesta_larga(update, respuesta)


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_autorizado(update):
        return
    await update.message.reply_text("⏳ Consultando tu balance...")
    respuesta = agente.chat("Mostrame mi balance completo: cuenta corriente y todas mis posiciones de inversión.")
    await enviar_respuesta_larga(update, respuesta)


async def alertas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_autorizado(update):
        return
    disparadas = agente.verificar_alertas() + agente.verificar_alertas_pct()
    if disparadas:
        await update.message.reply_text("🔔 *Alertas disparadas:*\n" + "\n".join(disparadas), parse_mode="Markdown")
    else:
        await update.message.reply_text("✅ Sin alertas disparadas en este momento.")


async def watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_autorizado(update):
        return
    respuesta = agente.chat("Mostrame mi watchlist con los precios actuales de cada ticker.")
    await enviar_respuesta_larga(update, respuesta)


async def earnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_autorizado(update):
        return
    await update.message.reply_text("Chequeando earnings de tu portafolio...")
    proximos = agente.verificar_earnings_portfolio(days=14)
    if proximos:
        texto = "EARNINGS PROXIMOS (14 dias)\n\n" + "\n".join(proximos)
    else:
        texto = "Ninguna empresa de tu portafolio reporta earnings en los proximos 14 dias."
    await enviar_respuesta_larga(update, texto)


async def debate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debate Bull vs Bear de un ticker. Uso: /debate AAPL"""
    if not es_autorizado(update):
        return
    args = context.args
    if not args:
        await update.message.reply_text("Uso: /debate TICKER\nEjemplo: /debate NVDA")
        return
    ticker = args[0].upper()
    contexto_extra = " ".join(args[1:]) if len(args) > 1 else ""
    await update.message.reply_text(f"Armando debate Bull vs Bear de {ticker}...")
    resultado = agente._ejecutar_bull_bear(ticker, contexto_extra)
    await enviar_respuesta_larga(update, resultado)


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_autorizado(update):
        return
    texto = (
        "📋 *Comandos disponibles:*\n\n"
        "/briefing – Morning Briefing completo\n"
        "/balance – Saldo e inversiones\n"
        "/alertas – Verificar alertas de precio\n"
        "/watchlist – Ver precios de tu watchlist\n"
        "/earnings – Earnings próximos de tu portafolio\n"
        "/debate TICKER – Bull vs Bear de una acción\n"
        "/ayuda – Esta ayuda\n\n"
        "También podés escribirme directamente cualquier consulta financiera 💬"
    )
    await update.message.reply_text(texto, parse_mode="Markdown")


async def mensaje_libre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_autorizado(update):
        return
    user_text = update.message.text
    await update.message.reply_text("⏳ Procesando...")
    ctx = agente.construir_contexto_inicial()
    respuesta = agente.chat(user_text, contexto_extra=ctx)
    await enviar_respuesta_larga(update, respuesta)


async def _enviar_texto_largo_bot(bot, chat_id: int, texto: str, parse_mode: str = None):
    """Igual que enviar_respuesta_larga pero para jobs automáticos (no tienen Update)."""
    MAX_LEN = 4000
    if len(texto) <= MAX_LEN:
        await bot.send_message(chat_id=chat_id, text=texto, parse_mode=parse_mode)
    else:
        for i in range(0, len(texto), MAX_LEN):
            await bot.send_message(chat_id=chat_id, text=texto[i:i+MAX_LEN], parse_mode=parse_mode)


async def verificar_alertas_periodico(context: ContextTypes.DEFAULT_TYPE):
    """Chequea alertas cada 30 minutos y notifica si hay disparadas."""
    disparadas = agente.verificar_alertas() + agente.verificar_alertas_pct()
    if disparadas and AUTHORIZED_USER_ID:
        texto = "🔔 *Alertas de precio:*\n" + "\n".join(disparadas)
        await _enviar_texto_largo_bot(context.bot, AUTHORIZED_USER_ID, texto, parse_mode="Markdown")


async def earnings_diarios(context: ContextTypes.DEFAULT_TYPE):
    """Chequea earnings del portafolio cada mañana a las 8am Argentina (UTC-3 = 11:00 UTC)."""
    proximos = agente.verificar_earnings_portfolio(days=7)
    if proximos and AUTHORIZED_USER_ID:
        texto = "EARNINGS ESTA SEMANA\n\n" + "\n".join(proximos)
        await _enviar_texto_largo_bot(context.bot, AUTHORIZED_USER_ID, texto)


async def research_diario(context: ContextTypes.DEFAULT_TYPE):
    """
    Corre las campañas de research activas una vez por día, a las 7am
    Argentina (UTC-3 = 10:00 UTC) — antes del chequeo de earnings y de la
    apertura de mercado, para tener las novedades listas a primera hora.
    Solo manda un mensaje corto con el conteo de novedades; el detalle
    (los links) queda en el HTML local, que se actualiza solo.
    """
    resumen = research_campaigns.ejecutar_campanas_diarias()
    if not resumen or not AUTHORIZED_USER_ID:
        return
    lineas = []
    for r in resumen:
        estado = "✅ campaña finalizada" if r["finalizada"] else f"día {r['dias_transcurridos']}/{r['dias_totales']}"
        lineas.append(f"🔎 Campaña #{r['campana_id']} [{r['tickers']}] ({estado}): {r['nuevos']} novedades nuevas\n{r['archivo_html']}")
    texto = "*Research diario:*\n\n" + "\n\n".join(lineas)
    await _enviar_texto_largo_bot(context.bot, AUTHORIZED_USER_ID, texto, parse_mode="Markdown")


def _limpiar_espera_traspaso():
    """Borra el estado de 'esperando que llegue la plata a Inversión' (ya sea porque se detectó o porque venció el plazo)."""
    guardar_config("DCA_SUELDO_MONTO_ESPERADO", "")
    guardar_config("DCA_SUELDO_CASH_BASELINE", "")
    guardar_config("DCA_SUELDO_ESPERA_DESDE", "")


def _chequear_traspaso_pendiente() -> Optional[str]:
    """
    Si se está esperando un traspaso manual a la cuenta de Inversión (porque
    ya se detectó el sueldo y se le avisó a Mateo cuánto transferir), chequea
    si ya llegó esa plata comparando el efectivo actual contra la foto
    guardada al empezar a esperar (ver salary_dca.iniciar_espera_traspaso_sueldo).

    Devuelve None si no hay nada pendiente o todavía no llegó nada — en ese
    caso este chequeo no le pide nada al LLM, solo lee un config y llama a
    Wallbit una vez, así que es barato correrlo todos los días sin condición.
    """
    monto_esperado_raw = obtener_config("DCA_SUELDO_MONTO_ESPERADO")
    if not monto_esperado_raw:
        return None

    desde = obtener_config("DCA_SUELDO_ESPERA_DESDE")
    if desde and salary_dca.espera_vencida(desde):
        _limpiar_espera_traspaso()
        return (
            "⌛ Hace más de 10 días que te avisé que había que transferir a la cuenta de "
            "Inversión y no vi que haya llegado esa plata. Dejo de chequearlo automáticamente — "
            "si ya transferiste o lo hacés más tarde, avisame vos y seguimos con la compra."
        )

    baseline_raw = obtener_config("DCA_SUELDO_CASH_BASELINE")
    if not baseline_raw:
        return None

    stocks_res = wallbit_client.get_stocks_balance()
    cash_actual = wallbit_client.obtener_cash_inversion(stocks_res)
    if cash_actual is None:
        return None  # no se pudo leer el efectivo ahora — se reintenta mañana, no es un error fatal

    monto_esperado = float(monto_esperado_raw)
    delta = cash_actual - float(baseline_raw)
    if not salary_dca.traspaso_detectado(delta, monto_esperado):
        return None

    _limpiar_espera_traspaso()
    contexto_extra = (
        f"CHEQUEO_TRASPASO_SUELDO: ya se detectó que entraron ${delta:.2f} a la cuenta de Inversión "
        f"(se había avisado transferir ${monto_esperado:.2f}). Llamá calcular_split_sueldo con "
        f"monto_total={delta:.2f} (el monto real que llegó, no el que se avisó) y mandale el ticket "
        f"de confirmación al usuario, esperando SÍ/NO como siempre."
    )
    return agente.chat("Chequeo automático de traspaso de sueldo.", contexto_extra=contexto_extra)


async def chequear_sueldo_diario(context: ContextTypes.DEFAULT_TYPE):
    """
    Corre una vez por día y hace dos chequeos independientes, cada uno solo
    si corresponde — para no golpear la API de Wallbit sin necesidad:

    1. Traspaso pendiente (_chequear_traspaso_pendiente): barato, se corre
       siempre. Si no hay nada pendiente, no llama a Wallbit para nada.
    2. Sueldo nuevo: solo si HOY cae dentro del rango de días configurado
       (DCA_SUELDO_DIA_DESDE/HASTA) — o siempre, si la persona no cargó un
       rango — le pide al agente (vía chat, contexto CHEQUEO_AUTOMATICO_SUELDO)
       que revise list_transactions buscando un depósito nuevo que parezca
       sueldo desde la última corrida. La ventana de fechas
       (DCA_SUELDO_ULTIMA_FECHA) la mueve este código, no el LLM — así el
       "desde cuándo" es determinístico aunque la detección en sí (si ESE
       depósito puntual parece o no un sueldo) sea juicio del modelo.

    Si no hay novedades en el chequeo de sueldo, el módulo de prompt le pide
    al LLM que responda exactamente "SIN_NOVEDADES" — para no mandar un
    mensaje de Telegram vacío todos los días.
    """
    if not AUTHORIZED_USER_ID:
        return

    respuesta_traspaso = _chequear_traspaso_pendiente()
    if respuesta_traspaso:
        await _enviar_texto_largo_bot(context.bot, AUTHORIZED_USER_ID, respuesta_traspaso)

    dia_desde_raw = obtener_config("DCA_SUELDO_DIA_DESDE")
    dia_hasta_raw = obtener_config("DCA_SUELDO_DIA_HASTA")
    dia_desde = int(dia_desde_raw) if dia_desde_raw else None
    dia_hasta = int(dia_hasta_raw) if dia_hasta_raw else None
    if not salary_dca.hoy_esta_en_ventana_sueldo(dia_desde, dia_hasta):
        return  # fuera de la ventana de días: no se llama a Wallbit para nada

    ultima_fecha = obtener_config("DCA_SUELDO_ULTIMA_FECHA") or "sin fecha previa (primera corrida, revisá todo el historial reciente)"
    contexto_extra = (
        f"CHEQUEO_AUTOMATICO_SUELDO: revisá list_transactions y fijate si hay un depósito que parezca "
        f"sueldo (comparando el monto contra DCA_SUELDO_MONTO_APROX guardado) con fecha posterior a {ultima_fecha}."
    )
    respuesta = agente.chat("Chequeo automático de sueldo.", contexto_extra=contexto_extra)
    guardar_config("DCA_SUELDO_ULTIMA_FECHA", date.today().isoformat())
    if respuesta.strip() != "SIN_NOVEDADES":
        await _enviar_texto_largo_bot(context.bot, AUTHORIZED_USER_ID, respuesta)


async def manejador_errores(update: object, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler global de errores. Sin esto, si algo revienta dentro de un
    comando/mensaje o de un job automático, python-telegram-bot lo loguea
    internamente pero el usuario se queda sin ninguna respuesta — vio
    "⏳ Procesando..." y ahí termina, sin enterarse de que algo falló.
    Acá lo logueamos igual (con traceback completo en bot.log) y, si el
    error vino de un mensaje de chat (no de un job en background, que no
    tiene update), le avisamos al usuario en vez de dejarlo esperando.
    """
    logger.error("Excepción no manejada", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ Ocurrió un error inesperado procesando tu mensaje. Si se repite, revisá bot.log."
            )
        except Exception:
            pass  # si ni el aviso de error se puede mandar, no hay más para hacer acá


def main():
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("briefing", briefing))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("alertas", alertas))
    app.add_handler(CommandHandler("watchlist", watchlist))
    app.add_handler(CommandHandler("earnings", earnings))
    app.add_handler(CommandHandler("debate", debate))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mensaje_libre))
    app.add_error_handler(manejador_errores)

    # Verificar alertas cada 30 minutos
    app.job_queue.run_repeating(verificar_alertas_periodico, interval=1800, first=60)

    # Earnings diarios a las 8:00am Argentina (11:00 UTC)
    app.job_queue.run_daily(earnings_diarios, time=dtime(hour=11, minute=0))

    # Research de campañas activas a las 7:00am Argentina (10:00 UTC)
    app.job_queue.run_daily(research_diario, time=dtime(hour=10, minute=0))

    # Chequeo de sueldo a las 9:00am Argentina (12:00 UTC) — después de la apertura de mercado
    app.job_queue.run_daily(chequear_sueldo_diario, time=dtime(hour=12, minute=0))

    logger.info("🤖 Agente Wallbit iniciado vía Telegram.")
    app.run_polling()


if __name__ == "__main__":
    main()
