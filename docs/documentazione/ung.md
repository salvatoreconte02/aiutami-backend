

1) Stakeholders

Sono suddivisi in tre livelli, in base alla prossimità d’uso e responsabilità:
	•	Primary users: studenti, ricercatori, colleghi di docenti, membri di community; partecipanti a contesti educativi o terapeutici; partecipanti a contesti di intrattenimento.
	•	Secondary users: docenti, manager, terapeuti, moderatori o team leader che supervisionano le conversazioni.
	•	Tertiary users: istituzioni educative o aziendali, HR, community manager.

2) Needs (Bisogni)

Raccolgono ciò che gli utenti (soprattutto primari, ma anche i secondari) si aspettano dall’esperienza:
	•	Sentirsi ascoltati e inclusi
	•	Partecipare con sicurezza
	•	Comunicare in modo chiaro e fluido
	•	Mantenere il focus e la produttività della discussione
	•	Promuovere inclusione e collaborazione sociale
	•	Ottenere strumenti per osservare e migliorare la comunicazione
	•	Garantire etica, privacy e trasparenza dei dati

3) Context (Contesto)

Descrive dove e come avviene l’interazione, articolata in quattro dimensioni:
	•	Organizational: durante lezioni/workshop o gruppi di studio; in riunioni di lavoro (brainstorming, co-design); in contesti terapeutici o di gruppo (training comunicativi).
	•	Physical: ambienti indoor o digitali che supportano interazioni vocali; piattaforme online (es. Discord); spazi VR o ambienti immersivi; aule, sale riunioni, laboratori; studi terapeutici. Include requisiti infrastrutturali: microfoni/ headset, connessione stabile (indicata come ~10 Mbps), bassa latenza di rete (indicata come ≤200 ms).
	•	Temporal: uso in tempo reale per monitorare/intervenire vocalmente durante la conversazione; uso post-sessione per generare resoconti o sintesi vocali dopo la discussione.
	•	Social: piccoli o medi gruppi (circa 3–10 persone).

4) Goals (Obiettivi del sistema)

Sono gli obiettivi funzionali che il sistema dovrebbe raggiungere per soddisfare i bisogni:
	•	Gestire in modo fluido i turni di parola vocali
	•	Riconoscere automaticamente i partecipanti
	•	Fornire feedback vocali in tempo reale
	•	Riassumere oralmente i punti principali della conversazione
	•	Monitorare i livelli di partecipazione
	•	Gestire i dati audio in modo sicuro

5) Constraints (Vincoli)

Evidenziano i principali fattori che possono limitare prestazioni e progettazione:
	•	Latenza nella catena ASR–LLM–TTS (riconoscimento vocale → modello linguistico → sintesi vocale)
	•	Riconoscimento vocale non sempre accurato
	•	Policy di moderazione dei contenuti
	•	Limitazioni del modello LLM
	•	Trattamento dei dati vocali (privacy, conservazione, sicurezza, conformità)

Lettura complessiva

Il grafo mostra un flusso logico: dagli stakeholders emergono i bisogni; questi orientano i goals del sistema; i vincoli e il contesto definiscono ciò che è realisticamente ottenibile (ad es. latenza e accuratezza influenzano soprattutto gestione dei turni, feedback in tempo reale e riconoscimento dei partecipanti; privacy e trattamento dei dati incidono sulla gestione sicura dell’audio e sulle funzionalità di monitoraggio/sintesi).

