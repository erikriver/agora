uv venv

source .venv/bin/activate

uv pip install -e .

python -m telegram_moderator_bot.main

