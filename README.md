# AIutami

Piattaforma di conferenze vocali moderate in tempo reale con supporto AI.

## Requisiti

- Docker e Docker Compose

## Avvio

```bash
# Configurare le variabili d'ambiente
cp .env.example .env

# Avviare i servizi
make up
```

L'applicazione sarà disponibile su `http://localhost:8000`.

## Stack tecnologico

- Django + Daphne (ASGI)
- PostgreSQL
- Redis
- Azure Speech Services (STT/TTS)
- Azure OpenAI
