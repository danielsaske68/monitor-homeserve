# Dockerfile corregido para Playwright en Railway
FROM python:3.14-slim

# Evitar prompts
ENV DEBIAN_FRONTEND=noninteractive

# Instalar dependencias de sistema necesarias + build tools
RUN apt-get update && apt-get install -y \
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
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Directorio de trabajo
WORKDIR /app

# Copiar requirements
COPY requirements.txt .

# Actualizar pip e instalar dependencias
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo el proyecto
COPY . .

# Instalar navegadores de Playwright con dependencias
RUN playwright install --with-deps

# Puerto de Railway
ENV PORT=8080

# Comando de inicio
CMD ["gunicorn", "main:app", "--workers", "1", "--bind", "0.0.0.0:8080"]
