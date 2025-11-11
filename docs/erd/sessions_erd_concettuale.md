# ERD concettuale — Sessions (MVP)

> Schema a livello concettuale (nessun tipo tecnico): entità, scopi, relazioni e vincoli funzionali.

## Entità

### 1) Session
- **Scopo**: contenitore della stanza vocale.
- **Attributi concettuali**: titolo, contesto, stato (`DRAFT/LOBBY/ACTIVE/CONCLUSION/CLOSED`), capienza (min/max), host, timestamp fasi (creata/pubblicata/avviata/conclusa/chiusa).
- **Relazioni**:
  - Ha molti **SessionParticipant**.
  - Ha molti **Invitation**.
  - Ha molti **SessionEvent**.

### 2) SessionParticipant
- **Scopo**: legame utente–sessione e ruolo.
- **Attributi concettuali**: utente, ruolo (`HOST` o `PARTICIPANT`), istante di ingresso (joined_at).
- **Vincoli**:
  - Unicità: un utente può comparire **al massimo una volta** nella stessa sessione.
  - L’HOST esiste dal momento della creazione della sessione.

### 3) Invitation
- **Scopo**: permettere l’accesso in lobby tramite link condivisibile.
- **Attributi concettuali**: token opaco, istante di creazione.
- **Vincoli**:
  - Token **riutilizzabile** (nessun `max_uses` in MVP).
  - Efficace solo se la sessione è in **LOBBY** e non è piena.

### 4) SessionEvent (audit minimo)
- **Scopo**: tracciare azioni e transizioni significative.
- **Attributi concettuali**: tipo evento (es. CREATED, PUBLISHED, INVITE_CREATED, JOINED, STARTED, CONCLUSION_AUTO, CLOSED_AUTO), attore (opzionale), payload sintetico, istante di creazione.
- **Uso**: diagnostica, storico, metriche.

## Relazioni (cardinalità)
- **Session 1 — N SessionParticipant**
- **Session 1 — N Invitation**
- **Session 1 — N SessionEvent**

## Vincoli funzionali globali
- Capienza **non superabile** (nessun partecipante oltre il limite).
- Stato **coerente** con l’azione (join solo in LOBBY, avvio solo con capienza richiesta).
- Nessuna chiusura forzata: la sequenza oltre ACTIVE è **automatica** (CONCLUSION → CLOSED).
