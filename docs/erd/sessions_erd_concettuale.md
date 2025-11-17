ERD concettuale — Sessions (MVP)

Schema a livello concettuale (nessun tipo tecnico): entità, scopi, relazioni e vincoli funzionali.

Entità

1) Session
	•	Scopo: contenitore della stanza vocale.
	•	Attributi concettuali:
titolo, contesto, stato (LOBBY / ACTIVE / CONCLUSION / CLOSED), capienza (min/max), host, timestamp fasi (creata / avviata / conclusa / chiusa).
	•	Relazioni:
	•	Ha molti SessionParticipant.
	•	Ha molti Invitation.
	•	Ha molti SessionEvent.

2) SessionParticipant
	•	Scopo: legame utente–sessione e ruolo.
	•	Attributi concettuali:
utente, ruolo (HOST o PARTICIPANT), istante di ingresso (joined_at).
	•	Vincoli:
	•	Unicità: un utente compare al massimo una volta nella stessa sessione.
	•	L’HOST è presente fin dalla creazione della sessione.

3) Invitation
	•	Scopo: permettere l’accesso alla sessione tramite token condivisibile.
	•	Attributi concettuali:
token opaco, data creazione.
	•	Vincoli:
	•	Token riutilizzabile (nessun max_uses nel MVP).
	•	Valido solo se la sessione è in LOBBY e non piena.

4) SessionEvent (audit minimo)
	•	Scopo: registrare azioni e transizioni importanti.
	•	Attributi concettuali:
tipo evento (CREATED, INVITE_CREATED, JOINED, STARTED, CONCLUSION_AUTO, CLOSED_AUTO), attore (facoltativo), payload sintetico, timestamp.
	•	Uso: diagnostica, storico, metriche.

Relazioni (cardinalità)
	•	Session 1 — N SessionParticipant
	•	Session 1 — N Invitation
	•	Session 1 — N SessionEvent

Vincoli funzionali globali
	•	Capienza non superabile.
	•	Join possibile solo in LOBBY.
	•	Avvio sessione possibile solo in LOBBY e solo a capienza raggiunta.
	•	Transizioni finali automatiche:
ACTIVE → CONCLUSION → CLOSED (timer o evento “pronti”).