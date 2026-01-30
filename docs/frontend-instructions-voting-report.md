# Istruzioni Frontend - Votazione e Report PDF

## Fase CONCLUSION - Votazione

### UI Votazione
- Mostrare 3 bottoni: **Eddie**, **Mickey**, **Billy**
- Bottoni **disabilitati** inizialmente (moderatore sta parlando)
- Abilitare dopo evento WebSocket `AI_ENDED`

### Flusso voto
1. Utente clicca su un sospetto
2. `POST /api/sessions/{id}/vote/` con `{"suspect": "Eddie|Mickey|Billy"}`
3. Mostrare stato attesa: "Voti: X/3"
4. Aggiornare contatore ad ogni `VOTE_CAST`

### Reveal risultati
- Quando arriva `ALL_VOTED`: mostrare risultati con chi ha indovinato
- Payload contiene: `results`, `guilty`, `success_rate`, `closing_in_seconds`
- Countdown 15 secondi
- Bottone "Chiudi Sessione" solo per host (`POST /api/sessions/{id}/close/`)

---

## Storico e Report

### SessionDetail
Nuovi campi disponibili su `GET /api/sessions/{id}/`:
- `report_available`: true se sessione CLOSED
- `votes_summary`: risultati votazione (null se non CLOSED)

### Download PDF
- `GET /api/sessions/{id}/report/` restituisce PDF
- Disponibile solo per partecipanti di sessioni CLOSED

---

## WebSocket Events

| Event | Azione |
|-------|--------|
| `STATE_CHANGED` (CONCLUSION) | Mostra UI voto (disabilitata) |
| `AI_ENDED` | Abilita bottoni voto |
| `VOTE_CAST` | Aggiorna contatore |
| `ALL_VOTED` | Mostra risultati + countdown |
| `SESSION_CLOSED` | Redirect a storico |

---

## Endpoint

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| POST | `/api/sessions/{id}/vote/` | Invia voto |
| GET | `/api/sessions/{id}/vote-status/` | Stato voti |
| POST | `/api/sessions/{id}/close/` | Chiudi (solo host) |
| GET | `/api/sessions/{id}/report/` | Scarica PDF |
