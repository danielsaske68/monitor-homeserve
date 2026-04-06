#!/bin/bash

# Instala los navegadores de Playwright
playwright install --with-deps

# Arranca Gunicorn
gunicorn main:app --workers 1 --bind 0.0.0.0:$PORT
