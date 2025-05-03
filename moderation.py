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
from langchain_ollama import OllamaLLM
from langchain.prompts import PromptTemplate

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
    """Salida del agente moderador"""
    is_appropriate: bool = Field(description="Si el mensaje cumple con las reglas del grupo")
    violation_reason: Optional[str] = Field(None, description="Razón por la que el mensaje viola las reglas")
    improved_message: Optional[str] = Field(None, description="Versión mejorada del mensaje si es posible")


@dataclass
class ModeratorDependencies:
    """Dependencias para el agente moderador"""
    group_guidelines: str
    message_text: str
    username: str


# Inicializar el agente de PydanticAI con LlamaGuard
def setup_moderator_agent(provider="ollama", **kwargs):
    """Configurar y devolver el agente moderador utilizando LangChain y Ollama"""
    
    # Configurar Ollama
    llm = OllamaLLM(
        model="llama3.2:latest",
        base_url=kwargs.get("host", "http://localhost:11434")
    )
    
    # Definir el template del prompt
    prompt_template = """
    Actúa como un moderador y evalúa si el siguiente mensaje cumple con las reglas del grupo.
    
    REGLAS DEL GRUPO:
    {group_guidelines}
    
    MENSAJE A EVALUAR:
    Usuario: {username}
    Mensaje: {message_text}
    
    INSTRUCCIONES:
    1. Responde en la primera línea solo con "safe" o "unsafe"
    2. Si es unsafe, explica en la siguiente línea por qué viola las reglas
    3. Si es posible mejorar el mensaje, sugiere una versión apropiada
    """
    
    prompt = PromptTemplate(
        template=prompt_template,
        input_variables=["group_guidelines", "username", "message_text"]
    )
    
    return prompt | llm


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
    try:
        # Ignorar mensajes de comandos y del propio bot
        if update.message.text.startswith('/') or update.effective_user.id == context.bot.id:
            return
        
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
            # Configurar el agente moderador
            chain = setup_moderator_agent()
            
            # Evaluar el mensaje
            result = await chain.ainvoke({
                "group_guidelines": group_guidelines,
                "message_text": text,
                "username": username
            })
            
            lines = result.strip().split('\n')
            is_safe = lines[0].lower().strip() == "safe"
            
            if not is_safe:
                # Eliminar el mensaje inapropiado
                await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
                
                violation_message = (
                    f"@{username}, tu mensaje ha sido eliminado porque viola los lineamientos del grupo:\n\n"
                    f"{lines[1] if len(lines) > 1 else 'Violación de reglas'}\n\n"
                )
                
                if len(lines) > 2:
                    violation_message += f"Sugerencia de redacción alternativa:\n{lines[2]}"
                
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=violation_message
                )
            else:
                # El mensaje es apropiado
                await context.bot.delete_message(chat_id=chat_id, message_id=status_message.message_id)
                
        except Exception as e:
            error_detail = f"Error en la moderación: {str(e)}"
            logger.error(error_detail)
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message.message_id,
                text=f"❌ Error técnico detallado: {error_detail}"
            )
            
    except Exception as e:
        logger.error(f"Error general: {str(e)}")
        await update.message.reply_text(f"❌ Error general del bot: {str(e)}")


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
