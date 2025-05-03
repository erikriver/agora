"""Módulo para la moderación de contenido con LlamaGuard y PydanticAI."""

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext


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


def setup_moderator_agent(provider="ollama", **kwargs):
    """Configurar y devolver el agente moderador utilizando PydanticAI y LlamaGuard"""
    
    # Seleccionar el modelo y proveedor basado en la configuración
    if provider == "ollama":
        from pydantic_ai.models import OllamaModel
        host = kwargs.get("host", "http://localhost:11434")
        model = OllamaModel(model_name="llama-guard3:latest", provider_kwargs={"base_url": host})
    elif provider == "replicate":
        from pydantic_ai.models import ReplicateModel
        api_key = kwargs.get("api_key")
        if not api_key:
            raise ValueError("Se requiere REPLICATE_API_KEY para usar Replicate")
        model = ReplicateModel(model_name="meta/llama-guard-3-8b", provider_kwargs={"api_token": api_key})
    elif provider == "moderation_api":
        from pydantic_ai.models import HttpModel
        api_key = kwargs.get("api_key")
        if not api_key:
            raise ValueError("Se requiere MODERATION_API_KEY para usar Moderation API")
        model = HttpModel(
            model_name="llama-guard-3",
            provider_kwargs={
                "base_url": "https://api.moderationapi.com/v1",
                "headers": {"Authorization": f"Bearer {api_key}"}
            }
        )
    else:
        raise ValueError(f"Proveedor de modelo no soportado: {provider}")
    
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


async def moderate_content(agent, group_guidelines, message_text, username):
    """Moderación de contenido utilizando el agente configurado"""
    try:
        # Configurar las dependencias para el agente
        deps = ModeratorDependencies(
            group_guidelines=group_guidelines,
            message_text=message_text,
            username=username
        )
        
        # Evaluar el mensaje
        result = await agent.run(deps=deps)
        return result
    except Exception as e:
        # Log error y devolver resultado por defecto que permite el mensaje
        print(f"Error al moderar contenido: {e}")
        return ModeratorOutput(
            is_appropriate=True,
            violation_reason="Error al evaluar el mensaje, se permite por defecto",
            improved_message=None
        )