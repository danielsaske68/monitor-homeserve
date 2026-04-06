# start.sh
#!/bin/bash
# instalar dependencias del sistema necesarias
apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    fonts-liberation \
    libnss3 \
    libxss1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libglib2.0-0 \
    libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

# instalar paquetes de Python
pip install --upgrade pip
pip install -r requirements.txt

# instalar navegadores de Playwright
playwright install --with-deps

# arrancar el servidor
gunicorn main:app --workers 1 --bind 0.0.0.0:$PORT
