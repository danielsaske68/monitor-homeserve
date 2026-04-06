FROM python:3.14-slim

WORKDIR /app

# Dependencias del sistema
RUN apt-get update && apt-get install -y \
    curl wget unzip ca-certificates fonts-liberation \
    libnss3 libxss1 libasound2 libatk-bridge2.0-0 libgtk-3-0 \
    libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libglib2.0-0 \
    libfontconfig1 build-essential python3-dev libffi-dev libssl-dev \
    pkg-config git cython3 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip
# Forzar greenlet compatible con Python 3.14
RUN pip install --no-cache-dir "greenlet>=3.1.2" -r requirements.txt

COPY . .

# Playwright
RUN python -m playwright install

CMD ["python", "main.py"]
