#!/usr/bin/env bash
# -*- coding: utf-8 -*-

# ===========================
# Build y Deploy para Railway
# ===========================

set -e  # Salir si hay error
echo "===== INICIANDO BUILD ====="

# Crear entorno virtual
if [ ! -d ".venv" ]; then
    echo "Creando entorno virtual..."
    python -m venv .venv
fi

# Activar entorno virtual
source .venv/bin/activate

# Actualizar pip
echo "Actualizando pip..."
pip install --upgrade pip

# Instalar dependencias
echo "Instalando requirements.txt..."
pip install -r requirements.txt

# Mensaje final
echo "===== BUILD COMPLETADO ====="
echo "Para ejecutar tu bot: .venv/bin/python main.py"
