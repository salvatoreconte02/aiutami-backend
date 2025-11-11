# ADR 0001 — Stati e Transizioni dell’app Sessions (MVP)

- **Stato**: ACCETTATA
- **Data**: (inserire data approvazione)

## Contesto
AIutami gestisce sessioni vocali moderate. È necessario uno schema di stati semplice, prevedibile e coerente con l’MVP, che imponga chi può eseguire le transizioni e quando.

## Decisione
1. Stati ammessi: `DRAFT → LOBBY → ACTIVE → CONCLUSION → CLOSED`.
2. Responsabilità transizioni:
   - `DRAFT → LOBBY`: solo HOST (pubblicazione).
   - `LOBBY → ACTIVE`: solo HOST (avvio), **solo** quando la capienza richiesta è raggiunta.
   - `ACTIVE → CONCLUSION`: **automatica** quando tutti i partecipanti sono “pronti alla conclusione” **oppure** scade il timer.
   - `CONCLUSION → CLOSED`: **automatica** al termine della fase conclusiva.
3. Non sono previsti co-host né chiusure forzate in LOBBY/ACTIVE.
4. L’invito è un token riutilizzabile: l’accesso è regolato dallo stato (`LOBBY`) e dalla capienza disponibile.

## Conseguenze
- Frontend e backend hanno confini netti: l’HOST controlla solo le prime due transizioni; il resto è guidato da eventi.
- Gli endpoint sono meno numerosi e più chiari; la logica di concorrenza si concentra su join e avvio.
- Il debugging degli stati è facilitato grazie all’audit minimo.

## Alternative considerate
- **Co-host**: scartato per semplicità MVP.
- **Chiusura forzata in LOBBY/ACTIVE**: scartata; la chiusura deve riflettere lo svolgimento naturale (consenso o timer).
- **Inviti con limiti/scadenze**: scartato per MVP; si demanda a versioni successive.

## Rischi e mitigazioni
- **Rischio**: blocco in ACTIVE se qualcuno non preme “pronto” e il timer non scade.  
  **Mitigazione**: definire una policy di timer chiara e comunicarla nella UI.
- **Rischio**: corsa al join in lobby.  
  **Mitigazione**: politiche di integrità (capienza non superabile, unicità partecipazione).
- **Rischio**: ambiguità sugli eventi automatici.  
  **Mitigazione**: specifiche funzionali e audit che registrino trigger e transizioni.

## Stato futuro
Le estensioni (co-host, revoche/scadenze inviti, stati intermedi) potranno essere introdotte con ADR dedicate senza impattare l’impianto di base.
