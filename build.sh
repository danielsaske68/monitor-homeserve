#!/bin/bash

# ===============================
# Build script para Render
# ===============================

echo "🔹 Actualizando pip..."
python3.11 -m pip install --upgrade pip

echo "🔹 Instalando dependencias..."
python3.11 -m pip install -r requirements.txt

echo "🔹 Instalando navegadores para Playwright..."
python3.11 -m playwright install

echo "✅ Build finalizado."
