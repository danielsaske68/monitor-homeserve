FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias sistema
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copiar archivos
COPY requirements.txt .

# Instalar dependencias python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar proyecto
COPY . .

# Ejecutar bot
CMD ["python", "src/main.py"]
