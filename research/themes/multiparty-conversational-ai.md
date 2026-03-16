# Multiparty Conversational AI

Tema centrale della tesi: "multiuser/multiparty/polyadic speech-based chatbots"

## Premessa: perche il multiparty e diverso

La quasi totalita dei conversational agent (Siri, Alexa, ChatGPT, GPT-4o voice) e progettata per interazioni **diadiche**: un utente parla, il sistema risponde. Ma la comunicazione umana reale e prevalentemente di gruppo -- riunioni, lezioni, terapie, brainstorming. Passare da diadico a multiparty non e un'estensione incrementale: e un cambio di paradigma che introduce problemi qualitativamente nuovi (Gu et al., 2022; Zheng et al., 2022; Traum, 2004).

**Differenza strutturale** (Gu et al., 2022):
- **Diadico**: flusso informativo sequenziale -- A parla, B risponde, A risponde
- **Multiparty**: flusso informativo a grafo -- ogni utterance puo essere detta da chiunque e indirizzata a chiunque, con sotto-conversazioni parallele

## Tassonomie di riferimento

### WHO says WHAT to WHOM (Gu et al., 2022 -- IJCAI)

Framework NLP/tecnico che decompone le MPC in tre problemi computazionali:

| Componente | Problema | Approcci |
|------------|----------|----------|
| **WHO** (Speaker Modeling) | Chi parla? Chi parla dopo? | Turn-taking prediction (CRF, LSTM, Transformer), speaker diarization |
| **WHAT** (Utterance Modeling) | Cosa dire? | Retrieval-based (TopicBERT), generation-based (HeterMPC, LLM) |
| **WHOM** (Addressee Modeling) | A chi e indirizzato? | Addressee recognition (MPC-BERT), dialogue disentanglement |

Gu identifica che questi tre problemi sono trattati separatamente in letteratura, ma nella pratica sono interdipendenti. Manca un modello unificato.

**Limite critico**: il survey copre solo MPC **text-based**. L'estensione a speech-based aggiunge complessita (ASR errors, overlapping speech, prosodia, latenza).

### WHEN / WHAT / WHERE + SPECIFY / ACCESS / IMPLEMENT (Houde et al., 2025 -- IUI)

Framework HCI/design per controllare il comportamento di un agente AI in conversazioni di gruppo:

**Cosa controllare:**
- **WHEN** -- Quando l'agente interviene: trigger (ogni messaggio, solo se indirizzato, quando serve steering), filtri (soglia di valore, rilevanza), frequenza (immediatamente, dopo gli umani, al ritmo del gruppo)
- **WHAT** -- Cosa contribuisce: contenuto (idee conservative vs creative), stile (tono, lunghezza, struttura), modalita (testo, emoji, voce)
- **WHERE** -- Dove contribuisce: nel canale condiviso, in un thread, come messaggio privato

**Come controllarlo:**
- **SPECIFY** -- Come specificare il comportamento: pannello UI, linguaggio naturale in-chat, role-based, persona-based
- **ACCESS** -- Chi puo controllarlo: admin, chiunque, consenso democratico
- **IMPLEMENT** -- Come implementarlo: system prompt, logica esterna all'LLM, ibrido

Questa tassonomia e complementare a Gu: dove Gu descrive **i problemi tecnici**, Houde descrive **lo spazio di design** per il controllo dell'agente.

### Sfide delle interazioni umano-umano mediate da CA (Zheng et al., 2022 -- CHI)

Analisi UX su 36 paper polyadic dall'ACM Digital Library. Identifica 4 sfide fondamentali:

1. **Comunicazione inefficiente** -- topic drift, mancanza di struttura, difficolta a raggiungere consenso
2. **Mancanza di engagement** -- partecipazione diseguale, engagement passivo
3. **Barriere nel mantenimento relazionale** -- mancanza di consapevolezza emotiva, difficolta a regolare le emozioni di gruppo
4. **Necessita di costruire connessioni** -- ice-breaking, common ground, sfide cross-culturali

E tre proprieta di design che i polyadic CA devono avere:
- **Visible**: gli utenti devono essere consapevoli della presenza dell'agente
- **Ignorable**: gli interventi dell'agente devono essere non-invasivi; se troppo frequenti, l'effetto e controproducente
- **Accountable**: deve essere chiaro a chi l'agente risponde e chi ne controlla il comportamento

## Sistemi multiparty con AI

### Koala -- Agente AI in brainstorming di gruppo (Houde et al., 2025)

**Setting**: bot Slack in sessioni di brainstorming IBM (3 umani + 1 AI), text-based.

**Due varianti**:
- **Reactive**: risponde solo se indirizzato direttamente (@Koala)
- **Proactive**: self-scoring LLM (0-100) con soglia; se il valore percepito supera la soglia, contribuisce autonomamente

**Risultati chiave**:
- Koala generava il 73% di tutte le idee nelle condizioni AI, ma solo il 33% delle top ideas selezionate
- 72% dei partecipanti preferiva la variante **reactive**
- Koala proattivo percepito come "pedantic student who wouldn't create space for others"
- Koala II (con soglia configurabile dall'utente): nessun gruppo e tornato alla versione reactive
- Utilita dei controlli: 4.46/5 -- gli utenti vogliono poter regolare il comportamento **durante** la sessione

**Insight fondamentale**: la proattivita non e ne binaria ne fissa. Gli utenti devono poterla controllare dinamicamente.

### ARI Robot -- Social robot in memory clinic (Addlesee et al., 2024 -- EACL)

**Setting**: robot umanoide ARI in ospedale, 2 umani (paziente + accompagnatore) + 1 robot, speech-based.

**Pipeline**: ASR → Gaze Detection → Addressee Detection (LLM) → Full Utterance Check → Response Generation (Vicuna-13b) → TTS + Gesti

**Componenti innovativi**:
- **Addressee detection** con gaze + LLM: 85.4% accuratezza (vs 53.4% solo testo). Se il robot non e il destinatario → Do Nothing
- **Clarification requests (iCR)**: se l'utterance non e completa (frequente con pazienti con demenza), genera una richiesta di chiarimento naturale invece di rispondere a nonsense
- **"Jodie" grounding**: attribuire le informazioni a una persona fittizia forza l'LLM a groundare le risposte nel prompt, riducendo hallucination (accuratezza +10% medio)
- **Gesti generati dall'LLM**: 86% accuratezza su 110 risposte annotate

**Limite**: solo 2 umani + 1 robot. Non testato con gruppi piu grandi.

### Co-facilitatore empatico in terapia oncologica (Adikari et al., 2022)

**Setting**: gruppi di supporto online text-based per pazienti oncologici (Cancer Chat Canada), 120K conversazioni.

**Modello**: AI come **co-facilitatore** del terapista umano (non moderatore autonomo). L'AI monitora in background e segnala al terapista.

**Capacita tecniche**:
- Emotion detection (8 emozioni di Plutchik) con Word2Vec + GloVe
- Emotion state transitions via catene di Markov -- predice transizioni verso emozioni negative
- Group emotion score e patient behavioral metrics a intervalli di 10-30 minuti
- Negativity threshold (lambda > 0.5) → trigger di risposta empatica o alert al terapista

**Limite**: pre-LLM (2021), usa classificatori classici e template predefiniti.

### Furhat Robot -- Conversazione aperta multiparty (Axelsson et al., 2025)

**Setting**: robot sociale Furhat, 2 umani + 1 robot, conversazione aperta (open-ended), speech-based.

**Pipeline**: Voice Direction-of-Arrival → Azure STT → Speaker Diarization + Face Recognition → GPT-3.5 → TTS + Gaze/Head movements

**Risultati chiave**:
- **Addressee accuracy**: 92.6% in setting parallelo (due utenti separati), 79.3% in setting di gruppo
- **Voice recognition**: solo **26.8%** accuratezza per utterance parallele -- conferma che l'audio-only e insufficiente per multiparty
- **Face recognition**: 80-94.7% accuratezza
- **Latenza**: 1.35s media (dominata dalla generazione LLM)
- Engagement maggiore in setting di gruppo vs parallelo

**Limite**: solo 2 umani, interazioni brevi (~12 min), laboratorio controllato, nessun ruolo di moderazione.

**Confronto con Addlesee (2024)**: stesso paradigma (robot + gaze + LLM), piu recente, addressee detection migliore (92.6% vs 85.4%), ma conversazione aperta vs contesto ospedaliero specifico.

### VIRTUAL HUMAN -- Precursore storico (Wahlster, 2023)

**Setting**: quiz sportivo con 2 umani + 3 agenti virtuali (1 moderatore + 2 esperti), multimodale.

**Rilevanza storica** (2006): dimostra che il concetto di moderatore AI in conversazioni multiparty esisteva gia 20 anni fa, ma con tecnologie pre-LLM (dialogue management simbolico, regole esplicite). L'avvento degli LLM ha reso questo approccio molto piu flessibile e scalabile.

## Sfide tecniche specifiche del multiparty speech-based

Addlesee et al. (2020) valuta le sfide ASR in contesto multiparty e diadico:

| Sfida | Descrizione | Stato 2020 |
|-------|-------------|------------|
| **Speaker diarization** | Chi sta parlando in ogni momento | DER 49-67% multiparty (IBM), Google fallisce con 4 speaker |
| **Overlapping speech** | Parlato sovrapposto degrada ASR | ~20% degradazione WER (Microsoft, Google) |
| **ASR incrementale** | WER incrementale 6x peggiore del batch | 33% WER incrementale vs 5% batch |
| **Disfluenze** | Pause piene, auto-correzioni, edit terms | Microsoft preserva meglio le pause piene |

Queste sfide tecniche spiegano perche quasi tutta la ricerca multiparty e text-based (Gu, 2022; Zheng, 2022; Houde, 2025): lo speech introduce complessita enorme.

## Mappa concettuale integrata

Come le tassonomie si relazionano tra loro:

```
Gu (NLP/Tecnico)          Houde (HCI/Design)         Zheng (UX/Proprieta)
-----------------          ------------------          --------------------
WHO speaks?        <---->  WHEN to contribute?  <---->  Visible (presenza)
Say WHAT?          <---->  WHAT to contribute?  <---->  Ignorable (non-invasivo)
Address WHOM?      <---->  WHERE to contribute?  <--->  Accountable (responsabilita)
                           SPECIFY / ACCESS / IMPLEMENT
```

## Confronto dei sistemi multiparty

| Aspetto | Koala (IBM) | ARI Robot (HW) | Furhat Robot | Co-facilitator (LaTrobe) | VIRTUAL HUMAN (DFKI) | **AIutami** |
|---------|------------|-----------------|-------------|--------------------------|---------------------|-------------|
| **Anno** | 2025 | 2024 | 2025 | 2022 | 2006 | 2024 |
| **Modalita** | Text (Slack) | Speech + gaze + gesti | Speech + gaze + gesti | Text (chat) | Multimodale (avatar) | Speech (WebRTC) |
| **Ruolo AI** | Partecipante/contributor | Receptionist | Partner conversazionale | Co-facilitatore (background) | Moderatore + esperti | Moderatore |
| **Partecipanti** | 3 umani + 1 AI | 2 umani + 1 robot | 2 umani + 1 robot | N umani + AI + terapista | 2 umani + 3 agenti | N umani + 1 AI |
| **WHEN** | Self-scoring (soglia 0-100) | Addressee detection (gaze+LLM) | Gaze + silenzio prolungato | Negativity threshold (Markov) | Regole simboliche | Trigger-based (timer + condizioni) |
| **Controllo utente** | Pannello in-session | Nessuno | Nessuno | Nessuno (uso terapista) | Nessuno | Config iniziale sessione |
| **LLM** | Llama 2/3 | Vicuna-13b locale | GPT-3.5 (cloud) | Word2Vec + classificatori | Pre-LLM (simbolico) | Azure OpenAI (cloud) |
| **Turn-taking** | Implicito (text) | Addressee detection | Gaze-based | N/A (text asincrono) | Multi-modal rules | Esplicito (request + reservation 8s) |
| **Contesto** | Brainstorming aziendale | Memory clinic | Open-ended | Oncologia (support group) | Quiz sportivo | Multi-contesto |
| **Production-ready** | Prototipo | Deployato in ospedale | Prototipo (lab) | Prototipo | Prototipo storico | Deployato (web) |

## Gap nella letteratura

### 1. Speech-based multiparty con AI e estremamente scarso
Su 8 paper analizzati, solo Addlesee (2024) e Furhat (Axelsson et al., 2025) operano in speech, entrambi con soli 2 umani + 1 robot e dipendenza da gaze/video. Tutti gli altri sono text-based. Nessun sistema combina: speech-based + N partecipanti + AI moderatore attivo. Il survey MPCA (arXiv:2505.18845, 2025) conferma che la dimensione multimodale e sottorappresentata nella ricerca multiparty.

### 2. Nessuna tassonomia di design per multiparty speech-based
Houde (2025) crea una tassonomia eccellente (WHEN/WHAT/WHERE) ma la valida solo su text-based (Slack). Come cambia lo spazio di design quando si passa a speech? La voce introduce vincoli (serialita, non-skippability, latenza) e opportunita (prosodia, emozione, naturalezza) assenti nel testo.

### 3. Controllo dinamico dell'agente in contesti speech
Houde dimostra che gli utenti vogliono controllare l'agente **durante** la sessione. In speech, come si implementa? Non c'e un pannello da cliccare mentre si parla. Servono meccanismi voice-based o gestuali.

### 4. Addressee detection senza gaze in gruppi N>2
Addlesee raggiunge 85.4% con gaze + LLM per 2 umani. Senza gaze (audio-only come AIutami) e con N partecipanti, il problema e aperto. AIutami lo bypassa con turn-taking esplicito, ma a costo di naturalezza.

### 5. Clarification requests e utterance incomplete in multiparty speech
Addlesee introduce iCR per gestire pause di pazienti con demenza. Ma in multiparty generico con N speaker, come gestire utterance troncate dall'endpointing ASR? Il problema e amplificato: con piu parlanti, le interruzioni e i false-endpoint sono piu frequenti.

### 6. Valutazione: nessun benchmark per multiparty speech-based CA
Non esiste un dataset, un benchmark, o un protocollo di valutazione condiviso per sistemi multiparty speech-based con AI. Zheng (2022) propone metriche UX (discussion quality, even participation, perceived group climate) ma solo per text-based.

### 7. Equilibrio tra proattivita e non-invasivita in speech
Houde mostra che la proattivita eccessiva e "dirompente" in text (Koala proattivo dominava). In speech, dove la voce dell'AI occupa il canale audio condiviso, il rischio e amplificato. Come bilanciare la necessita di intervenire (moderazione) con il rispetto del flusso conversazionale?

## Posizionamento di AIutami

AIutami si posiziona all'intersezione di gap non coperti dalla letteratura:

```
                          Text-Based              Speech-Based
                    ┌──────────────────────┬──────────────────────┐
    Diadico         │  ChatGPT, Siri       │  GPT-4o, Moshi,      │
    (1 umano +      │  Alexa               │  LLaMA-Omni,         │
     1 AI)          │  (ampia letteratura)  │  Freeze-Omni         │
                    ├──────────────────────┼──────────────────────┤
    Multiparty      │  Koala (Houde 2025)  │                      │
    (N umani +      │  Adikari (2022)      │    ★ AIutami ★       │
     1+ AI)         │  MMAgents (2025)     │    Addlesee (2024)   │
                    │  Kim et al. (2020)   │    Furhat (2025)     │
                    │  DialogLab (2025)    │    (entrambi 2+1,    │
                    │  (letteratura media)  │     con gaze)        │
                    └──────────────────────┴──────────────────────┘
```

Il quadrante multiparty + speech-based e estremamente scarso. I soli 2 sistemi esistenti (Addlesee, Furhat) hanno entrambi: solo 2 umani, dipendenza da gaze/video, AI non moderatrice.

AIutami e l'unico sistema che combina:
1. **Speech-based** (WebRTC, non text)
2. **Multiparty reale** (N partecipanti, non solo 2+1)
3. **AI come moderatore attivo** (non receptionist o partner conversazionale)
4. **Audio-only** (non dipende da gaze/video)
5. **LLM-based** (Azure OpenAI, non regole simboliche)
6. **Production-ready e deployato** (non solo prototipo di ricerca)

### Come AIutami affronta le sfide identificate

| Sfida (letteratura) | Soluzione AIutami | Riferimento |
|---------------------|-------------------|-------------|
| Speaker diarization inaffidabile (Addlesee 2020) | WebRTC: stream audio separati per partecipante | Architettura |
| Overlapping speech degrada ASR (Addlesee 2020) | ASR gating: trascrizione solo per speaker corrente | ASR module |
| Addressee detection senza gaze (Addlesee 2024) | Bypass: turn-taking esplicito, moderatore parla al gruppo | Turn module |
| Proattivita dirompente (Houde 2025) | Reservation window 8s + trigger condizionali | Turn + Moderation |
| Engagement diseguale (Zheng 2022) | Turn-taking bilanciato, chiunque puo richiedere turno | Turn module |
| Comunicazione inefficiente (Zheng 2022) | Summary evolutivo, AI gestisce flusso discussione | Moderation module |

### Cosa AIutami NON affronta (possibili estensioni)

| Gap | Riferimento | Possibile estensione |
|-----|-------------|---------------------|
| Clarification requests per utterance incomplete | Addlesee (2024) | Rilevare utterance troncate e chiedere chiarimenti prima di procedere |
| Controllo dinamico dell'agente durante la sessione | Houde (2025) | Comandi vocali o pannello web per regolare comportamento del moderatore in-session |
| Grounding esplicito anti-hallucination | Addlesee (2024) | Tecnica "Jodie" per ancorare risposte al contesto sessione |
| Emotion-aware moderation | Adikari (2022) | Analisi sentimento dal testo trascritto per informare le decisioni del moderatore |
| VAP-informed turn management | Ekstedt & Skantze (2022) | Usare predizioni VAP per anticipare fine turno e gestire transizioni |

## Paper e risorse analizzate

| Paper | Fonte | Tipo | Modalita | Contributo chiave |
|-------|-------|------|----------|-------------------|
| Gu et al. (2022) | IJCAI | Survey | Text | Tassonomia WHO/WHAT/WHOM per MPC |
| Zheng et al. (2022) | CHI | Literature review | Text | Sfide UX polyadic, proprieta Visible/Ignorable/Accountable |
| Houde et al. (2025) | IUI | Empirico (2 studi) | Text (Slack) | Tassonomia WHEN/WHAT/WHERE, Koala, controllo dinamico |
| Addlesee et al. (2024) | EACL | System demo | Speech + gaze | ARI robot, addressee detection, iCR, "Jodie" grounding |
| Axelsson et al. (2025) | arXiv (2503.15496) | Sistema | Speech + gaze | Furhat robot, open-ended multiparty, 92.6% addressee con gaze, 26.8% audio-only |
| Addlesee et al. (2020) | COLING | Empirico | Speech | Valutazione ASR/SD incrementale per multiparty |
| Adikari et al. (2022) | FGCS | Framework | Text | Co-facilitazione empatica, emotion tracking, Markov transitions |
| Wahlster (2023) | Phil Trans R Soc | Review | Multimodale | Evoluzione storica, VIRTUAL HUMAN, principi architetturali |
| MPCA Survey (2025) | arXiv (2505.18845) | Survey | Misto | Conferma gap benchmark multimodali e limitazioni valutazione |
| DialogLab (Hu et al., 2025) | UIST | Tool | Misto | Authoring/simulazione conversazioni di gruppo umano-AI |
