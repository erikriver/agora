"""Punto de entrada principal para el bot moderador de Telegram."""

import logging
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram import Update

from telegram_moderator_bot.config import TELEGRAM_BOT_TOKEN
from telegram_moderator_bot.telegram_handlers import start, help_command, moderate_message

# Configuración de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def main() -> None:
    """Iniciar el bot."""
    # Crear la aplicación
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Agregar manejadores
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    
    # Manejar mensajes normales
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, moderate_message))

    # Iniciar el bot
    logger.info("Iniciando el bot moderador de Telegram...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()