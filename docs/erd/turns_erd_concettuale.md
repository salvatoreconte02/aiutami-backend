ERD concettuale — Turns (MVP)

Schema concettuale: entità logiche, responsabilità, relazioni e vincoli funzionali.
L’app turns non usa il database relazionale: lo stato è mantenuto in Redis.
L’ERD descrive quindi entità logiche e strutture di stato, non tabelle.

⸻

1. Entità logiche

1) TurnState (entità logica principale)
	•	Scopo: rappresentare lo stato attuale del turno in una sessione vocale.
	•	Attributi concettuali:
	•	session_id — riferimento alla Session.
	•	state ∈ {IDLE, HUMAN_SPEAKING, AI_SPEAKING}.
	•	current_speaker_user_id (solo se HUMAN_SPEAKING).
	•	current_speaker = "AI" (solo se AI_SPEAKING).
	•	started_at — timestamp di inizio turno.
	•	Persistenza: Redis (chiave hash).

2) Reservation (entità logica non-stato)
	•	Scopo: garantire priorità di parola a un utente dopo la fine di uno speaking.
	•	Attributi concettuali:
	•	session_id
	•	reserved_user_id
	•	expires_at — timestamp di scadenza (circa 8 secondi).
	•	Persistenza: Redis (string con TTL).

Nota: la prenotazione non è uno stato; è una condizione accessoria che coesiste con lo stato IDLE.

3) TurnEvent (eventi applicativi)
	•	Scopo: tracciare gli eventi significativi del ciclo del turno.
	•	Attributi concettuali:
	•	tipo evento: HUMAN_STARTED, HUMAN_ENDED,
AI_STARTED, AI_ENDED,
RESERVATION_SET, RESERVATION_EXPIRED.
	•	timestamp.
	•	dati minimi (es. user_id, duration_ms).
	•	Persistenza: opzionale (audit in database),
oppure eventi solo realtime (WS).

L’MVP può rinviare la persistenza in DB; i WS sono sufficienti per la UI.

⸻

2. Relazioni (concettuali)
	•	Session 1 — 1 TurnState
Ogni sessione ha un solo stato del turno attivo alla volta.
	•	Session 1 — 0..1 Reservation
Una sessione può avere al più una prenotazione attiva.
	•	TurnState 1 — N TurnEvent
Gli eventi descrivono l’evoluzione dello stato del turno.

⸻

3. Vincoli funzionali globali
	•	Turno unico: in una sessione può esistere un solo speaker attivo.
	•	Mutua esclusione:
	•	se HUMAN_SPEAKING, l’AI non può intervenire.
	•	se AI_SPEAKING, nessun umano può parlare.
	•	Prenotazione:
	•	può essere attivata solo durante HUMAN_SPEAKING.
	•	valida solo nella finestra di priorità (circa 8 secondi).
	•	scaduta → eliminata automaticamente.
	•	Fine speaking:
	•	quando un umano finisce, se esiste una prenotazione attiva → turno passa a IDLE con priorità per il prenotato.
	•	se non esiste prenotazione → semplice IDLE.
	•	L’AI non può interrompere un prenotato durante la finestra di priorità.
	•	L’AI non può iniziare a parlare se un umano sta parlando (gestito dai trigger di moderazione nel backend).

⸻

4. Modellazione Redis (chiavi logiche)

Chiave: session:{session_id}:turn

Tipo: Hash

Campi tipici:
	•	state
	•	current_speaker_user_id
	•	started_at

⸻

Chiave: session:{session_id}:reservation

Tipo: String (user_id)
TTL: 8 secondi circa

⸻

Chiave: session:{session_id}:events

Tipo: List (opzionale, solo se serve audit minimale)

⸻

5. Semantica Operazioni
	•	begin_human_speaking(user_id)
Aggiorna TurnState → HUMAN_SPEAKING.
	•	end_human_speaking(user_id)
TurnState → IDLE;
se esiste reservation → turno riservato.
	•	begin_ai_speaking()
TurnState → AI_SPEAKING.
	•	end_ai_speaking()
TurnState → IDLE.
	•	reserve_turn(user_id)
Crea reservation con TTL.
	•	reservation_expired
Turno rimane IDLE senza priorità.
