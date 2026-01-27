# AIutami — Specifiche funzionali Turns (MVP, v1)

## 1. Scopo

L’app *turns* governa i **turni di parola** all’interno di una sessione vocale moderata:  
decide chi può parlare, quando, con quale priorità, e come l’AI può intervenire.

Lo stato dei turni è condiviso tra i partecipanti tramite:

- **Redis** → stato vivo (chi è lo speaker, chi è prenotato, ecc.);
- **WebSocket** → canale realtime tra backend e frontend per comandi ed eventi.

Gli endpoint HTTP, se usati, servono solo come supporto/debug, non sono il canale principale di interazione.

---

## 2. Perimetro (in scope)

- Stato del turno per sessione:
  - `IDLE` (nessuno parla),
  - `HUMAN_SPEAKING` (sta parlando un utente),
  - `AI_SPEAKING` (sta parlando il moderatore AI).
- Gestione delle richieste:
  - richiesta di parlare,
  - termine dell’intervento,
  - prenotazione del turno.
- Finestra di priorità per il prenotato (≈ 8 s).
- Blocco totale durante l’intervento AI.
- Eventi WebSocket per aggiornare l’interfaccia su:
  - chi sta parlando,
  - chi è prenotato,
  - quando cambia lo stato del turno.

---

## 3. Fuori dall’MVP (out of scope)

- Coda di più prenotati (solo **una** prenotazione alla volta).
- Configurazione dinamica della durata finestra (valore fisso, es. 8 s).
- Integrazione diretta con ASR/TTS/LLM (gestite da altre app).
- Persistenza storica dei turni in DB relazionale (opzionale in futuro).
- Qualsiasi logica legata al contenuto del parlato (testo, sentiment, ecc.).

---

## 4. Stati logici del turno

### 4.1 Stati di base

Per ogni `session_id` esiste esattamente **un** stato di turno:

1. **IDLE**
   - Nessuno sta parlando.
   - Significato:
     - il microfono è “libero”;
     - se esiste una prenotazione attiva, solo il prenotato può prendere la parola durante una finestra di priorità, altrimenti chiunque.

2. **HUMAN_SPEAKING**
   - Sta parlando un utente umano.
   - Attributi concettuali:
     - `current_speaker_user_id`
   - Significato:
     - solo questo utente può terminare l’intervento;
     - al massimo un altro utente può risultare **prenotato**.

3. **AI_SPEAKING**
   - Sta parlando il moderatore AI.
   - Attributi concettuali:
     - `current_speaker = "AI"`
   - Significato:
     - nessun utente può parlare o prenotarsi;
     - al termine dell’audio AI si torna a `IDLE`.

### 4.2 Prenotazione (condizione accessoria)

La prenotazione **non è uno stato a sé**, ma una condizione associata:

- `reservation_user_id` — utente che ha priorità;
- `reservation_expires_at` — scadenza finestra (es. now + 8 s).

Durante la finestra:

- lo stato del turno è ancora `IDLE` (nessuno sta parlando),
- ma solo `reservation_user_id` può ottenere lo speaking.

Alla scadenza:

- la prenotazione viene eliminata,
- il turno rimane in `IDLE` libero.

---

## 5. Trasporto: WebSocket e messaggi

### 5.1 Canale WebSocket della sessione

Per ogni sessione, i client si connettono a un canale WS dedicato, ad esempio:

- `wss://…/ws/sessions/{session_id}/?token=<JWT>`

Autenticazione:

- il token JWT viene passato nella query string o in header iniziale;
- solo utenti che sono **membri** della sessione (host o participant) possono inviare comandi turn.

Il canale viene usato per:

- **comandi in ingresso** dal frontend (richieste di turno),
- **eventi in uscita** dal backend (aggiornamenti di stato).

---

## 6. Comandi WebSocket in ingresso (dal client al backend)

I messaggi sono JSON con un campo obbligatorio `type`.  
Gli esempi omettono eventuali campi tecnici (es. `client_msg_id`).

### 6.1 Richiesta di parlare

- **type**: `turn.request_speak`
- **payload**:
  ```json
  {
    "type": "turn.request_speak",
    "session_id": "<uuid>"
  }

Comportamento funzionale:
	•	Se il turno è:
	•	IDLE senza finestra attiva → il chiamante diventa speaker (HUMAN_SPEAKING).
	•	IDLE con finestra attiva:
	•	se il chiamante è il prenotato → diventa speaker;
	•	se non è il prenotato → rifiuto (errore).
	•	Se il turno è:
	•	HUMAN_SPEAKING → rifiuto (microfono occupato).
	•	AI_SPEAKING → rifiuto (sta parlando il moderatore).

Risposte tipiche:
	•	Ack al chiamante:

    {
  "type": "turn.request_speak.ack",
  "ok": true,
  "state": "HUMAN_SPEAKING"
}

	•	Broadcast a tutti i membri:
    {
  "type": "turn.state",
  "state": "HUMAN_SPEAKING",
  "speaker": {
    "id": 12,
    "username": "salvo"
  },
  "reserved_user": null,
  "reservation_window_active": false
}

6.2 Termine dell’intervento umano
	•	type: turn.end_speak
	•	payload:
    {
  "type": "turn.end_speak",
  "session_id": "<uuid>"
}

Comportamento funzionale:
	•	Consentito solo se:
	•	il turno è HUMAN_SPEAKING,
	•	il chiamante è current_speaker_user_id.
	•	Effetto:
	•	speaker rimosso → turno torna a IDLE;
	•	se esiste reservation_user_id:
	•	si apre la finestra di priorità (circa 8s) per il prenotato.

Broadcast tipico:
{
  "type": "turn.state",
  "state": "IDLE",
  "speaker": null,
  "reserved_user": {
    "id": 34,
    "username": "sara"
  },
  "reservation_window_active": true,
  "reservation_window_seconds": 8
}
Se non esisteva prenotazione, reserved_user sarà null e reservation_window_active = false.

⸻

6.3 Prenotazione del turno
	•	type: turn.request_reserve
	•	payload:
    {
  "type": "turn.request_reserve",
  "session_id": "<uuid>"
}

Comportamento funzionale:
	•	Consentito solo se:
	•	il turno è HUMAN_SPEAKING,
	•	non esiste già un reservation_user_id,
	•	il chiamante non è lo speaker attuale.
	•	Effetto:
	•	viene salvata reservation_user_id con una scadenza associata alla futura finestra di priorità.

Broadcast tipico:
{
  "type": "turn.reserved",
  "reserved_user": {
    "id": 34,
    "username": "sara"
  }
}
La finestra di priorità si aprirà solo quando lo speaker attuale terminerà.

⸻

6.4 Lettura stato turno (ricostruzione UI)
	•	type: turn.get_state
	•	payload:
{
  "type": "turn.get_state",
  "session_id": "<uuid>"
}

Risposta (solo al chiamante):
{
  "type": "turn.state",
  "state": "IDLE" | "HUMAN_SPEAKING" | "AI_SPEAKING",
  "speaker": {
    "id": 12,
    "username": "salvo"
  } | null,
  "reserved_user": {
    "id": 34,
    "username": "sara"
  } | null,
  "reservation_window_active": true | false,
  "reservation_window_seconds": 8   // opzionale
}

7. Messaggi WebSocket in uscita (dal backend ai client)

Oltre alle risposte specifiche (.ack), il backend invia broadcast a tutti i membri via canale WS di sessione.

Messaggi principali:

7.1 Stato del turno
	•	type: turn.state

Usato in due casi:
	•	come risposta a turn.get_state;
	•	come broadcast quando qualcosa cambia (speaker, prenotato, finestra, AI).

Formato:
{
  "type": "turn.state",
  "state": "IDLE" | "HUMAN_SPEAKING" | "AI_SPEAKING",
  "speaker": { "id": ..., "username": "..." } | null,
  "reserved_user": { "id": ..., "username": "..." } | null,
  "reservation_window_active": true | false,
  "reservation_window_seconds": 8
}

7.2 Prenotazione
	•	type: turn.reserved
Emesso quando viene accettata una prenotazione.
{
  "type": "turn.reserved",
  "reserved_user": {
    "id": 34,
    "username": "sara"
  }
}

	•	type: turn.reservation_expired
Emesso quando la finestra di priorità scade senza intervento del prenotato.
{
  "type": "turn.reservation_expired"
}

> **Nota:** L'evento `turn.reservation_expired` viene inviato automaticamente dal server dopo 8 secondi dalla scadenza della finestra di prenotazione, senza necessità di azioni da parte dei client.

7.3 AI moderatore

Questi messaggi sono informativi per la UI:
	•	ai.turn_started
    {
  "type": "ai.turn_started"
}

	•	ai.turn_ended
    {
  "type": "ai.turn_ended"
}

Lo stato logico corrispondente viene comunque riflesso in turn.state con state = "AI_SPEAKING".

7.4 Errori

In caso di comando non valido o non consentito, viene inviato al chiamante:
{
  "type": "turn.error",
  "code": "CONFLICT" | "FORBIDDEN" | "BAD_REQUEST",
  "detail": "Messaggio leggibile (es. 'Microfono occupato', 'Non sei lo speaker attuale', 'Prenotazione non disponibile')."
}

8. Interazione con AI / moderation (uso interno)

L’app moderation non usa il WS, ma richiede l’intervento dell’AI tramite chiamate interne (es. servizi Python o endpoint protetti).

Operazioni principali:
	•	inizio intervento AI:
	•	backend verifica che lo stato di turno è IDLE e che non esista finestra di prenotazione;
	•	se ok → imposta AI_SPEAKING e notifica via WS (ai.turn_started + turn.state).
	•	fine intervento AI:
	•	backend imposta IDLE e notifica via WS (ai.turn_ended + turn.state).

Se al momento del trigger lo stato non è IDLE o esiste una prenotazione, moderation deve attendere l’evento turn.state che segnala il ritorno a IDLE prima di avviare AI_SPEAKING.

⸻

9. Stato in Redis (vista funzionale)

Per ogni session_id, turns utilizza chiavi concettuali (nomi indicativi):
	•	turns:{session_id}:state
→ "IDLE" | "HUMAN_SPEAKING" | "AI_SPEAKING"
	•	turns:{session_id}:current_speaker_user_id
→ id utente o null
	•	turns:{session_id}:reservation_user_id
→ id prenotato o null
	•	turns:{session_id}:reservation_expires_at
→ timestamp (ISO) o null
(oppure TTL diretto su una chiave reservation)

Tutta la logica di concorrenza (due utenti che cliccano quasi insieme) viene gestita tramite operazioni atomiche Redis e/o locking applicativo nel servizio TurnManager.

⸻

10. Vincoli funzionali
	•	Microfono esclusivo: una sessione non può avere due speaker contemporaneamente.
	•	Prenotazione singola per sessione.
	•	Prenotazione possibile solo se HUMAN_SPEAKING.
	•	AI non può iniziare a parlare:
	•	se un umano sta parlando;
	•	se esiste una prenotazione in corso (finestra di priorità da rispettare).
	•	Durante AI_SPEAKING:
	•	nessun comando utente di turno viene accettato (request_speak, request_reserve, end_speak).

⸻

11. Criteri di accettazione (scenari)

Scenario A — Prenotazione usata
	1.	Utente A diventa speaker (turn.request_speak → HUMAN_SPEAKING).
	2.	Utente B chiama turn.request_reserve → prenotazione accettata.
	3.	A chiama turn.end_speak → IDLE + finestra per B.
	4.	B chiama turn.request_speak entro la finestra → diventa speaker.

Scenario B — Prenotazione non usata
	1.	A parla.
	2.	B si prenota.
	3.	A termina → finestra aperta per B.
	4.	B non chiede di parlare entro la finestra → turn.reservation_expired, stato IDLE, prenotazione cancellata.

Scenario C — AI in attesa
	1.	A parla (HUMAN_SPEAKING).
	2.	Scatta un trigger che richiede AI:
	•	moderation rileva che non è IDLE → marca “intervento AI in sospeso”.
	3.	A termina (ed eventuale prenotato usa la finestra).
	4.	Quando lo stato torna IDLE senza prenotazioni attive, moderation avvia AI_SPEAKING.
	5.	Fine intervento AI → IDLE.

⸻

12. Glossario
	•	Turno: diritto esclusivo temporaneo di parlare in una sessione.
	•	Prenotazione: richiesta di priorità per parlare subito dopo lo speaker attuale.
	•	Finestra di priorità: intervallo (circa 8 s) in cui solo il prenotato può ottenere il turno.
	•	AI moderatore: componente applicativa che genera interventi vocali automaticamente, subordinata alle regole di turns.
