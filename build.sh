#!/bin/bash
# build.sh para Render usando Python 3.11 y Playwright

# Activar virtualenv
source .venv/bin/activate

# Instalar navegadores de Playwright (sin root)
python -m playwright install

# Iniciar la app con Gunicorn
gunicorn main:app --bind 0.0.0.0:$PORT
