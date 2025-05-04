"""Manejadores para los eventos del bot de Telegram."""

import logging
import os
from telegram import Update, Bot
from telegram.ext import ContextTypes
from telegram_moderator_bot.config import LLAMAGUARD_PROVIDER, OLLAMA_HOST
from telegram_moderator_bot.moderation import setup_moderator_agent, moderate_content

# Configuración de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Inicializar el agente moderador
def get_moderator_agent():
    """Obtener una instancia del agente moderador según la configuración"""
    provider_args = {}
    
    if LLAMAGUARD_PROVIDER == "ollama":
        provider_args["host"] = OLLAMA_HOST
    elif LLAMAGUARD_PROVIDER == "replicate":
        provider_args["api_key"] = os.getenv("REPLICATE_API_KEY")
    elif LLAMAGUARD_PROVIDER == "moderation_api":
        provider_args["api_key"] = os.getenv("MODERATION_API_KEY")
        
    return setup_moderator_agent(LLAMAGUARD_PROVIDER, **provider_args)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enviar un mensaje cuando se emite el comando /start"""
    user = update.effective_user
    await update.message.reply_text(
        f'¡Hola {user.first_name}! Soy el bot moderador del grupo. '
        f'Estoy aquí para asegurar que todos los mensajes cumplan con los lineamientos del grupo.'
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enviar un mensaje cuando se emite el comando /help"""
    await update.message.reply_text(
        'Soy un bot moderador que analiza mensajes usando LlamaGuard. '
        'Elimino mensajes inapropiados y ofrezco sugerencias de redacción cuando es necesario.'
    )


async def get_group_description(bot: Bot, chat_id: int) -> str:
    """Obtener la descripción del grupo para usar como lineamientos"""
    try:
        chat = await bot.get_chat(chat_id)
        description = chat.description or ""
        
        # Si no hay descripción, usar lineamientos predeterminados
        if not description:
            return (
                "Este es un grupo de discusión respetuoso. No se permite lenguaje ofensivo, "
                "discriminatorio o contenido para adultos. Mantén las conversaciones cordiales "
                "y constructivas. No se permite spam ni promociones no autorizadas, no esta permitido nada relacionado a la muerte ni suicidio"
            )
        return description
    except Exception as e:
        logger.error(f"Error al obtener la descripción del grupo: {e}")
        return (
            "Este es un grupo de discusión respetuoso. No se permite lenguaje ofensivo, "
            "discriminatorio o contenido para adultos. Mantén las conversaciones cordiales "
            "y constructivas. No se permite spam ni promociones no autorizadas."
        )


async def moderate_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Moderar mensajes del grupo usando LlamaGuard"""
    # Ignorar mensajes de comandos y del propio bot
    if not update.message or not update.message.text:
        return
        
    if update.message.text.startswith('/') or update.effective_user.id == context.bot.id:
        return
    
    # Obtener información necesaria
    chat_id = update.effective_chat.id
    message_id = update.message.message_id  # ID del mensaje original del usuario
    user = update.effective_user
    username = user.username or user.first_name
    text = update.message.text
    
    # Verificar permisos del bot
    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        if not bot_member.can_delete_messages:
            print("⚠️ ADVERTENCIA: El bot no tiene permisos para eliminar mensajes")
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ No tengo permisos para eliminar mensajes. Por favor, haz que un administrador me dé permisos de 'Eliminar mensajes'."
            )
            return  # Salir si no hay permisos
    except Exception as e:
        logger.error(f"Error al verificar permisos: {e}")
    
    # Obtener lineamientos del grupo
    group_guidelines = await get_group_description(context.bot, chat_id)
    
    # Informar al usuario que su mensaje está siendo revisado
    status_message = await context.bot.send_message(
        chat_id=chat_id,
        reply_to_message_id=message_id,
        text="⏳ Revisando este mensaje..."
    )
    status_message_id = status_message.message_id  # Guardar el ID del mensaje de estado
    
    try:
        # Obtener el agente moderador
        moderator_agent = get_moderator_agent()
        
        # Evaluar el mensaje
        result = await moderate_content(
            moderator_agent, 
            group_guidelines,
            text,
            username
        )
        
        print(f"Resultado de moderación: {result}")
        print(f"¿Es apropiado?: {result.is_appropriate}")
        
        # Procesar el resultado
        if not result.is_appropriate:  # Si NO es apropiado
            print(f"Mensaje inapropiado detectado, ID: {message_id}")
            # Eliminar el mensaje inapropiado del usuario
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            
            # También eliminar el mensaje de estado
            await context.bot.delete_message(chat_id=chat_id, message_id=status_message_id)
            
            # Notificar al usuario
            violation_message = (
                f"@{username}, tu mensaje ha sido eliminado porque viola los lineamientos del grupo:\n\n"
                f"{result.violation_reason or 'Contenido inapropiado'}\n\n"
            )
            
            # Agregar sugerencia de mejora si está disponible
            if result.improved_message:
                violation_message += f"Sugerencia de redacción alternativa:\n{result.improved_message}"
            
            await context.bot.send_message(
                chat_id=chat_id,
                text=violation_message
            )
        else:
            # El mensaje es apropiado - Solo eliminar el mensaje de estado, NO el mensaje original
            print(f"Mensaje apropiado, eliminando solo mensaje de estado ID: {status_message_id}")
            await context.bot.delete_message(chat_id=chat_id, message_id=status_message_id)
    
    except Exception as e:
        logger.error(f"Error al moderar el mensaje: {e}")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_message_id,
            text="❌ No se pudo revisar este mensaje debido a un error técnico."
        )