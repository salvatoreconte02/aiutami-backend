AIutami — Specifiche funzionali Sessions (MVP, v1)

1. Scopo

L’app sessions governa il ciclo di vita di una stanza vocale moderata: dalla creazione alla lobby, all’avvio, alla conclusione e alla chiusura. Espone endpoint REST e invia eventi realtime al frontend.

2. Perimetro (in scope)
	•	Creazione sessione in LOBBY.
	•	Invito tramite link (token riutilizzabile).
	•	Join in lobby: l’utente diventa partecipante.
	•	Avvio sessione quando la capienza richiesta è raggiunta.
	•	Transizioni automatiche: ACTIVE → CONCLUSION → CLOSED.
	•	Elenchi: mie sessioni, partecipanti della sessione.
	•	Eventi realtime essenziali.

3. Fuori per l’MVP (out of scope)
	•	Co-host, coda o prenotazioni, “ready” utente.
	•	Modifiche configurazioni post-creazione.
	•	Lascia sessione, revoca invito, scadenze/limiti inviti.
	•	Turni PTT, ASR, LLM/TTS (gestiti in altre app).

4. Stati della sessione e responsabilità

Stati ammessi:
LOBBY → ACTIVE → CONCLUSION → CLOSED.
	•	Creazione → LOBBY: avviene automaticamente alla creazione (nessuna bozza).
	•	LOBBY → ACTIVE: azione esplicita dell’HOST (“start”).
Precondizione: capienza richiesta raggiunta.
	•	ACTIVE → CONCLUSION: automatica quando scade il timer o condizioni definite dal sistema.
	•	CONCLUSION → CLOSED: automatica al termine della fase conclusiva.
	•	Non previsto: co-host, chiusure forzate da LOBBY/ACTIVE.

5. Endpoint (descrizione concettuale)

Base path: /api/sessions/ (JWT richiesto salvo diversa indicazione).

1. POST /

Crea una nuova sessione in LOBBY.
L’utente chiamante diventa HOST.

2. GET /{id}/

Dettaglio sessione.
Visibile solo a membri (HOST o PARTICIPANT).

3. POST /{id}/start/

Transizione LOBBY → ACTIVE.
Solo HOST; consentito solo a capienza richiesta raggiunta.

4. POST /{id}/invitations/

Genera link invito.
Solo HOST; token riutilizzabile senza limiti in MVP.

5. POST /join_by_token/

Join tramite invito.
Utente autenticato + token valido; se c’è posto e stato LOBBY, diventa PARTICIPANT.

6. GET /{id}/participants/

Elenco partecipanti.
Accessibile solo ai membri.

7. GET /mine/?state=…

Lista delle sessioni a cui l’utente partecipa o che ospita.
Filtro opzionale per stato.

6. Permessi (riassunto)
	•	HOST: creare, avviare, generare inviti, leggere dettagli/partecipanti, vedere le proprie sessioni.
	•	PARTICIPANT: leggere dettagli/partecipanti, vedere le proprie sessioni.
	•	Non membro: nessun accesso, tranne join via token.

7. Concorrenza e integrità (politiche)
	•	Capienza non superabile: join oltre capienza viene respinto.
	•	Unicità partecipazione: stesso utente non può unirsi due volte.
	•	Avvio unico: transizione ad ACTIVE eseguibile una sola volta.
	•	Token invito: riutilizzabile finché la sessione è in LOBBY e non è piena.

8. Eventi realtime (semantica)

Canale WS per sessione, accessibile ai soli membri.
	•	participant.joined
	•	participants.list
	•	session.updated
	•	session.started
	•	session.conclusion
	•	session.closed

9. Errori (tassonomia)
	•	Autenticazione: JWT mancante o non valido.
	•	Permessi: azioni riservate a HOST, dettagli riservati ai membri.
	•	Vincoli: stato non idoneo, capienza non raggiunta, token invalido.
	•	Conflitti: join simultanei oltre limite; avvio ripetuto.

10. Criteri di accettazione (scenari naturali)
	•	Creazione: l’utente crea una sessione → stato iniziale LOBBY.
	•	Inviti: l’HOST può generare inviti mentre è in LOBBY.
	•	Join: se token valido e posto disponibile, l’utente entra come PARTICIPANT.
	•	Avvio: l’HOST avvia solo quando la capienza richiesta è raggiunta → stato ACTIVE.
	•	Conclusione automatica: in ACTIVE, il sistema passa a CONCLUSION secondo le regole stabilite.
	•	Chiusura automatica: al termine, la sessione diventa CLOSED.
	•	Visibilità: solo membri possono accedere ai dettagli e all’elenco partecipanti.

11. Glossario
	•	HOST: creatore della sessione, responsabile dell’avvio.
	•	PARTICIPANT: utente che ha fatto join in lobby.
	•	Capienza richiesta: numero minimo/fisso per l’avvio.
	•	Token invito: stringa opaca che abilita il join.