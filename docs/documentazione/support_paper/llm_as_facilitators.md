

Riassunto del paper

“Large Language Models as Facilitators in Multi-user Conversations: A Mixed Method Study” (CHI 2026)  ￼

⸻

Obiettivo del lavoro

Il paper studia l’effetto di un facilitatore basato su Large Language Models nelle conversazioni multi-utente orientate al decision making collaborativo.
L’obiettivo principale è valutare se e come un facilitatore LLM, progettato in modo minimalista tramite solo prompt engineering, influenzi:
	•	l’accuratezza delle decisioni;
	•	la qualità del ragionamento collettivo;
	•	le dinamiche sociali e partecipative del gruppo.

⸻

Contesto teorico

Il lavoro si colloca nell’ambito della Human-Computer Interaction e della ricerca sui processi decisionali di gruppo, evidenziando come:
	•	la letteratura sui chatbot si concentri prevalentemente su interazioni diadiche;
	•	i sistemi di moderazione tradizionali siano spesso rigidi e rule-based;
	•	i LLM offrano nuove opportunità di facilitazione flessibile e contestuale, ma con effetti sociali ancora poco compresi.

Il paper si fonda sul paradigma del Hidden Profile, ampiamente studiato in psicologia sociale, che dimostra come i gruppi tendano a discutere informazioni condivise trascurando quelle uniche e decisive.

⸻

Metodo sperimentale

Lo studio adotta un disegno sperimentale mixed-method con 20 gruppi da tre partecipanti (N = 60).

Task
	•	Risoluzione collaborativa di un murder mystery.
	•	Ogni partecipante possiede informazioni parziali e uniche.
	•	La soluzione corretta è ottenibile solo tramite condivisione efficace delle informazioni.

Condizioni sperimentali
	1.	No-Facilitator: discussione libera senza interventi IA.
	2.	Facilitator: discussione supportata da un LLM-facilitator che interviene proattivamente.

⸻

Implementazione del facilitatore

Il facilitatore è implementato come servizio web basato su GPT-4o, integrato in una piattaforma Django.

Caratteristiche principali:
	•	approccio minimalista, senza moduli esterni di memoria o stato;
	•	interventi regolati da vincoli espliciti (off-topic, monopolizzazione, conflitti);
	•	politica di intervento limitato (massimo un intervento ogni tre turni);
	•	assenza di accesso diretto ai contenuti del task, per evitare che l’IA risolva il problema.

⸻

Risultati quantitativi

I risultati mostrano che:
	•	i partecipanti nella condizione Facilitator ottengono una accuratezza individuale significativamente più alta nella decisione finale rispetto alla condizione di controllo;
	•	l’effetto è significativo a livello individuale, ma non a livello di consenso di gruppo;
	•	la presenza del facilitatore non aumenta la fiducia soggettiva nella decisione, ma rende la discussione percepita come costruttiva anche in caso di errore.

⸻

Risultati qualitativi

L’analisi tematica individua quattro funzioni principali del facilitatore:
	1.	Regolazione delle dinamiche conversazionali
	•	bilanciamento della partecipazione;
	•	mantenimento del focus sul task;
	•	chiarificazione di incomprensioni.
	2.	Guida task-specific
	•	promozione di ragionamento basato su evidenze;
	•	introduzione spontanea di strutture cognitive (motive, opportunità, alibi);
	•	supporto alla sintesi delle informazioni.
	3.	Promozione del consenso e riduzione dei bias
	•	contrasto a ipotesi speculative;
	•	riduzione di ancoraggio e pregiudizi narrativi;
	•	incoraggiamento alla revisione delle convinzioni iniziali.
	4.	Gestione del tempo e dell’ordine
	•	strutturazione sequenziale dell’analisi dei sospetti;
	•	sollecitazione alla conclusione;
	•	creazione di senso di urgenza, talvolta prematuro.

⸻

Limiti individuati

Il paper evidenzia diversi limiti:
	•	occasionali allucinazioni del facilitatore;
	•	rischio di pressione temporale anticipata;
	•	ambiguità nel grado di utilizzo percepito del facilitatore;
	•	difficoltà nel bilanciare profondità del ragionamento e raggiungimento del consenso.

Inoltre, i partecipanti tendono a trattare il facilitatore come strumento di supporto, non come interlocutore attivo.

⸻

Contributo rispetto alla letteratura

Il contributo principale del lavoro consiste nel:
	•	dimostrare empiricamente che anche un facilitatore LLM “out-of-the-box” può migliorare il decision making individuale;
	•	fornire un’analisi approfondita delle strategie emergenti di facilitazione;
	•	mostrare che molte capacità di facilitazione derivano dalla conoscenza pre-addestrata del modello, non solo dal prompt.

