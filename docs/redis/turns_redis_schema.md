# Schema Redis — Turns (MVP)

## 1. Obiettivo

Redis mantiene lo **stato vivo** dei turni di parola per ogni sessione in stato `ACTIVE`.

Per ogni `session_id` esiste **al massimo un record logico** di turno, che descrive:

- chi sta parlando (se qualcuno),
- se esiste una prenotazione,
- se è attiva una finestra di priorità,
- una piccola `version` per proteggere da race condition.

Nessun dato di *turns* è salvato in PostgreSQL.

---

## 2. Chiave principale per sessione

Per ogni sessione:

```text
turns:{session_id}

Tipo: HASH

2.1 Campi della hash
	•	state
	•	Tipo: stringa
	•	Valori ammessi: "IDLE", "HUMAN_SPEAKING", "AI_SPEAKING"
	•	Semantica:
	•	IDLE: nessuno sta parlando.
	•	HUMAN_SPEAKING: un utente umano sta parlando.
	•	AI_SPEAKING: sta parlando il moderatore AI.
	•	current_speaker_user_id
	•	Tipo: stringa (id utente) oppure stringa vuota
	•	Valida solo se state = "HUMAN_SPEAKING".
	•	reservation_user_id
	•	Tipo: stringa (id utente) oppure stringa vuota
	•	Utente che ha diritto di priorità nella finestra di 8 secondi.
	•	reservation_expires_at
	•	Tipo: stringa timestamp (es. ISO8601) oppure stringa vuota
	•	Momento fino al quale la prenotazione è valida durante la finestra di priorità.
	•	version
	•	Tipo: stringa che rappresenta un intero ("1", "2", …)
	•	Incrementata ad ogni modifica consistente del turno.
	•	Usata per rilevare conflitti: lettura → calcolo nuovo stato → scrittura solo se version non è cambiata.

Eventuali campi aggiuntivi (es. ai_busy) saranno valutati in futuro; l’MVP si basa solo su quelli sopra.

⸻

3. Invarianti

Per ogni turns:{session_id}:
	1.	state è sempre uno dei valori ammessi (IDLE / HUMAN_SPEAKING / AI_SPEAKING).
	2.	Se state = "HUMAN_SPEAKING":
	•	current_speaker_user_id è valorizzato a un id utente non vuoto.
	3.	Se state != "HUMAN_SPEAKING":
	•	current_speaker_user_id è vuoto.
	4.	Se esiste una finestra di priorità attiva:
	•	state = "IDLE",
	•	reservation_user_id non è vuoto,
	•	reservation_expires_at è un timestamp futuro (o almeno non scaduto).
	5.	Se non esiste prenotazione:
	•	reservation_user_id è vuoto,
	•	reservation_expires_at è vuoto.
	6.	version è sempre un intero ≥ 1 (come stringa).

⸻

4. Ciclo di vita dei campi (semplificato)

4.1 Inizializzazione (sessione entra in ACTIVE)

Quando una sessione passa da LOBBY a ACTIVE, l’app turns inizializza:
HSET turns:{session_id} \
  state "IDLE" \
  current_speaker_user_id "" \
  reservation_user_id "" \
  reservation_expires_at "" \
  version "1"

  4.2 Inizio speaking umano

Condizioni (verificate dal servizio applicativo):
	•	state = "IDLE";
	•	oppure state = "IDLE" con finestra attiva e il chiamante è reservation_user_id.

Effetto:
	•	state = "HUMAN_SPEAKING"
	•	current_speaker_user_id = <id chiamante>
	•	eventuale prenotazione precedente (se consumata) viene azzerata:
	•	reservation_user_id = ""
	•	reservation_expires_at = ""
	•	version incrementata (N → N+1)

4.3 Fine speaking umano

Condizioni:
	•	state = "HUMAN_SPEAKING",
	•	current_speaker_user_id = <id chiamante>.

Effetto base:
	•	state = "IDLE"
	•	current_speaker_user_id = ""

Se esiste un utente prenotato (prenotazione già impostata durante lo speaking):
	•	si calcola una finestra di priorità (es. 8 secondi):
	•	reservation_expires_at = now + 8s
	•	(facoltativa: logica di scadenza pigra vs attiva)

Se non esiste prenotato:
	•	reservation_user_id = ""
	•	reservation_expires_at = ""

In tutti i casi:
	•	version incrementata (N → N+1).

4.4 Prenotazione

Condizioni:
	•	state = "HUMAN_SPEAKING",
	•	reservation_user_id è vuoto,
	•	il chiamante non è current_speaker_user_id.

Effetto:
	•	reservation_user_id = <id chiamante>
	•	reservation_expires_at per ora vuoto; verrà valorizzato solo alla fine dello speaking.
	•	version incrementata.

4.5 Finestra di priorità

Quando lo speaker termina (vedi 4.3) e reservation_user_id non è vuoto:
	•	state = "IDLE"
	•	reservation_expires_at = now + 8s

In questo intervallo:
	•	solo reservation_user_id può ottenere HUMAN_SPEAKING.

Se arriva una richiesta di parlare:
	•	se ora > reservation_expires_at:
	•	la prenotazione viene cancellata:
	•	reservation_user_id = ""
	•	reservation_expires_at = ""
	•	e ci si comporta come in un semplice IDLE libero.

4.6 Speaking AI

Condizioni per l’avvio (decide il backend di moderazione):
	•	state = "IDLE",
	•	reservation_user_id vuoto (nessuna priorità da servire).

Effetto:
	•	state = "AI_SPEAKING"
	•	current_speaker_user_id = ""
	•	version incrementata.

Alla fine dell’intervento AI:
	•	state = "IDLE"
	•	version incrementata.

⸻

5. Cleanup

Quando la sessione passa a CLOSED (e/o dopo un certo tempo):
	•	si può eliminare la chiave:
    DEL turns:{session_id}

	•	oppure impostare un TTL (auto-scadenza dopo N minuti):
    EXPIRE turns:{session_id} N

 La decisione su DEL vs EXPIRE è tecnica e può essere presa in fase di implementazione.

⸻

6. Uso previsto da parte dell’applicazione

Tutta la logica di lettura/scrittura di queste hash viene centralizzata in un servizio applicativo (es. TurnManager), che:
	1.	legge lo stato attuale dalla hash (compresa version);
	2.	applica le regole di dominio;
	3.	aggiorna i campi nella hash, incrementando version;
	4.	in caso di conflitto di version, ripete la lettura e rivaluta (o restituisce errore di conflitto);
	5.	notifica via WebSocket i cambiamenti di stato.

Nessuna altra parte del codice dovrebbe manipolare direttamente Redis per lo stato dei turni.   