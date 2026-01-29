# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Rules for Claude

- **Git operations require explicit permission**: Never execute `git commit`, `git push`, `git pull`, or `git branch` autonomously. Always ask for permission before any git operation.
- **No Claude references in commits**: Do not include "Co-Authored-By: Claude" or similar references in commit messages.
- **Push incrementali**: Quando una feature è completa e funzionante, proponi commit e push per mantenere il repository remoto aggiornato.
- **CLAUDE.md maintenance**: Keep this file under 200 lines. When updates are needed, ask for permission first and explain the proposed changes and why they are necessary.
- **Testing**: Claude è connesso direttamente alla VM via SSH. Può eseguire test, gestire Docker e verificare in tempo reale.

## Project Overview

AIutami is a Django-based real-time moderated voice conference platform. It provides WebSocket-based session management, WebRTC audio streaming with server-side forwarding, speech-to-text transcription (Azure), and AI moderation (Azure OpenAI).

## Common Commands

```bash
# Docker Compose (recommended)
make build              # Build Docker images
make up                 # Start all services (foreground)
make up-detached        # Start all services (background)
make down               # Stop all services
make logs               # Tail web container logs
make migrate            # Run Django migrations
make test               # Run test suite
make shell              # Django shell

# Run a single test
docker compose run --rm web python manage.py test apps.sessions.tests.TestClassName

# Local development (requires PostgreSQL and Redis running)
daphne -b 0.0.0.0 -p 8000 aiutami.asgi:application
```

## Architecture

### Service Stack
- **Web**: Django + Daphne ASGI server (port 8000 TCP, 10000-10050 UDP for WebRTC)
- **Database**: PostgreSQL 16 (port 5433→5432)
- **Cache/Queue**: Redis 7 (port 6379)

### Core Apps

| App | Responsibility | State Storage |
|-----|----------------|---------------|
| `sessions` | Session lifecycle (LOBBY→ACTIVE→CONCLUSION→CLOSED), participants, invitations | PostgreSQL |
| `turns` | Turn-taking state (IDLE/HUMAN_SPEAKING/AI_SPEAKING), reservations | Redis |
| `asr` | Speech-to-text via Azure, audio buffering, gating logic | Redis cache |
| `moderation` | AI intervention decisions, LLM calls to Azure OpenAI | Redis |
| `webrtc` | WebRTC peer connections, audio forwarding hub | In-memory |

### WebSocket Endpoints
- `ws/sessions/<session_id>/` - Session events (join, leave, state changes)
- `ws/turns/<session_id>/` - Turn state broadcasts
- `ws/webrtc/<session_id>/` - WebRTC signaling

### Data Flow
1. User joins via REST API → WebSocket subscription
2. Turn request via WebSocket → TurnManager (Redis) → Broadcast
3. Audio via WebRTC → ASRStreamWorker (gated) → Azure STT → Transcript
4. Turn ends → ModerationService → LLM decision → AI response (if needed)

### Key Patterns
- **ASR Gating**: Transcription only runs when user is current speaker (prevents echo/interference)
- **Audio Hub**: Server-side forwarding without mixing - speaker's audio forwarded to all other peers
- **Turn Reservation**: 8-second priority window for next speaker after current ends

## Environment Variables

Required in `.env`:
```
POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST
AZURE_SPEECH_KEY, AZURE_SPEECH_REGION
AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION
```

## Documentation

- `docs/specs/` - Functional specifications (sessions_v1_spec.md, turns_v1_spec.md)
- `docs/adr/` - Architecture Decision Records
- `docs/redis/` - Redis key schema
