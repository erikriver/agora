"""
Bot de moderación para grupos de Telegram utilizando PydanticAI y LlamaGuard

Este bot analiza los mensajes en un grupo de Telegram, utilizando LlamaGuard para determinar
si son apropiados según los lineamientos del grupo. Si un mensaje no es apropiado, el bot
lo eliminará y notificará al remitente la razón. Si el mensaje contiene lenguaje inapropiado
pero su intención es válida, el bot sugerirá una mejor redacción.
"""

import os
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import logging
import asyncio

# Bibliotecas para Telegram
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# PydanticAI
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

# Configuración de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuraciones y constantes
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("No se encuentra TELEGRAM_BOT_TOKEN. Por favor, configura esta variable de entorno.")


# Modelos para la evaluación de mensajes
class ModeratorOutput(BaseModel):
    """Salida del agente moderador con PydanticAI"""
    is_appropriate: bool = Field(description="Si el mensaje cumple con las reglas del grupo")
    violation_reason: Optional[str] = Field(None, description="Razón por la que el mensaje viola las reglas")
    improved_message: Optional[str] = Field(None, description="Versión mejorada del mensaje si contiene lenguaje inapropiado pero es válido")


@dataclass
class ModeratorDependencies:
    """Dependencias para el agente moderador"""
    group_guidelines: str
    message_text: str
    username: str


# Inicializar el agente de PydanticAI con LlamaGuard
def setup_moderator_agent(model_provider="ollama"):
    """Configurar y devolver el agente moderador utilizando PydanticAI y LlamaGuard"""
    
    # Seleccionar el modelo y proveedor basado en la configuración
    if model_provider == "ollama":
        from pydantic_ai.models import OllamaModel
        model = OllamaModel(model_name="llama-guard:latest")
    elif model_provider == "replicate":
        from pydantic_ai.models import ReplicateModel
        model = ReplicateModel(model_name="meta/llama-guard-3-8b")
    elif model_provider == "moderation_api":
        from pydantic_ai.models import ModerationApiLlamaGuardModel
        model = ModerationApiLlamaGuardModel(api_key=os.environ.get("MODERATION_API_KEY"))
    else:
        raise ValueError(f"Proveedor de modelo no soportado: {model_provider}")
    
    # Crear el agente moderador
    agent = Agent(
        "moderator",
        model=model,
        deps_type=ModeratorDependencies,
        output_type=ModeratorOutput,
    )
    
    @agent.system_prompt
    def moderator_system_prompt(ctx: RunContext[ModeratorDependencies]) -> str:
        """Definir el prompt del sistema para el moderador"""
        return f"""
        Eres un moderador de un grupo de Telegram encargado de verificar si los mensajes cumplen
        con las reglas y lineamientos del grupo. Debes evaluar cada mensaje y determinar si es apropiado.
        
        LINEAMIENTOS DEL GRUPO:
        {ctx.deps.group_guidelines}
        
        Tu tarea es analizar el siguiente mensaje enviado por un usuario y determinar:
        1. Si el mensaje es apropiado según los lineamientos del grupo
        2. Si no es apropiado, explicar por qué
        3. Si contiene lenguaje inapropiado pero la intención es válida, sugerir una mejor redacción
        
        MENSAJE A EVALUAR:
        Usuario: {ctx.deps.username}
        Mensaje: {ctx.deps.message_text}
        """
    
    return agent


# Funciones para gestionar el bot de Telegram
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enviar un mensaje cuando se emite el comando /start"""
    user = update.effective_user
    await update.message.reply_text(
        f'¡Hola {user.first_name}! Soy el bot moderador del grupo. Estoy aquí para asegurar que todos los mensajes cumplan con los lineamientos del grupo.'
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
                "y constructivas. No se permite spam ni promociones no autorizadas."
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
    if update.message.text.startswith('/') or update.effective_user.id == context.bot.id:
        return
    
    # Obtener información necesaria
    chat_id = update.effective_chat.id
    message_id = update.message.message_id
    user = update.effective_user
    username = user.username or user.first_name
    text = update.message.text
    
    # Obtener lineamientos del grupo
    group_guidelines = await get_group_description(context.bot, chat_id)
    
    # Informar al usuario que su mensaje está siendo revisado
    status_message = await context.bot.send_message(
        chat_id=chat_id,
        reply_to_message_id=message_id,
        text="⏳ Revisando este mensaje..."
    )
    
    try:
        # Configurar las dependencias para el agente
        deps = ModeratorDependencies(
            group_guidelines=group_guidelines,
            message_text=text,
            username=username
        )
        
        # Inicializar el agente moderador
        moderator_agent = setup_moderator_agent()
        
        # Evaluar el mensaje
        result = await moderator_agent.run(deps=deps)
        
        # Procesar el resultado
        if not result.is_appropriate:
            # Eliminar el mensaje inapropiado
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            
            # Notificar al usuario
            violation_message = (
                f"@{username}, tu mensaje ha sido eliminado porque viola los lineamientos del grupo:\n\n"
                f"{result.violation_reason}\n\n"
            )
            
            # Agregar sugerencia de mejora si está disponible
            if result.improved_message:
                violation_message += f"Sugerencia de redacción alternativa:\n{result.improved_message}"
            
            await context.bot.send_message(
                chat_id=chat_id,
                text=violation_message,
                reply_to_message_id=None  # No responder al mensaje original ya que fue eliminado
            )
        else:
            # El mensaje es apropiado
            await context.bot.delete_message(chat_id=chat_id, message_id=status_message.message_id)
    
    except Exception as e:
        logger.error(f"Error al moderar el mensaje: {e}")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_message.message_id,
            text="❌ No se pudo revisar este mensaje debido a un error técnico."
        )


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
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
