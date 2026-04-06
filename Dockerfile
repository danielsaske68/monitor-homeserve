# Dockerfile optimizado para Railway y Python 3.14
FROM python:3.14-slim

# Establecer directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema necesarias
RUN apt-get update && apt-get install -y \
    curl wget unzip ca-certificates fonts-liberation \
    libnss3 libxss1 libasound2 libatk-bridge2.0-0 libgtk-3-0 \
    libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libglib2.0-0 \
    libfontconfig1 build-essential python3-dev libffi-dev libssl-dev \
    pkg-config git python3.14-venv cython \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements.txt
COPY requirements.txt .

# Actualizar pip e instalar dependencias de Python
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo el proyecto
COPY . .

# Instalar navegadores de Playwright
RUN python -m playwright install

# Comando por defecto (ajusta según tu app)
CMD ["python", "main.py"]
