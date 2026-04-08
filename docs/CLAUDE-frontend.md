# CLAUDE.md — AIutami Frontend

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Rules for Claude

- **Git operations require explicit permission**: Never execute `git commit`, `git push`, `git pull`, or `git branch` autonomously. Always ask for permission before any git operation.
- **CLAUDE.md maintenance**: Keep this file under 200 lines. When updates are needed, ask for permission first.
- **NO riferimenti a Claude nei commit**: non aggiungere mai "Co-Authored-By" o altri riferimenti a Claude nei messaggi di commit.

## Project Overview

AIutami è una piattaforma di conferenza vocale in tempo reale con moderatore AI. Questo è il **frontend** (mobile-first PWA). Il backend è in una repo separata (Django + Daphne).

**Contesto:** tesi magistrale al Politecnico di Milano (Prof.ssa Garzotto, HCI).

## Tech Stack

- **React 19** + **Vite**
- **Tailwind CSS** — mobile-first, design system custom
- **PWA** — installabile su telefono senza app store
- **WebRTC** — streaming audio bidirezionale (microfono)
- **WebSocket** — eventi sessione, turn-taking, signaling WebRTC

## Backend API Reference

Il backend gira su Django + Daphne (porta 8000 in dev, dietro Nginx in prod).

### Autenticazione (JWT)

Tutte le richieste REST usano `Authorization: Bearer <token>`.
Tutte le connessioni WebSocket usano `?token=<access_token>` nella query string.

| Endpoint | Metodo | Descrizione |
|----------|--------|-------------|
| `/api/auth/token/` | POST | Login → `{access, refresh}` |
| `/api/auth/token/refresh/` | POST | Rinnova access token |

- Access token: 30 minuti
- Refresh token: 7 giorni

### Accounts

| Endpoint | Metodo | Auth | Descrizione |
|----------|--------|------|-------------|
| `/api/accounts/signup/` | POST | No | Registrazione `{username, email, password}` |
| `/api/accounts/me/` | GET | Sì | Profilo utente corrente |

### Sessions

| Endpoint | Metodo | Auth | Descrizione |
|----------|--------|------|-------------|
| `/api/sessions/` | POST | Sì | Crea sessione `{title, context, min_size, max_size}` |
| `/api/sessions/mine/` | GET | Sì | Le mie sessioni (filtro `?state=LOBBY`) |
| `/api/sessions/{id}/` | GET | Sì | Dettaglio sessione |
| `/api/sessions/{id}/start/` | POST | Host | Avvia sessione (LOBBY→ACTIVE) |
| `/api/sessions/{id}/invitations/` | POST | Host | Crea link invito |
| `/api/sessions/join_by_token/` | POST | Sì | Entra con token invito `{token}` |
| `/api/sessions/{id}/participants/` | GET | Sì | Lista partecipanti |
| `/api/sessions/{id}/ready_to_conclude/` | POST | Sì | Segna pronto per concludere |
| `/api/sessions/{id}/vote/` | POST | Sì | Vota `{suspect}` |
| `/api/sessions/{id}/vote-status/` | GET | Sì | Stato votazione |
| `/api/sessions/{id}/close/` | POST | Host | Chiudi sessione |
| `/api/sessions/{id}/report/` | GET | Sì | Scarica report PDF |

**Stati sessione:** LOBBY → ACTIVE → CONCLUSION → CLOSED

**Contesti:** MURDER_MYSTERY, THERAPEUTIC, WORKPLACE, ACADEMIC

### WebSocket Endpoints

Tutti richiedono `?token=JWT` nella query string.

**1. Sessions broadcast (read-only):** `ws://host/ws/sessions/{session_id}/`
- Riceve: `sessions.state_changed`, `sessions.vote_cast`, `sessions.all_voted`, `sessions.session_closed`

**2. Turns (bidirezionale):** `ws://host/ws/turns/{session_id}/`
- Invia: `turns.get_state`, `turns.request_speak`, `turns.end_speak`, `turns.request_reserve`, `turns.ping`
- Riceve: `turns.state` (payload con state, current_speaker_user_id, reservation_user_id, etc.)
- Riceve: `turns.event` (HUMAN_STARTED, HUMAN_ENDED, AI_STARTED, AI_ENDED, RESERVATION_SET, RESERVATION_EXPIRED)
- **Stati turno:** IDLE, HUMAN_SPEAKING, AI_SPEAKING, AI_INTRODUCING

**3. WebRTC signaling:** `ws://host/ws/webrtc/{session_id}/`
- Invia: `webrtc.offer` (SDP), `webrtc.ice_candidate`
- Riceve: `webrtc.answer` (SDP), `webrtc.ice_candidate`, `webrtc.error`
- STUN server: `stun:stun.l.google.com:19302`
- Audio: 48kHz, mono, PCM s16, frame 20ms

## Key Frontend Flows

### Sessione completa
1. Login/Signup → JWT tokens
2. Crea sessione (host) o entra con token invito
3. Lobby: attendi partecipanti, host avvia
4. Active: connetti WebRTC (audio), apri WS turns + sessions
5. Parla: request_speak → parla → end_speak
6. Conclusion: vota (murder mystery)
7. Closed: scarica report PDF

### WebRTC Audio
- Il browser manda offer SDP al server via WS
- Il server risponde con answer SDP
- L'audio va al server che lo forwarda agli altri partecipanti
- ASR attivo solo per chi ha il turno di parola (gating)

## Common Commands

```bash
npm run dev          # dev server (Vite, porta 5173)
npm run build        # build produzione
npm run preview      # preview build locale
```

## CORS

Il backend accetta richieste da `http://localhost:5173` e `http://127.0.0.1:5173` in dev.
