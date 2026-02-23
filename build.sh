#!/bin/bash

# Activar el entorno virtual
source /app/.venv/bin/activate

# Instalar navegadores de Playwright
python -m playwright install

# Ejecutar Gunicorn para iniciar la app
gunicorn main:app --bind 0.0.0.0:$PORT
