# Usa la imagen slim de Python 3.14
FROM python:3.14-slim

# Establece directorio de trabajo
WORKDIR /app

# Instala dependencias del sistema necesarias
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    unzip \
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

# Copia el archivo de dependencias
COPY requirements.txt .

# Actualiza pip y instala las dependencias Python
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo el proyecto al contenedor
COPY . .

# Instala navegadores de Playwright
RUN playwright install --with-deps

# Expone el puerto que usa Flask (ajusta si es diferente)
EXPOSE 5000

# Comando por defecto al iniciar el contenedor
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000"]
