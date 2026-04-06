# Dockerfile corregido para Playwright y greenlet
FROM python:3.14-slim

WORKDIR /app

# Dependencias del sistema para Playwright y compilación de paquetes nativos
RUN apt-get update && apt-get install -y \
    curl wget unzip ca-certificates fonts-liberation \
    libnss3 libxss1 libasound2 libatk-bridge2.0-0 libgtk-3-0 \
    libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libglib2.0-0 \
    libfontconfig1 build-essential python3-dev libffi-dev libssl-dev \
    pkg-config git \
    && rm -rf /var/lib/apt/lists/*

# Copiar dependencias Python
COPY requirements.txt .

# Actualizar pip y herramientas de compilación
RUN pip install --upgrade pip setuptools wheel

# Instalar dependencias Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo el proyecto
COPY . .

# Instalar navegadores de Playwright con dependencias
RUN pip install playwright
RUN playwright install --with-deps

# Exponer puerto
EXPOSE 5000

# Comando por defecto
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000"]
