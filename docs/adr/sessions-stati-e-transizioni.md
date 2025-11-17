ADR 0001 — Stati e Transizioni dell’app Sessions (MVP)
	•	Stato: ACCETTATA
	•	Data: (inserire data approvazione)

Contesto

AIutami gestisce sessioni vocali moderate. È necessario definire un ciclo di vita semplice e prevedibile, compatibile con l’MVP e con il modello operativo concordato, in cui la sessione risulta immediatamente predisposta all’ingresso dei partecipanti.

Decisione
	1.	Stati ammessi: LOBBY → ACTIVE → CONCLUSION → CLOSED.
	2.	Responsabilità delle transizioni:
	•	LOBBY → ACTIVE: esclusivamente HOST, e solo quando la capienza prevista è raggiunta.
	•	ACTIVE → CONCLUSION: automatica, sulla base delle condizioni definite dal servizio applicativo (completamento attività, esito logico o timer).
	•	CONCLUSION → CLOSED: automatica al termine della fase conclusiva.
	3.	L’accesso tramite invito è consentito solo in LOBBY, nel rispetto della capienza.
	4.	Non sono previsti stati intermedi né ruoli aggiuntivi nel ciclo di vita.

Conseguenze
	•	La creazione di una sessione produce direttamente lo stato LOBBY, eliminando la precedente fase di bozza.
	•	La responsabilità dell’HOST si concentra esclusivamente sull’avvio della sessione; tutte le fasi successive sono determinate dal sistema.
	•	L’architettura degli endpoint risulta più compatta e meno soggetta a errori di sincronizzazione.
	•	L’audit degli eventi consente la ricostruzione del ciclo di vita con minore complessità operativa.

Alternative considerate
	•	Introduzione di uno stato DRAFT: eliminato perché ridondante rispetto alle esigenze attuali.
	•	Co-host e privilegi aggiuntivi: rinviato a versioni successive per evitare complessità non necessarie nell’MVP.
	•	Inviti con limiti o scadenza: esclusi in questa fase; la gestione rimane volutamente minimale.

Rischi e mitigazioni
	•	Rischio: permanenza prolungata in ACTIVE in assenza delle condizioni di conclusione.
Mitigazione: utilizzo di timer e trigger applicativi chiari, documentati e verificabili.
	•	Rischio: saturazione rapida della capienza in LOBBY.
Mitigazione: applicazione rigorosa delle politiche di integrità e unicità partecipazione.
	•	Rischio: ambiguità nella gestione degli eventi automatici.
Mitigazione: definizione puntuale dei trigger e audit strutturato.

Stato futuro

Elementi come co-host, revoche di inviti, stati aggiuntivi o logiche avanzate di moderazione potranno essere introdotti tramite ADR dedicate senza modificare la struttura definita.