# Multi-party Multimodal Conversations Between Patients, Their Companions, and a Social Robot in a Hospital Memory Clinic

- **Autori**: Addlesee, Cherakara, Nelson, Hernandez Garcia, Gunson, Sieinska, Dondrup, Lemon
- **Anno**: 2024
- **Fonte**: EACL 2024 (18th Conference of the European Chapter of the ACL), System Demonstrations, pp. 62-70
- **Citazioni**: 17
- **Pagine**: 9
- **Affiliazione**: The Interaction Lab, Heriot-Watt University, Edinburgh, UK
- **Progetto**: EU H2020 SPRING
- **Demo video**: https://www.youtube.com/watch?v=xMCpcsLhN_I
- **Prompts**: https://github.com/AddleseeHQ/mp-llm-demo-prompts

## Relazione con Addlesee et al. (2024) HRI

Questo paper e la **versione estesa** del paper corto HRI 2024 di cui abbiamo gia la scheda. Stesso sistema (ARI robot nella memory clinic), ma con significativamente piu dettagli tecnici, risultati quantitativi, e componenti aggiuntivi (clarification requests, in-prompt grounding, gesture generation). Questa scheda SOSTITUISCE e COMPLETA quella precedente.

## Problema affrontato

I sistemi SDS commerciali (Siri, Alexa) e la ricerca sono progettati per interazioni diadiche. Questo e un limite critico quando si deployano robot sociali in spazi pubblici dove piu persone interagiscono contemporaneamente (ospedali, musei, aeroporti). Le sfide specifiche delle MPC:
1. **Speaker recognition**: chi ha parlato? Il significato cambia in base a chi parla (Example A, Table 1)
2. **Addressee recognition**: a chi e indirizzato l'utterance? Ambiguo senza gaze (Example C)
3. **Response generation**: dipende da chi ha detto cosa a chi, nel contesto multiparty
4. **Multi-party goal tracking**: un utente puo esprimere il goal di un altro (Example B), rispondere al goal di un altro (Example C), o condividere goals (Example D, "we are hungry")

## Setting: Memory Clinic ospedaliera

- Pazienti in diagnosi di demenza + accompagnatori (familiari/amici)
- Giornate lunghe con attese ansiose tra appuntamenti
- Il robot deve essere **utile** (direzioni, orari bus, menu caffe) e **intrattenente** (quiz, barzellette, chit-chat)
- Staff ospedaliero esegue gli esperimenti con pazienti volontari
- Iterativo: il sistema e stato migliorato attraverso test regolari con pazienti reali

## Architettura del sistema (Figure 2)

Pipeline completa con 6 componenti principali:

### (A) Robot Platform - ARI
- Robot umanoide ARI, 1.65m, base mobile
- Touch-screen sul torso, braccia mobili per gesti, testa con occhi LCD per gaze
- ReSpeaker Mic v2.0 array (microfono)
- Camera RGB nella testa + camera fish-eye 180° nel petto
- TTS: Acapela Text-to-Speech
- LLM: **Vicuna-13b-v1.5** (locale, per privacy)

### (B) Addressee Detection - Gaze + LLM
- Due detector addressee creati con Vicuna-13b-v1.5:
  1. Solo testo (dialogue history + current turn)
  2. Testo + informazione gaze (utente guarda ARI o no)
- **Risultati su dati reali ospedalieri annotati**:
  - Accuratezza: **53.35%** (solo testo) → **85.40%** (testo + gaze)
  - Recall: **31.33%** (solo testo) → **91.00%** (testo + gaze)
- Gaze detection model (Tonini et al., 2023) per rilevare quando l'utente guarda ARI
- Se ARI NON e il destinatario → **Do Nothing** (non interrompe)
- Recall massimizzato: meglio rispondere quando non necessario che ignorare quando indirizzato

### (C) Clarification Requests (iCR) - Accessibilita per demenza
**Problema**: pazienti con demenza pausano piu frequentemente e piu a lungo (word-finding problems). L'ASR interpreta la pausa come fine turno → interruzione con nonsense.

**Soluzione**: se l'utterance non e completa, generare una clarification request naturale invece di rispondere.

**Tassonomia delle CR** (dal corpus SLUICE-CR, 3000 CR umane per 250 domande interrotte):
1. **Sentential CR (SentCR)**: frasi complete autonome ("Who wrote what?") -- gli umani le usano raramente (3.8%)
2. **Reprise CR (RCR)**: ripetono le ultime parole per localizzare il punto di interruzione ("zipcode of?") -- 39.6% umano
3. **Sluice CR (SCR)**: come RCR ma con wh-word finale ("zipcode of who?", "By who?" come in Example E) -- 35.2% umano

**Metrica**: Sluice Match Accuracy (SMA) = % di CR generate con wh-word che corrisponde ad almeno una delle 12 CR umane.

**Risultati** (Table 2):

| Modello | Prompt | SMA | SentCR% | RCR% | SCR% |
|---------|--------|-----|---------|------|------|
| Umano | - | - | 3.8 | 39.6 | 35.2 |
| GPT-4 | Reasoning | 97.6 | 0.8 | 1.2 | 86.0 |
| Llama-2-70b | Reasoning | 86.0 | 51.6 | 20.0 | 12.0 |
| Vicuna-13b-v1.5 | Reasoning | 87.0 | 66.4 | 2.4 | 20.0 |

- GPT-4 eccellente ma richiede API (privacy). Vicuna-13b scelto per deployment locale.
- Con prompt "basic" (senza esempi), tutti gli LLM generano quasi solo SentCR (non naturali)
- Con prompt "reasoning" (con esempi + motivazione), gli LLM imparano a generare iCR

### (D) Response Generation - In-prompt Grounding
- Info ospedale fornite nel prompt + guardrails ("you are not qualified to give medical advice", "you do not have access to patient records")
- **Miglioramento QA**: error rate da **29.2%** (sistema precedente Alana V2) a **11.5%** (LLM-based)
- LLM gestisce inherentemente chit-chat, barzellette, quiz -- prima impossibile

**Problema hallucination da world knowledge**: l'LLM puo generare info NON nel prompt ma appresa dal pre-training. Esempio critico: "you should fast before your visit" -- il prompt non lo dice, e il paziente resterebbe a digiuno inutilmente.

**Soluzione - "Jodie" Prompt**: attribuire il passaggio a una persona fittizia ("Jodie W. Jenkins said '...' Answer according to Jodie W. Jenkins") forza l'LLM a groundare la risposta nel testo fornito.

**Risultati grounding** (Table 3, su 50 domande con ospedale fittizio):

| Modello | Basic Acc | Jodie Acc | Expert Acc | Wikipedia Acc |
|---------|-----------|-----------|------------|---------------|
| GPT-4 | 94% | **98%** | 92% | 90% |
| Llama-70b | 64% | **82%** | 70% | 68% |
| Vicuna-13b-v1.5 | 70% | **74%** | 52% | 56% |

- "Jodie" prompt: accuratezza MAI deteriorata, migliorata fino a +28% (media +10%)
- QUIP-score (precision del grounding al testo fornito) migliore con Jodie
- Expert e Wikipedia prompt differiscono per un solo nome ma performano peggio

### (E) Gesture Generation
- Gesti generati da Vicuna-13b in parallelo con la risposta testuale
- Gesti funzionali: guardare l'utente indirizzato, puntare per direzioni, indicare passaggio turno
- No gesti durante l'ascolto (ego-noise dei motori satura il microfono)
- **Accuratezza gesti**: 86% su 110 risposte annotate, precision 0.91
- Gestire tag forniti in-prompt al robot (Cherakara et al., 2023)

## Evoluzione dal sistema precedente

| Aspetto | Alana V2 (Gunson 2022) | Sistema attuale (EACL 2024) |
|---------|----------------------|---------------------------|
| Architettura | Modulare tradizionale | LLM-based (Vicuna-13b) |
| Multi-party | No (rispondeva a ogni turno) | Si (addressee detection) |
| QA error rate | 29.2% | 11.5% |
| Out-of-domain | "I'm not sure, but I can help with..." | Gestito dall'LLM (quiz, jokes, chit-chat) |
| Accessibility | No | iCR per utterance incomplete |
| Grounding | N/A | "Jodie" prompt |
| Gesti | Limitati | Generati dall'LLM |

## Considerazioni etiche

- **Privacy**: Vicuna locale (non API cloud) per proteggere dati pazienti. Impossibile garantire che i pazienti non rivelino info personali, specialmente in memory clinic
- **Hallucination**: mai eliminabili completamente. Staff ospedaliero presente per correggere errori
- **Nessuna info personale** fornita al sistema (no schedule pazienti) per evitare confusione
- **Prompt poisoning**: rischio in deployment reale. Mitigabile con speaker diarization e reset della dialogue history

## Limiti

- Solo 2 umani + 1 robot (non testato con gruppi piu grandi)
- Vicuna-13b non e il modello piu capace (limitazione hardware)
- Speaker diarization non implementata -- si basa su osservazione esterna
- Gaze detection dipende dall'hardware del robot e dalla posizione fisica
- Valutazione quantitativa limitata (no user study formale con metriche UX)
- Solo inglese
- Contesto molto specifico (memory clinic) -- generalizzabilita da verificare
- Ego-noise del robot impedisce gesti durante l'ascolto

## Rilevanza per la tesi

**Molto alta**. Questo e il paper piu direttamente confrontabile con AIutami, e questa versione EACL fornisce i dettagli quantitativi che mancavano nel paper corto HRI.

### 1. Architetture a confronto: stesso paradigma, scelte diverse

Entrambi usano **pipeline STT → LLM → TTS**, ma con scelte architetturali complementari:

| Aspetto | Addlesee (ARI/EACL) | AIutami |
|---------|--------------------|---------|
| **Turn-taking** | Implicito: addressee detection (gaze + LLM) | Esplicito: request + reservation window (8s) |
| **Chi parla** | Microfono condiviso, nessuna diarization | WebRTC: stream audio separati per partecipante |
| **Quando rispondere** | Se addressee = robot (gaze + text) | Trigger-based (timer + condizioni conversazionali) |
| **Utterance incomplete** | iCR (clarification requests) | Non gestite esplicitamente |
| **Grounding** | "Jodie" prompt per in-prompt knowledge | Session context + summary evolutivo |
| **Hallucination** | Jodie prompt + guardrails + staff presente | Guardrails nel prompt + contesto sessione |
| **LLM** | Vicuna-13b locale (privacy) | Azure OpenAI cloud |
| **Multimodalita** | Speech + gaze + gesti (robot fisico) | Solo speech (WebRTC) |
| **Scala** | 2 umani + 1 robot | N umani + 1 AI moderatore |
| **Ruolo AI** | Receptionist/intrattenitore | Moderatore di discussione |
| **Contesto** | Memory clinic (healthcare) | Multi-contesto (murder mystery, terapeutico, accademico) |

### 2. Addressee detection vs Turn-taking esplicito
Addlesee risolve il problema "a chi rispondere" con gaze + LLM (accuratezza 85.4%). AIutami non ha questo problema: il moderatore parla al gruppo, e il turn-taking esplicito con reservation window gestisce chi parla quando. Sono due soluzioni complementari per contesti diversi:
- **Addlesee**: il robot e un partecipante passivo che deve capire quando gli si parla
- **AIutami**: il moderatore e attivo e gestisce il flusso della discussione

### 3. Clarification Requests -- gap di AIutami
Addlesee introduce iCR per gestire utterance incomplete (cruciale per pazienti con demenza). AIutami non ha questa funzionalita -- se l'ASR taglia un turno a meta, l'LLM riceve testo incompleto. Possibile estensione per AIutami: rilevare utterance incomplete e chiedere chiarimenti prima di procedere.

### 4. In-prompt grounding -- "Jodie" prompt
La tecnica "Jodie" per forzare il grounding e direttamente applicabile ad AIutami. Il moderatore di AIutami potrebbe usare una tecnica simile per groundare le risposte al contesto della sessione piuttosto che alla world knowledge dell'LLM. Attualmente AIutami usa il session context nel prompt, ma senza una strategia esplicita anti-hallucination come Jodie.

### 5. Privacy: locale vs cloud
Addlesee sceglie Vicuna locale per privacy (setting ospedaliero). AIutami usa Azure OpenAI cloud. Questa e una differenza architetturale significativa che ha implicazioni per deployment in contesti sensibili.

### 6. Evoluzione da sistema tradizionale a LLM-based
L'evoluzione da Alana V2 (modulare) al sistema LLM-based mostra lo stesso pattern di AIutami: gli LLM semplificano enormemente il dialogue management, eliminando la necessita di pipeline modulari complesse per intent recognition, slot filling, etc.

### 7. Multi-party goal tracking
Addlesee introduce il concetto di **multi-party goal tracking** (un utente esprime il goal di un altro, risponde al goal di un altro, goals condivisi). AIutami non ha goal tracking esplicito -- il moderatore interpreta il contesto via LLM. Ma il concetto e rilevante: in una discussione moderata, i partecipanti possono esprimere le esigenze di altri partecipanti.

## Collegamento con gli altri paper letti

- **Addlesee et al. (2024) HRI**: questa e la versione estesa dello stesso sistema. La scheda HRI puo essere considerata superata da questa.
- **Addlesee et al. (2020) COLING**: stesso primo autore, 4 anni prima. Nel 2020 valutava ASR incrementale. Nel 2024 ha un sistema completo deployato. L'evoluzione: le sfide ASR del 2020 sono state parzialmente risolte con LLM + gaze.
- **Gu et al. (2022)**: citato esplicitamente. Il framework WHO/WHAT/WHOM e implementato: speaker recognition (WHO), addressee detection (WHOM), response generation (WHAT).
- **Zheng et al. (2022)**: le 4 sfide polyadic sono tutte affrontate. Il sistema e "ignorable" (Do Nothing quando non indirizzato) e "visible" (robot fisico).
- **Houde et al. (2025)**: la tassonomia WHEN/WHAT/WHERE si applica: WHEN = addressee detection, WHAT = grounded response + iCR, WHERE = speech + gesti del robot.
- **Adikari et al. (2022)**: entrambi in contesto healthcare, ma Adikari e text-based co-facilitatore, Addlesee e speech-based con robot fisico.
- **Wahlster (2023)**: ARI e un discendente della linea SMARTKOM/VIRTUAL HUMAN di Wahlster -- embodied dialogue system con gesti e turn-taking multimodale.

## Paper citati da approfondire

- **Addlesee (2024)**: tesi di dottorato -- "Incremental Multi-party Conversational AI for People with Dementia". Contiene tutti i dettagli del sistema, corpus SLUICE-CR, e risultati completi
- **Addlesee et al. (2023d)**: "Multi-party Goal Tracking with LLMs" -- pre-training, fine-tuning, prompt engineering per goal tracking multiparty
- **Traum (2004)**: "Issues in multiparty dialogues" -- riferimento fondamentale per MPC, citato da quasi tutti i paper letti
- **Cherakara et al. (2023)**: FurChat -- embodied conversational agent con LLM e espressioni facciali
