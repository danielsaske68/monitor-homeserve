# ----------------------------
# Dockerfile para Python 3.14 + Playwright
# ----------------------------
FROM python:3.14-slim

# ----------------------------
# Instalar dependencias del sistema
# ----------------------------
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
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# ----------------------------
# Crear directorio de la app
# ----------------------------
WORKDIR /app

# ----------------------------
# Copiar requirements.txt
# ----------------------------
COPY requirements.txt .

# ----------------------------
# Actualizar pip e instalar dependencias
# ----------------------------
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# ----------------------------
# Copiar todo el proyecto
# ----------------------------
COPY . .

# ----------------------------
# Instalar navegadores de Playwright
# ----------------------------
RUN playwright install --with-deps

# ----------------------------
# Puerto y comando
# ----------------------------
ENV PORT=8080
EXPOSE 8080

CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:8080", "main:app"]
