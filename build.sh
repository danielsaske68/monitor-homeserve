#!/bin/bash
# Activar virtualenv de Railway
source /app/.venv/bin/activate

# Instalar navegadores de Playwright
python -m playwright install

# Arrancar servidor
exec gunicorn main:app --bind 0.0.0.0:$PORT
