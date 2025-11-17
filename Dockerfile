# Dockerfile per il backend Django di AIutami

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Dipendenze di sistema minime (psycopg, ecc.)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia dei requirements
COPY requirements.txt /app/

RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copia del codice del progetto
COPY . /app/

# Porta esposta (Django dev server)
EXPOSE 8000

# Comando di default (può essere sovrascritto da docker-compose)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]