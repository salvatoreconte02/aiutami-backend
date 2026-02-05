Di seguito è riportato un riassunto strutturato e neutrale dei contenuti affrontati nella tesi, pensato per essere utilizzabile come base di riferimento teorica e metodologica nella scrittura del progetto che ne deriva.

⸻

Riassunto della tesi

“Multiuser Conversational Agents Based on Large Language Models” – Francesco Dubini (2023–2024)  ￼

Obiettivo della tesi

La tesi analizza il ruolo dei Large Language Models (LLM) all’interno di conversazioni multi-utente, con particolare attenzione alla possibilità di utilizzare un chatbot basato su LLM come moderatore artificiale nelle discussioni di gruppo.
L’obiettivo principale è studiare come la presenza di un moderatore IA influenzi le dinamiche sociali, la partecipazione e i processi decisionali, senza perseguire l’ottimizzazione di un moderatore “perfetto”, ma concentrandosi su una valutazione sperimentale di un approccio di base.

⸻

Domanda di ricerca

La tesi ruota attorno a una domanda centrale:

In che modo l’introduzione di un moderatore artificiale basato su LLM modifica le dinamiche di interazione e il processo decisionale in una conversazione multi-utente?

⸻

Contesto teorico e stato dell’arte

Il lavoro si colloca nell’ambito della Human-Computer Interaction (HCI) e della Human-AI Interaction, evidenziando come la maggior parte della letteratura sui chatbot sia storicamente focalizzata su interazioni uno-a-uno.
Viene sottolineata la scarsità di studi su chatbot generativi in contesti multi-utente, soprattutto per quanto riguarda il ruolo di moderazione automatica.

La tesi analizza:
	•	tipologie di chatbot (rule-based, generativi, ibridi);
	•	tecniche di moderazione già esplorate in letteratura (timer, regole, chiamata diretta);
	•	limiti delle metriche qualitative comunemente utilizzate per valutare i moderatori IA.

⸻

Metodo sperimentale

Lo studio sperimentale è basato sulla digitalizzazione di un esperimento classico di psicologia sociale (Stasser & Stewart) fondato sul paradigma dell’Hidden Profile.

Task sperimentale
	•	I partecipanti affrontano un murder mystery.
	•	Ogni gruppo è composto da 3 persone, ciascuna con informazioni parziali e uniche.
	•	Solo attraverso una discussione efficace è possibile individuare il colpevole corretto.

Condizioni sperimentali
	1.	Condizione di controllo: discussione senza moderatore IA.
	2.	Condizione sperimentale: discussione con moderatore IA basato su GPT-3.5.

Obiettivo del confronto
Valutare differenze tra le due condizioni in termini di:
	•	accuratezza della decisione finale;
	•	quantità e qualità delle informazioni condivise;
	•	focalizzazione sui dati critici;
	•	equilibrio della partecipazione;
	•	durata e struttura della discussione.

⸻

Implementazione tecnica

La tesi descrive in dettaglio:
	•	l’architettura web (Django + frontend JavaScript);
	•	la gestione asincrona delle chiamate al modello LLM;
	•	il design del sistema di moderazione per evitare interventi ripetuti o incoerenti;
	•	le scelte di prompt engineering, con iterazioni successive per definire:
	•	quando il moderatore deve intervenire;
	•	come intervenire senza risultare invasivo;
	•	come mantenere un comportamento generale e task-agnostico.

⸻

Risultati principali

I risultati mostrano che:
	•	La presenza del moderatore IA non migliora in modo significativo l’accuratezza della decisione finale.
	•	Il moderatore influenza parzialmente la struttura della conversazione e la partecipazione, ma:
	•	non aumenta in modo statisticamente significativo la condivisione di informazioni critiche;
	•	non migliora il focus della discussione;
	•	non garantisce un maggiore equilibrio tra i partecipanti.
	•	L’efficacia del moderatore è fortemente condizionata dalla qualità e motivazione dei partecipanti, soprattutto in contesti online.

⸻

Limiti individuati

La tesi evidenzia diversi limiti rilevanti:
	•	bassa motivazione dei partecipanti reclutati online;
	•	difficoltà di un moderatore task-agnostico, che può suggerire azioni non realistiche;
	•	problemi dovuti a filtri di contenuto del provider LLM;
	•	assenza di metriche standard consolidate per valutare la moderazione IA multi-utente.

⸻

Conclusioni e contributo

Il contributo principale della tesi non risiede nei risultati quantitativi, ma in:
	•	una analisi metodologica dettagliata della moderazione IA multi-utente;
	•	una sistematizzazione delle scelte di design e dei problemi emersi;
	•	la definizione di una baseline sperimentale utile per studi futuri.

La tesi conclude che la moderazione tramite LLM è promettente, ma richiede maggiore contestualizzazione del task, migliori metriche e partecipanti più coinvolti per esprimere il proprio potenziale.

