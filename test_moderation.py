import asyncio
from langchain_ollama import OllamaLLM
from langchain.prompts import PromptTemplate
from langchain.schema.runnable import RunnableSequence
from pydantic import BaseModel
from typing import Optional

class ModeratorOutput(BaseModel):
    is_appropriate: bool
    violation_reason: Optional[str] = None
    improved_message: Optional[str] = None

async def setup_moderator_agent():
    # Configurar Ollama
    llm = OllamaLLM(
        model="llama3.2:latest",
        base_url="http://localhost:11434"
    )
    
    # Definir el template del prompt
    prompt_template = """
    Actúa como un moderador y evalúa si el siguiente mensaje cumple con las reglas del grupo.
    
    REGLAS DEL GRUPO:
    {guidelines}
    
    MENSAJE A EVALUAR:
    Usuario: {username}
    Mensaje: {message}
    
    INSTRUCCIONES:
    1. Responde en la primera línea solo con "safe" o "unsafe"
    2. Si es unsafe, explica en la siguiente línea por qué viola las reglas
    3. Si es posible mejorar el mensaje, sugiere una versión apropiada
    """
    
    prompt = PromptTemplate(
        template=prompt_template,
        input_variables=["guidelines", "username", "message"]
    )
    
    return prompt | llm

async def moderate_content(chain, group_guidelines, message_text, username):
    try:
        result = await chain.ainvoke({
            "guidelines": group_guidelines,
            "username": username,
            "message": message_text
        })
        
        lines = result.strip().split('\n')
        is_safe = lines[0].lower().strip() == "safe"
        
        return ModeratorOutput(
            is_appropriate=is_safe,
            violation_reason=lines[1] if not is_safe and len(lines) > 1 else None,
            improved_message=lines[2] if not is_safe and len(lines) > 2 else None
        )
    except Exception as e:
        print(f"Error en moderación: {e}")
        return ModeratorOutput(is_appropriate=True)

async def test_moderation():
    # 1. Configurar el agente
    chain = await setup_moderator_agent()

    # 2. Definir reglas
    group_guidelines = """
    1. No insultos ni lenguaje ofensivo
    2. No spam ni contenido comercial
    3. Mantener discusiones respetuosas
    4. No compartir información personal
    5. No mencionar a otros grupos o canales
    6. No compartir links de adultos
    7. No compartir links maliciosos
    8. No ofrecer productos o servicios
    """

    # 3. Mensajes de prueba
    test_messages = [
        ("usuario1", "Hola a todos, ¿cómo están?"),  # Apropiado
        ("usuario2", "Eres un idiota!"),  # Inapropiado - insulto
        ("usuario3", "Compra mis productos en www.spam.com"),  # Inapropiado - spam
        ("usuario4", "Visiten mi grupo de crypto t.me/crypto"),  # Inapropiado - otro grupo
        ("usuario5", "Mi número es 123456789"),  # Inapropiado - info personal
    ]

    # 4. Probar cada mensaje
    for username, message in test_messages:
        print(f"\n{'='*50}")
        print(f"Probando mensaje de {username}: '{message}'")
        result = await moderate_content(chain, group_guidelines, message, username)
        print(f"¿Es apropiado?: {result.is_appropriate}")
        if not result.is_appropriate:
            print(f"Razón: {result.violation_reason}")
            if result.improved_message:
                print(f"Sugerencia: {result.improved_message}")

if __name__ == "__main__":
    asyncio.run(test_moderation())
