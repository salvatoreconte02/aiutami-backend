ADR 0002 — Stati e Azioni dell’app Turns (MVP)

Contesto

AIutami gestisce sessioni vocali moderate, in cui un solo partecipante (oppure il moderatore AI) può parlare alla volta.
L’app sessions definisce il ciclo di vita della sessione (LOBBY → ACTIVE → CONCLUSION → CLOSED), ma non governa chi parla quando.
È necessario introdurre un modello chiaro per la gestione dei turni di parola (push-to-talk, prenotazioni, intervento AI), con stato condiviso e regole semplici.

Decisione

1. Stati logici del turno

Per ogni sessione attiva, il backend considera quattro stati logici:
	1.	IDLE
	•	Nessuno sta parlando.
	•	Condizioni:
	•	speaker = None
	•	ai_busy = False
	•	Significato: qualsiasi membro può provare a prendere la parola.
	2.	SPEAKING_USER
	•	Sta parlando un utente umano.
	•	Condizioni:
	•	speaker = user_id
	•	ai_busy = False
	•	Significato: solo questo utente può terminare lo speaking; al massimo un altro utente può risultare prenotato.
	3.	WINDOW_FOR_RESERVED
	•	Nessuno sta parlando, ma esiste un utente prenotato con una finestra di priorità.
	•	Condizioni:
	•	speaker = None
	•	reservation_user_id = user_id
	•	reservation_window_until nel futuro
	•	Significato: solo il prenotato può attivare il microfono entro la finestra; se non lo fa, si torna in IDLE.
	4.	SPEAKING_AI
	•	Sta parlando il moderatore AI.
	•	Condizioni:
	•	speaker = "AI"
	•	ai_busy = True
	•	Significato: nessun utente può prendere la parola o prenotarsi fino a fine intervento AI.

Lo stato logico non viene salvato come campo separato, ma si deduce dalle chiavi gestite in Redis.

⸻

2. Azioni utente

Azioni concettuali esposte dall’app turns verso il frontend:
	•	user_request_speak(session_id, user_id)
	•	user_end_speak(session_id, user_id)
	•	user_request_reserve(session_id, user_id)

Regole principali:
	•	In IDLE:
	•	user_request_speak è consentita → lo user diventa speaker (SPEAKING_USER).
	•	user_request_reserve non è consentita (prenotazione ha senso solo se qualcuno parla).
	•	In SPEAKING_USER:
	•	user_end_speak è consentita solo allo speaker attuale:
	•	se non c’è prenotato → si torna in IDLE;
	•	se c’è prenotato → si passa a WINDOW_FOR_RESERVED (finestra dedicata).
	•	user_request_reserve è consentita solo se non esiste già un prenotato.
	•	In WINDOW_FOR_RESERVED:
	•	user_request_speak è consentita solo al prenotato:
	•	se il prenotato parla → diventa speaker (SPEAKING_USER) e la prenotazione viene eliminata.
	•	user_request_reserve non è consentita.
	•	In SPEAKING_AI:
	•	Nessuna azione utente (request_speak, end_speak, request_reserve) è consentita:
	•	vengono tutte rifiutate finché l’AI sta parlando.

⸻

3. Azioni sistema / AI

Azioni concettuali interne tra moderation e turns:
	•	ai_start_speak(session_id)
	•	ai_end_speak(session_id)
	•	reservation_window_timeout(session_id) (scadenza finestra prenotato)

Regole principali:
	•	ai_start_speak è consentita solo in IDLE:
	•	se lo speaker è None, non c’è prenotato e ai_busy=False → si passa a SPEAKING_AI.
	•	se la sessione è in SPEAKING_USER o WINDOW_FOR_RESERVED → la richiesta viene rifiutata.
	•	ai_end_speak è rilevante solo in SPEAKING_AI:
	•	chiude l’intervento, ripristina speaker=None, ai_busy=False, e riporta la sessione in IDLE.
	•	reservation_window_timeout è rilevante solo in WINDOW_FOR_RESERVED:
	•	alla scadenza della finestra si cancellano prenotazione e timestamp → si torna in IDLE.

⸻

4. Ruolo di moderation / triggers

L’app turns non decide quando l’AI deve parlare; si limita a far rispettare i vincoli di stato.

Il comportamento è il seguente:
	•	Se un trigger decide che l’AI deve intervenire:
	•	se la sessione è già in IDLE → moderation invoca ai_start_speak();
	•	se la sessione non è in IDLE (utente che parla o finestra prenotato):
	•	moderation registra che l’AI ha un intervento “in sospeso”,
	•	aspetta che la sessione torni IDLE,
	•	solo allora invoca ai_start_speak().

In questo modo:
	•	turns è responsabile di stato e vincoli sui turni;
	•	moderation è responsabile di quando l’AI deve parlare.

⸻

5. Storage dello stato

Per ogni session_id, lo stato vivo dei turni è mantenuto in Redis, usando chiavi del tipo:
	•	session:{id}:speaker → None | user_id | "AI"
	•	session:{id}:reservation_user_id → None | user_id
	•	session:{id}:reservation_window_until → timestamp o None
	•	session:{id}:ai_busy → True/False

Il database relazionale (PostgreSQL) potrà essere usato in seguito per log storici dei turni, ma non è previsto come sorgente dello stato in tempo reale nell’MVP.

⸻

Conseguenze
	•	Si ottiene un modello di turni, semplice ma completo, compatibile con il push-to-talk e con una prenotazione alla volta.
	•	L’intervento dell’AI non può interrompere né lo speaking umano né la finestra di un utente prenotato: avviene solo quando il microfono è effettivamente libero.
	•	La logica di concorrenza (due utenti che premono quasi insieme) è confinata in turns, che lavora su Redis.