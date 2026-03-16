# Turn-Taking

Tema indicato dal tutor: "turn taking" (non strettamente necessario ma utile)

## Framework fondamentale

**Sacks, Schegloff, Jefferson (1974)** -- "A Simplest Systematics for the Organization of Turn-Taking for Conversation". Concetto chiave: **Transition Relevance Places (TRPs)** -- punti dove un cambio di speaker puo legittimamente avvenire. Tre regole ordinate:
1. Current speaker seleziona next speaker
2. Next speaker si auto-seleziona
3. Current speaker continua

I turni umani hanno gap di ~200ms (Heldner & Edlund, 2010) -- molto piu veloce di qualsiasi sistema AI attuale.

## Approcci computazionali

### 1. Rule-Based / Threshold-Based
- Soglie di silenzio fisse (tipicamente 500-700ms)
- Usato da Alexa, Siri, Google Assistant
- Problema: **premature cutoffs** (interrompe l'utente) o **latenza eccessiva** (aspetta troppo)
- Termine tecnico: **endpointing**

### 2. Prosody-Based
- I parlanti segnalano turn-yielding con cues prosodiche: pitch calante, allungamento finale, riduzione intensita
- **Gravano & Hirschberg (2011)** -- "Turn-Taking Cues in Task-Oriented Dialogue": piu cues simultanee → piu probabile la transizione
- **Ward & Tsukahara (2000)** -- cues prosodiche per predizione backchannels

### 3. Machine Learning
- **Raux & Eskenazi (2009)** -- primo endpointing ML-based oltre soglie fisse
- **Meena, Skantze, Gustafson (2014)** -- Random Forests con features prosodiche e contestuali (robot Nao)
- **Skantze (2017)** -- "Towards a General, Continuous Model of Turn-Taking using LSTM": turn-taking come **problema di predizione continua**, non classificazione binaria a soglie
- **Ekstedt & Skantze (2020)** -- TurnGPT: Transformer per predire turn shifts dal contenuto linguistico
- Approcci recenti: Transformer + rappresentazioni self-supervised (wav2vec 2.0, HuBERT)

### 4. LLM-Based (recente)
- Gli LLM possono decidere quando rispondere basandosi sul contesto dialogico
- Addlesee et al. (2024): LLM prompt per decidere se l'utterance e completa o serve clarification
- Houde et al. (2025): Koala usa self-scoring LLM per decidere quando contribuire

## Concetti chiave

| Termine | Significato |
|---------|------------|
| Turn-yielding | Segnali che il parlante sta cedendo il turno |
| Turn-holding | Segnali che il parlante vuole continuare (es. pausa piena "uhm") |
| Backchannel | Feedback breve ("uh-huh", "si") che non costituisce un turno pieno |
| Barge-in | L'ascoltatore interrompe il parlante corrente |
| Floor | Chi "ha il pavimento" (il diritto di parlare) |
| Floor management | Processo di distribuzione dei diritti di parola |
| Overlap | Due parlanti parlano simultaneamente |
| TRP | Transition Relevance Place -- punto dove il cambio e legittimo |
| Endpointing | Rilevare quando l'utente ha finito di parlare |

## Multi-party turn-taking

### Sfide specifiche (3+ partecipanti)

1. **"Who's Next?" Problem**: in diadico, se uno smette l'altro parla. Con 3+, chi tra i potenziali next speakers prende il turno?
2. **Addressee recognition**: chi sta venendo indirizzato? Senza gaze (audio-only come AIutami), molto piu difficile
3. **Overlapping speech piu frequente**: degrada ASR e complica decisioni
4. **Speaker diarization piu complessa**: sapere "chi parla quando" e piu difficile con piu parlanti
5. **Dinamiche sociali**: schismi (sub-conversazioni parallele), dominance, coalizioni
6. **Meccanismi di allocazione turno**:
   - Nomina esplicita ("Cosa ne pensi, Marco?")
   - Selezione basata su gaze
   - Self-selection races (piu persone iniziano, una cede)
   - **Moderator-mediated** (come AIutami)

### Ricerca chiave su multi-party turn-taking
- **Bohus & Horvitz (2009, 2011)** -- modelli di engagement multi-party con Directions Robot (Microsoft)
- **Johansson, Skantze, Gustafson (2013, 2014)** -- gaze come meccanismo di turn-management con robot Nao/Furhat
- **Ishii, Nakano, Nishida (2013)** -- predizione gaze in conversazioni multi-party

## In AIutami

AIutami usa un approccio di **structured floor management**:
- **Richiesta turno esplicita** (utente chiede di parlare)
- **Reservation window** di 8 secondi (priorita al prossimo speaker)
- **Moderation-in-progress** blocca nuovi turni durante valutazione AI
- **AI moderatore** gestisce il flusso della discussione (decide quando intervenire)

### Vantaggi dell'approccio AIutami
- Evita il problema non risolto della predizione automatica del turn-taking in multi-party audio-only
- Garantisce equita (tutti possono richiedere un turno)
- Simile a sistemi di meeting management e classroom orchestration
- Trade-off: naturalezza ridotta rispetto a conversazione libera

### Possibili estensioni (per la tesi)
- **Ibrido VAP + reservation window**: usare predizioni VAP per informare le decisioni del moderatore (es. rilevare quando un speaker sta per finire per anticipare il prompt al prossimo speaker prenotato)
- **Barge-in detection**: usare VAD per rilevare quando qualcuno cerca di intervenire e segnalarlo al moderatore
- **Adaptive reservation window**: durata variabile basata sul contesto della discussione

## Sistemi di riferimento
- **Furhat Robot** (KTH / Furhat Robotics) -- turn-taking sofisticato con gaze e multimodalita
- **Google Duplex (2018)** -- timing quasi-umano nei turni telefonici
- **IrisTK** (KTH) -- framework per interazione multi-party face-to-face
- **Retico** -- framework per processing incrementale in SDS
