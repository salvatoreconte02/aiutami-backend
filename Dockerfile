# Dockerfile per il backend Django di AIutami

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Dipendenze di sistema minime (psycopg, ecc.) + certificati CA
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia dei requirements
COPY requirements.txt /app/

# Installazione dipendenze Python (incluso Daphne)
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copia del codice del progetto
COPY . /app/

# Espone la porta 8000
EXPOSE 8000

# Avvio tramite Daphne (ASGI), non più runserver
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "aiutami.asgi:application"]