import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from database import init_db
import agente

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
    disparadas = agente.verificar_alertas()
    if disparadas:
        await update.message.reply_text("🔔 *Alertas disparadas:*\n" + "\n".join(disparadas), parse_mode="Markdown")
    else:
        await update.message.reply_text("✅ Sin alertas disparadas en este momento.")


async def watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_autorizado(update):
        return
    respuesta = agente.chat("Mostrame mi watchlist con los precios actuales de cada ticker.")
    await enviar_respuesta_larga(update, respuesta)


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_autorizado(update):
        return
    texto = (
        "📋 *Comandos disponibles:*\n\n"
        "/briefing – Morning Briefing completo\n"
        "/balance – Saldo e inversiones\n"
        "/alertas – Verificar alertas de precio\n"
        "/watchlist – Ver precios de tu watchlist\n"
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


async def verificar_alertas_periodico(context: ContextTypes.DEFAULT_TYPE):
    """Chequea alertas cada 30 minutos y notifica si hay disparadas."""
    disparadas = agente.verificar_alertas()
    if disparadas and AUTHORIZED_USER_ID:
        texto = "🔔 *Alertas de precio:*\n" + "\n".join(disparadas)
        await context.bot.send_message(chat_id=AUTHORIZED_USER_ID, text=texto, parse_mode="Markdown")


def main():
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("briefing", briefing))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("alertas", alertas))
    app.add_handler(CommandHandler("watchlist", watchlist))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mensaje_libre))

    # Verificar alertas cada 30 minutos
    app.job_queue.run_repeating(verificar_alertas_periodico, interval=1800, first=60)

    logger.info("🤖 Agente Wallbit iniciado vía Telegram.")
    app.run_polling()


if __name__ == "__main__":
    main()
