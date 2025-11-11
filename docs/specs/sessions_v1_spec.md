# AIutami — Specifiche funzionali Sessions (MVP, v1)

## 1. Scopo
L’app *sessions* governa il ciclo di vita di una stanza vocale moderata: dalla creazione in bozza alla lobby, all’avvio, alla conclusione e alla chiusura. Espone endpoint REST e invia eventi realtime al frontend.

## 2. Perimetro (in scope)
- Creazione sessione (bozza) e pubblicazione in lobby.
- Invito tramite link (token riutilizzabile).
- Join in lobby: l’utente diventa partecipante.
- Avvio sessione quando la capienza richiesta è raggiunta.
- Transizioni automatiche: ACTIVE → CONCLUSION → CLOSED.
- Elenchi: mie sessioni, partecipanti della sessione.
- Eventi realtime essenziali.

## 3. Fuori per l’MVP (out of scope)
- Co-host, coda o prenotazioni, “ready” utente.
- Modifica configurazioni post-creazione.
- Lascia sessione, revoca invito, scadenze/limiti inviti.
- Turni PTT, ASR, LLM/TTS (gestiti in altre app).

## 4. Stati della sessione e responsabilità
Stati ammessi: `DRAFT → LOBBY → ACTIVE → CONCLUSION → CLOSED`.

- **DRAFT → LOBBY**: azione esplicita dell’HOST (“publish”).
- **LOBBY → ACTIVE**: azione esplicita dell’HOST (“start”), precondizione: capienza richiesta raggiunta.
- **ACTIVE → CONCLUSION**: **automatica** quando tutti i partecipanti hanno premuto “Pronto alla conclusione” **oppure** scade il timer.
- **CONCLUSION → CLOSED**: **automatica** al termine della fase conclusiva.
- **Non previsto**: co-host, chiusure forzate da LOBBY/ACTIVE.

## 5. Endpoint (descrizione concettuale)
Base path: `/api/sessions/` (JWT richiesto salvo diversa nota).

1. **POST /** — Crea sessione in `DRAFT`.  
   Utente chiamante diventa HOST.

2. **GET /{id}/** — Dettaglio sessione.  
   Visibile solo a membri (HOST o PARTICIPANT).

3. **POST /{id}/publish/** — `DRAFT → LOBBY`.  
   Solo HOST; rende la sessione invitabile e joinabile.

4. **POST /{id}/start/** — `LOBBY → ACTIVE`.  
   Solo HOST; consentito solo a capienza richiesta raggiunta.

5. **POST /{id}/invitations/** — Genera link invito.  
   Solo HOST; token riutilizzabile senza `max_uses`.

6. **POST /join_by_token/** — Join tramite invito.  
   Utente autenticato + token valido; se c’è posto e stato `LOBBY`, diventa PARTICIPANT.

7. **GET /{id}/participants/** — Elenco partecipanti.  
   Solo membri della sessione.

8. **GET /mine/?state=...** — Le sessioni dell’utente.  
   Include quelle dove l’utente è HOST o PARTICIPANT.

## 6. Permessi (riassunto)
- **HOST**: creare, pubblicare, avviare, generare invito, leggere dettagli/partecipanti, vedere le proprie sessioni.
- **PARTICIPANT**: leggere dettagli/partecipanti, vedere le proprie sessioni.
- **Non membro**: nessun accesso, tranne il join via token (se autenticato).

## 7. Concorrenza e integrità (politiche)
- **Capienza non superabile**: join simultanei oltre capienza vengono respinti.
- **Unicità partecipazione**: stesso utente non può entrare due volte.
- **Avvio unico**: transizione a `ACTIVE` eseguibile una sola volta.
- **Token invito**: riutilizzabile finché lo stato è `LOBBY` e c’è posto; non esistono limiti d’uso nell’MVP.

## 8. Eventi realtime (semantica)
Canale WS per sessione, accessibile ai soli membri.
- `participant.joined`: un utente è entrato in lobby.
- `participants.list`: snapshot elenco partecipanti (emesso dopo variazioni significative).
- `session.updated`: aggiornamenti di stato/contatori.
- `session.started`: passaggio a `ACTIVE`.
- `session.conclusion`: passaggio a `CONCLUSION` (automatico).
- `session.closed`: passaggio a `CLOSED` (automatico).

## 9. Errori (tassonomia)
- **Autenticazione**: richiesto JWT.
- **Permessi**: solo membri vedono dettagli/partecipanti; solo HOST pubblica/avvia/genera inviti.
- **Vincoli**: stato non idoneo, capienza non raggiunta, token invalido, sessione piena.
- **Conflitti**: richieste concorrenti su join/avvio oltre i limiti.

## 10. Criteri di accettazione (scenari naturali)
- Creazione: l’utente crea una sessione e diventa HOST; stato `DRAFT`.
- Pubblicazione: l’HOST pubblica; stato `LOBBY`; si può generare un invito.
- Join: un utente usa un invito valido; se c’è posto e stato `LOBBY`, diventa PARTICIPANT; se la sessione è piena o non in `LOBBY`, è respinto.
- Avvio: l’HOST può avviare solo con capienza richiesta raggiunta; stato `ACTIVE`.
- Conclusione automatica: in `ACTIVE`, se tutti pronti o timer scaduto, si passa a `CONCLUSION`.
- Chiusura automatica: al termine della fase conclusiva, la sessione diventa `CLOSED`.
- Visibilità: solo membri vedono dettagli e partecipanti.

## 11. Glossario
- **HOST**: creatore e responsabile delle transizioni iniziali.
- **PARTICIPANT**: utente che ha eseguito il join in lobby.
- **Capienza richiesta**: numero minimo/fisso di partecipanti per l’avvio.
- **Invito (token)**: stringa opaca nel link che abilita il join in lobby.
