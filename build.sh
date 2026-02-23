#!/bin/bash
echo "🔹 Usando Python 3.11 para instalar dependencias..."
python3.11 -m pip install --upgrade pip
python3.11 -m pip install -r requirements.txt

echo "🔹 Instalando navegadores para Playwright..."
python3.11 -m playwright install

echo "✅ Build finalizado."
