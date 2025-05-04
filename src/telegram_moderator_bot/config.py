"""Configuración y variables de entorno para el bot."""

import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Bot Token
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN no está configurado en .env")

# Configuración del modelo LlamaGuard
LLAMAGUARD_PROVIDER = os.getenv("LLAMAGUARD_PROVIDER", "ollama")  # ollama, replicate, moderation_api
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
