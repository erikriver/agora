"""Módulo para la moderación de contenido con LlamaGuard usando LangChain."""

from typing import Optional, Dict, Any
import os
from dataclasses import dataclass

from langchain_ollama import OllamaLLM
from langchain.prompts import PromptTemplate
from langchain.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field


class ModeratorOutput(BaseModel):
    """Resultado de la evaluación de moderación"""
    is_appropriate: bool = Field(description="Si el mensaje cumple con las reglas del grupo")
    violation_reason: Optional[str] = Field(None, description="Razón por la que el mensaje viola las reglas")
    improved_message: Optional[str] = Field(None, description="Versión mejorada del mensaje si es posible")


def setup_moderator_agent(provider="ollama", **kwargs):
    """Configurar y devolver el agente moderador utilizando LangChain"""
    
    # Seleccionar el modelo y proveedor basado en la configuración
    if provider == "ollama":
        host = kwargs.get("host", "http://localhost:11434")
        model_name = kwargs.get("model_name", "llama-guard3:1b")
        
        # Configurar el modelo de LangChain para Ollama
        llm = OllamaLLM(
            model=model_name,
            base_url=host
        )
    else:
        raise ValueError(f"Proveedor de modelo no soportado: {provider}")
    
    # Configurar el parser de salida
    parser = PydanticOutputParser(pydantic_object=ModeratorOutput)
    
    # Definir el template del prompt
    prompt_template = """
    Eres un moderador de un grupo de Telegram encargado de verificar si los mensajes cumplen
    con las reglas y lineamientos del grupo. Debes evaluar cada mensaje y determinar si es apropiado.
    
    LINEAMIENTOS DEL GRUPO:
    {group_guidelines}
    
    Tu tarea es analizar el siguiente mensaje enviado por un usuario y determinar:
    1. Si el mensaje es apropiado según los lineamientos del grupo
    2. Si no es apropiado, explicar por qué
    3. Si contiene lenguaje inapropiado pero la intención es válida, sugerir una mejor redacción
    
    MENSAJE A EVALUAR:
    Usuario: {username}
    Mensaje: {message_text}
    
    {format_instructions}
    """
    
    # Crear el prompt con el formato para el parser
    prompt = PromptTemplate(
        template=prompt_template,
        input_variables=["group_guidelines", "message_text", "username"],
        partial_variables={"format_instructions": parser.get_format_instructions()}
    )
    
    # Crear la cadena de moderación
    moderation_chain = prompt | llm | parser
    
    return moderation_chain


async def moderate_content(chain, group_guidelines, message_text, username):
    """Moderación de contenido utilizando la cadena configurada"""
    try:
        # Configurar los datos para la cadena
        try:
            # Intentar usar el parser estructurado primero
            raw_result = await chain.ainvoke({
                "group_guidelines": group_guidelines,
                "message_text": message_text,
                "username": username
            })
            
            # Asegurarse de que is_appropriate sea explícitamente un booleano
            result = ModeratorOutput(
                is_appropriate=bool(raw_result.is_appropriate),
                violation_reason=raw_result.violation_reason,
                improved_message=raw_result.improved_message
            )
        except Exception as parser_error:
            # Procesar la respuesta en texto plano que puede ser "safe" o "unsafe"
            print(f"Error al parsear JSON, intentando procesar texto plano: {parser_error}")
            
            # Obtener la respuesta directa del modelo sin el parser
            template = PromptTemplate(
                template="""
                Eres un moderador de un grupo de Telegram encargado de verificar si los mensajes cumplen
                con las reglas y lineamientos del grupo. Debes evaluar cada mensaje y determinar si es apropiado.
                
                LINEAMIENTOS DEL GRUPO:
                {group_guidelines}
                
                Tu tarea es analizar el siguiente mensaje enviado por un usuario y determinar:
                1. Si el mensaje es apropiado según los lineamientos del grupo
                2. Si no es apropiado, explicar por qué
                3. Si contiene lenguaje inapropiado pero la intención es válida, sugerir una mejor redacción
                
                MENSAJE A EVALUAR:
                Usuario: {username}
                Mensaje: {message_text}
                
                Responde en la siguiente estructura:
                Primera línea: "safe" o "unsafe"
                Segunda línea (si es unsafe): explicación de por qué viola las reglas
                Tercera línea (opcional): sugerencia de redacción alternativa
                """,
                input_variables=["group_guidelines", "message_text", "username"]
            )
            
            # Crear la cadena sin parser
            simple_chain = template | OllamaLLM(
                model="llama-guard3:1b",
                base_url=os.environ.get("OLLAMA_HOST", "http://localhost:11434")
            )
            
            # Obtener texto plano
            raw_text = await simple_chain.ainvoke({
                "group_guidelines": group_guidelines,
                "message_text": message_text,
                "username": username
            })
            
            print(f"Respuesta en texto plano: {raw_text}")
            
            # Procesar la respuesta
            lines = raw_text.strip().split('\n')
            first_line = lines[0].lower().strip()
            
            is_appropriate = first_line == "safe"
            violation_reason = lines[1].strip() if len(lines) > 1 and not is_appropriate else None
            improved_message = lines[2].strip() if len(lines) > 2 and not is_appropriate else None
            
            result = ModeratorOutput(
                is_appropriate=is_appropriate,
                violation_reason=violation_reason,
                improved_message=improved_message
            )
        
        print(f"Resultado procesado: {result}")
        return result
    except Exception as e:
        # En caso de error, permitir el mensaje por defecto
        print(f"Error al moderar contenido: {e}")
        # Por seguridad, ahora por defecto marcamos como NO apropiado si hay un error irrecuperable
        return ModeratorOutput(
            is_appropriate=False,  # Por defecto, NO permitir en caso de error
            violation_reason="Error en la evaluación del mensaje. Por seguridad, se ha eliminado. Los administradores revisarán este caso.",
            improved_message=None
        )