import os
import logging
from datetime import time as dtime, date
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from database import init_db, guardar_mensaje
import agente
import research_campaigns
import planes_dca
import wallbit_client

load_dotenv("config.env")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AUTHORIZED_USER_ID = int(os.getenv("TELEGRAM_USER_ID", "0"))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# httpx (lo usan python-telegram-bot y el SDK de Anthropic) loguea en INFO
# cada request con la URL completa — y la URL de Telegram lleva el token del
# bot adentro (https://api.telegram.org/bot<TOKEN>/...). En WARNING deja de
# escribir esas líneas. El resto de los loggers se revisó y no escribe
# claves en INFO: Wallbit y Brave mandan la key en headers, y requests/urllib3
# (FMP manda la apikey en la URL) solo loguean URLs en DEBUG.
logging.getLogger("httpx").setLevel(logging.WARNING)


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
    # Si hay tickets de planes DCA esperando respuesta, el LLM tiene que
    # saberlo para entender a qué responde un "SÍ" (el ticket lo mandó el job).
    ctx_dca = planes_dca.contexto_tickets_pendientes(date.today())
    contexto = "\n".join(p for p in (ctx, ctx_dca) if p)
    # El texto real que llegó por Telegram viaja hasta ejecutar_plan_dca, que
    # solo compra si ese texto es una confirmación válida (ver planes_dca.py).
    with planes_dca.mensaje_real_del_usuario(user_text):
        respuesta = agente.chat(user_text, contexto_extra=contexto)
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


async def chequear_planes_dca_diario(context: ContextTypes.DEFAULT_TYPE):
    """
    Corre una vez por día (9am Argentina) y manda, por cada plan DCA que
    toca hoy, el ticket de compra o el aviso de falta de plata. La lógica
    entera vive en planes_dca.correr_chequeo_diario (sin LLM; si no hay
    planes activos ni ninguno toca hoy, tampoco llama a Wallbit).

    Cada mensaje se guarda además en el historial como mensaje del bot, para
    que cuando Mateo responda "SÍ" el modelo vea el ticket al que responde.
    """
    if not AUTHORIZED_USER_ID:
        return
    for texto in planes_dca.correr_chequeo_diario(date.today()):
        await _enviar_texto_largo_bot(context.bot, AUTHORIZED_USER_ID, texto)
        guardar_mensaje("assistant", texto)


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

    # Planes DCA programados a las 9:00am Argentina (12:00 UTC)
    app.job_queue.run_daily(chequear_planes_dca_diario, time=dtime(hour=12, minute=0))

    logger.info("🤖 Agente Wallbit iniciado vía Telegram.")
    app.run_polling()


if __name__ == "__main__":
    main()
