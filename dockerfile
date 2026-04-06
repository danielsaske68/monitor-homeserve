FROM python:3.14-slim

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    curl wget unzip ca-certificates build-essential \
    libffi-dev libssl-dev git \
    && rm -rf /var/lib/apt/lists/*

# Copiar requerimientos e instalar Python deps
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el proyecto
COPY . .

# Puerto expuesto
EXPOSE 8080

# Comando de arranque
CMD ["python", "main.py"]
