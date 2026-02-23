# Activar virtualenv
source /app/.venv/bin/activate

# Instalar los navegadores de Playwright
python -m playwright install

# Ejecutar gunicorn
gunicorn main:app --bind 0.0.0.0:$PORT
