# Dockerfile per il backend Django di AIutami

# Base image spostata a Python 3.11 su Debian bullseye
# (più compatibile con Azure Speech SDK)
FROM python:3.11-bullseye

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Dipendenze di sistema:
# - build-essential, libpq-dev: per psycopg2 / compilazioni base
# - ca-certificates, curl: certificati e HTTP client
# - libcurl4, libgssapi-krb5-2, zlib1g: stack HTTP/TLS usato dallo Speech SDK
# - libasound2: libreria audio usata internamente dallo Speech SDK
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    ca-certificates \
    curl \
    libcurl4 \
    libgssapi-krb5-2 \
    zlib1g \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia dei requirements
COPY requirements.txt /app/

# Installazione dipendenze Python (incluso Daphne e azure-cognitiveservices-speech)
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copia del codice del progetto
COPY . /app/

# Espone la porta 8000
EXPOSE 8000

# Avvio tramite Daphne (ASGI)
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "aiutami.asgi:application"]