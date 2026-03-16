# Understanding Computational Dialogue Understanding

- **Autori**: Wahlster, Wolfgang
- **Anno**: 2023 (ricevuto Feb 2023, accettato Mar 2023)
- **Fonte**: Philosophical Transactions of the Royal Society A, Vol. 381, 20220049
- **DOI**: 10.1098/rsta.2022.0049
- **Citazioni**: 20
- **Pagine**: 20
- **Affiliazione**: DFKI - German Research Center for Artificial Intelligence, Berlino

## Tipo di paper

**Review/retrospettiva** di 5 decenni di sistemi di dialogo (1976-2026), scritta da uno dei pionieri del campo. Non e un paper empirico con esperimenti, ma una panoramica storica e architetturale con principi di design e sfide future. Parte della discussion meeting issue "Cognitive Artificial Intelligence" della Royal Society.

## Tesi principale

Il dialogue understanding e **AI-complete**: un sistema non puo raggiungere un comportamento dialogico human-like senza possedere molte altre competenze cognitive (visione, ragionamento, planning, apprendimento, user modeling, knowledge representation). Gli LLM attuali sono "super-parrots" -- producono testo indistinguibile dall'umano ma mancano di rappresentazione esplicita dell'intento comunicativo, grounding fisico e capacita metacognitive.

## Evoluzione storica dei sistemi di dialogo (Figure 3)

### Decennio per decennio

| Periodo | Paradigma | Sistemi esempio |
|---------|-----------|-----------------|
| 1976-1986 | Closed-domain dialogue systems | HAM-RPM, HAM-ANS |
| 1986-1996 | Perceptually grounded + multimodal | VITRA, XTRA |
| 1996-2006 | Speech-to-speech translation, embodied dialogue, conversational characters | VERBMOBIL, SMARTKOM, MSA |
| 2006-2016 | Open-domain, empathic virtual agents, multiparty dialogue | SMARTWEB, THESEUS, VIRTUAL HUMAN |
| 2016-2026 | Massively multimodal, hybrid team interaction, LLM-based chatbots | MADMACS, HYSOCIATEA, OpenGPT-X |

### Sistemi chiave descritti

**SHRDLU (1972, Winograd)**: primo closed-domain dialogue system. BLOCKS world. Completamente simbolico, nessun ML. Poteva risolvere anafore, chiedere chiarimenti, spiegare le proprie azioni. Ma non robusto, non scalabile.

**HAM-RPM/HAM-ANS (1978-1983)**: domain-independent, "transmutable" -- adattabili a domini, tipi di dialogo e utenti diversi. HAM-ANS poteva switchare tra modalita cooperativa e persuasiva.

**XTRA (1986)**: multimodale (linguaggio naturale + pointing gestuale). Interfaccia per sistema esperto fiscale. Gestiva deixis con diverse granularita.

**VITRA**: perceptually grounded -- traduce output di analisi visiva in descrizioni linguistiche. Reporter di partite di calcio. "One word says more than a thousand pictures".

**SMARTKOM (1996-2006)**: primo sistema multimodale per dispositivi mobili. Agente embodied "Smartakus". Copre: mutual disambiguation of modalities, multi-modal deixis/reference/anaphora/ellipsis resolution, **multi-modal turn-taking and backchannelling**.

**VERBMOBIL**: speech-to-speech translation bidirezionale per 4 lingue. Multi-blackboard architecture con 5 thread di processing concorrenti (da shallow end-to-end ML a deep semantic transfer). Ogni risultato ha un confidence value. Task-completion rate 90%. Genera summary multilingue dalla dialogue memory.

**SMARTWEB**: open-domain, combina knowledge graphs + web search + information extraction. Capacita introspettive (previsione tempo di risposta e confidence level).

**VIRTUAL HUMAN**: **sistema multiparty** con 3 agenti virtuali (1 moderatore + 2 esperti) e 2 umani in un quiz sportivo. Agent-based dialogue management platform. Multi-modal turn-taking + emotional involvement in controversial group discussions. Ogni personaggio ha ruolo, obiettivi dialogici dinamici, stato affettivo che cambia durante l'interazione.

**MADMACS/SiAM-dp**: massively multimodal (fino a 9 modalita diverse). System-environment interaction per smart environments.

**HYSOCIATEA**: hybrid teams (umani + cobot + softbot) in Industry 4.0. Spoken multi-modal dialogue per task allocation. Multi-agent architecture con blackboard per dialogue management.

## LLM: Super-Parrots o comprensione human-like? (Sezione 3)

### Argomenti a favore degli LLM
- Output spesso indistinguibile da testo umano
- Rispondono rapidamente, enabling fluent dialogue
- Gestiscono follow-up questions, ammettono errori, challenge premesse scorrette
- Ban ICML 2023 come prova indiretta della qualita formale dell'output

### Argomenti critici ("super-parrots")
- **Nessuna rappresentazione esplicita dell'intento comunicativo**
- **Grounding fisico molto limitato**
- **Capacita metacognitive e introspettive limitate**
- LaMDA addestrato su 1.56 trilioni di parole -- e un pappagallo con vocabolario enorme
- **Hallucination**: inventano fatti, non possono verificarli
- **Discourse memory limitata**: ~3000 parole nella conversazione corrente
- **Non chiedono clarification questions** per ambiguita (dimostrato con PP-attachment ambiguity)
- Metacomunicazione supportata ma spiegazioni non convincenti

### Confronto LLM vs cervello umano
- Cervello: 86 miliardi di neuroni, ~7000 connessioni sinaptiche ciascuno = ~100 trilioni di sinapsi
- PaLM: 540 miliardi di parametri -- molto meno delle sinapsi umane
- Cervello: 20 Watt. LLM: costi di training enormi ($12M+ per GPT-3)
- Elaborazione linguistica nel cervello: moduli cascati e paralleli (acustica <100ms, semantica/sintassi 300-500ms, integrazione >600ms)
- Le architetture transformer end-to-end non riflettono la struttura modulare del cervello

## Principi architetturali (Sezione 4)

### 1. Symmetric Multi-Modality
Tutte le modalita di input (speech, gesti, espressioni facciali) devono essere disponibili anche per l'output, e viceversa. Il sistema deve rappresentare non solo l'input dell'utente ma anche il **proprio output** per poter gestire riferimenti anaforici, cross-modali e gestuali nei turni successivi.

**Multi-modal fusion**: combina output dei componenti di analisi modality-specific in una rappresentazione interna del dialogue act.
**Multi-modal fission**: funzionalita inversa -- alloca generatori modality-specific ai segmenti dell'atto comunicativo e sincronizza l'output.

Principio: **"No presentation without representation"** -- il sistema deve avere una rappresentazione simbolica di tutto cio che presenta, altrimenti non puo gestire riferimenti futuri.

### 2. Anticipation Feedback Loops (Figure 9)
Ciclo di controllo per generazione user-adaptive:
1. Intenzione comunicativa s1
2. Componente di generazione produce planned utterance
3. Componente di analisi (con dialogue partner model) interpreta l'utterance pianificata
4. Genera interpretazione anticipata s2
5. Confronta s1 ≈ s2?
6. Se SI -> realizza l'utterance. Se NO -> revisione e rigenera.

Basato sull'assunzione di similarita: le procedure di analisi del sistema sono simili a quelle dell'utente. Usato per generazione di ellissi, anafore, espressioni deittiche, descrizioni spaziali, parafrasi.

## 7 trend di ricerca futuri

1. Da **closed-domain** a **open-domain**
2. Da **single-initiative** a **mixed-initiative**
3. Da **unimodal** a **multi-modal**
4. Da **single-task** a **multi-task**
5. Da **monolingual** a **multi-lingual**
6. Da **dyadic** a **multi-party** conversations
7. Da **emotionless** a **emotionally charged** conversations

Plus 2 trend metodologici:
- Da **black-box** a **transparent/explainable** dialogue systems
- Da metodi puramente **simbolici o neurali** a **hybrid neuro-symbolic**

## Massime conversazionali di Grice

Wahlster collega le metriche di qualita dei moderni LLM alle massime di Grice:
- **Quantita** (be informative) ~ Interestingness di LaMDA
- **Qualita** (be truthful) ~ Safety/factuality
- **Relazione** (be relevant) ~ Sensibleness di LaMDA
- **Maniera** (be clear) ~ Specificity di LaMDA

LaMDA usa classificatori SSI (Sensibleness, Specificity, Interestingness) per rankare le risposte candidate -- approssimazione delle massime di Grice.

## Limiti del paper

- **Review personale**: basata principalmente sui progetti dell'autore (tutti tedeschi/DFKI), non una survey sistematica
- **Nessun esperimento o dati nuovi**: e una retrospettiva con opinioni esperte
- **Focus su sistemi pre-2023**: ChatGPT analizzato nella versione di Gennaio 2023 (pre-GPT-4, pre-multimodalita)
- Non copre le architetture speech-to-speech end-to-end piu recenti (Whisper, AudioPaLM, etc.)
- Non approfondisce i sistemi multiparty contemporanei basati su LLM
- Focus europeo/tedesco -- poca copertura di sistemi asiatici o nordamericani
- Il concetto di "AI-completeness" non e formalizzato
- Nessuna discussione su turn-taking computazionale o VAD/VAP

## Rilevanza per la tesi

**Media**. Questo paper non e direttamente confrontabile con AIutami, ma fornisce un contesto storico e principi architetturali importanti per la tesi.

### 1. Contesto storico per il Related Work
La timeline di Wahlster (Figure 3) posiziona i multiparty dialogue systems nel periodo 2006-2016, con l'evoluzione verso LLM-based chatbots nel 2016-2026. AIutami si colloca esattamente nell'intersezione di queste due ere: e un **multiparty dialogue system basato su LLM**.

### 2. VIRTUAL HUMAN come precursore
Il sistema VIRTUAL HUMAN (2006) e un precursore concettuale di AIutami:
- Entrambi hanno un **moderatore AI** + partecipanti umani
- Entrambi gestiscono **multi-modal turn-taking**
- Entrambi hanno **emotional involvement** nelle discussioni
- Differenza: VIRTUAL HUMAN usa agenti virtuali con embodiment (avatar animati), AIutami usa solo voce

### 3. Il principio "No Presentation Without Representation"
Rilevante per AIutami: il moderatore AI deve mantenere una rappresentazione del contesto della discussione per generare interventi appropriati. AIutami fa questo con il **summary evolutivo della sessione** -- una forma di discourse memory che rappresenta lo stato della conversazione.

### 4. Anticipation Feedback Loops
Il concetto di anticipare come l'utente interpretera l'output del sistema e rilevante per il moderatore di AIutami. Attualmente AIutami non implementa feedback loops espliciti -- l'LLM genera e il TTS produce senza verifica intermedia. Possibile estensione: verificare che l'intervento del moderatore sia appropriato prima di pronunciarlo.

### 5. Dialogue understanding come AI-complete
Argomento utile per la tesi: il moderatore di AIutami non deve solo "capire" il testo trascritto, ma anche il contesto del gruppo, le dinamiche relazionali, lo stato emotivo -- confermando che la moderazione multiparty e un task AI-complete.

### 6. LLM come "super-parrots" vs moderatore AIutami
La critica di Wahlster agli LLM (nessun intento comunicativo esplicito, grounding limitato) e applicabile al moderatore di AIutami. L'LLM di AIutami non ha una "vera" comprensione della discussione -- genera risposte appropriate tramite pattern matching probabilistico. Ma il sistema di trigger e il summary evolutivo forniscono una struttura esterna che compensa parzialmente questa limitazione.

### 7. I 7 trend come framework per posizionare AIutami
AIutami tocca almeno 4 dei 7 trend identificati:
- Mixed-initiative (moderatore proattivo + partecipanti)
- Multimodal (speech input/output, anche se non simmetrico -- no gesti)
- Multi-party (N utenti + 1 AI)
- Emotionally aware (il moderatore interpreta il contesto emotivo via LLM)

### Confronto diretto con AIutami

| Aspetto | Wahlster (VIRTUAL HUMAN) | AIutami |
|---------|------------------------|---------|
| Periodo | 2006 (pre-LLM) | 2024 (post-LLM) |
| Modalita | Multimodale (speech + avatar animati) | Solo speech (WebRTC + TTS) |
| Partecipanti | 2 umani + 3 agenti virtuali | N umani + 1 AI moderatore |
| Ruolo AI | Moderatore + esperti (ruoli multipli) | Moderatore unico |
| Dialogue management | Agent-based platform con regole | LLM + trigger-based moderation |
| Stato emotivo | Rendering in tempo reale (gesti, colori, espressioni) | Interpretazione via LLM dal testo trascritto |
| Discourse memory | Rappresentazione simbolica esplicita | Summary evolutivo in linguaggio naturale |
| Turn-taking | Multi-modal (speech + gesti) | Esplicito (request + reservation window) |
| Grounding | Knowledge graphs + domain model | In-prompt knowledge + session context |

## Collegamento con gli altri paper letti

- **Zheng et al. (2022)**: il trend "da dyadic a multi-party" di Wahlster e esattamente il gap che Zheng identifica nella letteratura. Wahlster conferma da una prospettiva storica che il multiparty e stato a lungo trascurato rispetto al dyadic.
- **Gu et al. (2022)**: il framework WHO/WHAT/WHOM di Gu e un'operazionalizzazione moderna delle sfide che Wahlster identifica per i multiparty dialogue systems (addressee detection, response generation).
- **Addlesee et al. (2024)**: il robot ARI e un discendente della linea SMARTKOM/VIRTUAL HUMAN -- embodied dialogue system con LLM. Addlesee cita Wahlster come background.
- **Houde et al. (2025)**: il tema del mixed-initiative e central in Wahlster (SMARTKOM) e in Houde (proactive vs reactive). Il concetto di "anticipation feedback" di Wahlster e complementare al "value scoring" di Koala.
- **Addlesee et al. (2020)**: la valutazione ASR incrementale di Addlesee 2020 affronta proprio la sfida che Wahlster identifica a p.2: "the step-by-step reduction of uncertainties in the interpretation of utterances" -- partendo dal livello acustico.
- **Adikari et al. (2022)**: il trend "emotionally charged conversations" di Wahlster e realizzato da Adikari con emotion detection e co-facilitazione empatica.

## Concetti utili per la tesi

1. **"Dialogue understanding is AI-complete"** -- citazione potente per motivare la complessita del task di AIutami
2. **Uncertainty reduction funnel** (Figure 1): speech recognition -> language analysis -> dialogue understanding. Applicabile alla pipeline STT-LLM di AIutami
3. **"No presentation without representation"** -- principio architetturale che giustifica il summary evolutivo di AIutami
4. **Massime di Grice** -- framework per valutare la qualita delle risposte del moderatore AI
5. **Hybrid neuro-symbolic** -- direzione futura che combina la robustezza dell'LLM con la struttura esplicita dei trigger di AIutami

## Paper citati da approfondire

- **Reithinger et al. (2006)** [25]: VIRTUAL HUMAN -- dettagli tecnici del sistema multiparty con agenti virtuali
- **Ni et al. (2023)** [6]: "Recent advances in deep learning based dialogue systems: a systematic survey" -- survey complementare, post-LLM
- **Bender & Koller (2020)** [33]: "Climbing towards NLU" -- critica fondamentale all'idea che gli LLM "capiscano" il linguaggio
- **Jurafsky & Martin (2023)** [2]: Capitoli 15-16 su chatbots e dialogue systems -- textbook di riferimento
