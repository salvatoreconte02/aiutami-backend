# Voice Activity Detection / Voice Activity Prediction

Tema indicato dal tutor: "non strettamente necessari ma sarebbero utili"

## VAD - Voice Activity Detection

### Cos'e
Task di classificazione binaria: in un dato momento, **qualcuno sta parlando o no?** Opera sul segnale audio e produce etichette speech/non-speech. E un passo di preprocessing in quasi tutte le pipeline speech (ASR, diarization, dialogue systems).

### Approcci tradizionali
- **Energy-based**: soglia su energia/ampiezza del segnale. Semplice ma fallisce in ambienti rumorosi
- **Zero-crossing rate**: combinato con energia per robustezza marginalmente migliore
- **Statistici**: GMM su features spettrali per distinguere speech da rumore
- **WebRTC VAD**: GMM leggero dal progetto WebRTC di Google, opera su frame di 10/20/30ms, 4 livelli di aggressivita. Molto veloce, risorse minime, ma accuratezza limitata in condizioni rumorose. Package Python: `py-webrtcvad`

### State of the Art (Neural VAD)

**Silero VAD** (de facto standard open-source):
- ~1M parametri, accuratezza molto alta
- Opera su audio 16kHz in chunk di 30-100ms
- Gira efficientemente su CPU (no GPU)
- Pre-trained, no fine-tuning necessario
- Disponibile come ONNX e PyTorch
- Ampiamente usato in produzione

**Altri modelli notevoli**:
- **pyannote-audio VAD** (Herve Bredin, IRIT Toulouse) -- parte del toolkit pyannote, piu pesante, progettato per pipeline di speaker diarization
- **MarbleNet** (NVIDIA NeMo) -- 1D time-channel separable convolutions
- **Personal VAD** (Google, 2020) -- rileva speech da un target speaker specifico

### Ruolo nelle pipeline di dialogo
1. **Gating ASR**: invia audio all'ASR solo quando c'e speech (esattamente quello che fa AIutami con l'ASR gating)
2. **Endpointing**: rileva quando l'utente smette di parlare → trigger risposta sistema
3. **Barge-in detection**: rileva quando l'utente inizia a parlare mentre il sistema sta parlando
4. **Riduzione bandwidth**: in WebRTC, sopprime trasmissione di frame di silenzio

**Critico**: VAD dice *che* qualcuno sta parlando, ma NON *chi* (serve speaker diarization) e NON *se intende prendere un turno pieno* (serve turn-taking prediction).

## VAP - Voice Activity Projection

### Cos'e e differenza da VAD
- **VAD e reattivo**: rileva attivita vocale corrente
- **VAP e predittivo**: prevede l'attivita vocale **futura** (chi parlera nei prossimi 0.5-2 secondi)

Questa distinzione e critica per il turn-taking: un sistema che **predice** che il parlante corrente sta per smettere (prima che smetta effettivamente) puo raggiungere transizioni piu naturali con latenza simile all'umano (~200ms).

### Ricerca chiave: Erik Ekstedt e Gabriel Skantze (KTH Stockholm)

**TurnGPT** (Ekstedt & Skantze, 2020):
- Transformer GPT-style per predire turn shifts dal contenuto linguistico
- Addestrato su trascrizioni di dialogo
- Dimostra che obiettivi di language modeling catturano naturalmente le regolarita del turn-taking

**VAP** (Ekstedt & Skantze, 2022) -- paper fondamentale:
- Input: **audio stereo** (un canale per speaker in dialogo diadico)
- Usa rappresentazioni **self-supervised** (CPC, wav2vec 2.0) elaborate da un Transformer
- Output: distribuzione di probabilita sugli stati futuri di voice activity per entrambi i parlanti nei prossimi 2 secondi
- Discretizzato in bin (es. 4 bin da 0.5s ciascuno, 4 stati possibili: nessuno parla, solo A, solo B, entrambi)
- **Self-supervised**: usa l'attivita vocale futura effettiva come segnale di training, nessuna annotazione manuale
- Valutato su Switchboard e Fisher corpus

**Cosa apprende implicitamente**:
- Turn-yielding cues
- Opportunita di backchannel
- Turn-holds (l'interlocutore continuera nonostante una pausa)
- Silenzi reciproci (fine del topic)

### Come VAP viene usato per turn-taking prediction
1. Audio stereo continuo in input
2. Modello self-supervised (wav2vec 2.0, HuBERT) estrae features a 50Hz
3. Transformer processa e produce, per ogni frame, probabilita di voice activity futura
4. Da queste predizioni si derivano: turn-shift probability, backchannel opportunity, turn-hold, mutual silence

**Paradigma fondamentalmente diverso** dagli approcci tradizionali: invece di ingegnerizzare regole su quando prendere il turno, il modello **apprende il comportamento di turn-taking end-to-end dai dati**.

### Lavori successivi
- Sperimentazione con diversi speech encoders (HuBERT, WavLM)
- Integrazione in sistemi di dialogo real-time
- Analisi di cosa il modello apprende (cues prosodiche, pattern di pausa, completezza sintattica)
- Contributo relativo prosodia vs lessico nelle predizioni VAP

## Rilevanza per multiparty

### Problema aperto: VAP per multi-party
- I modelli VAP attuali assumono audio stereo (2 canali per dialogo diadico)
- Con N partecipanti, ci sono N stream audio
- Processare tutte le N*(N-1)/2 combinazioni a coppie non scala
- **Estendere VAP a multi-party e esplicitamente un problema aperto** (Malik, Atieh & Skantze, 2023/2024)

### In AIutami
AIutami usa VAD implicitamente (ASR gating) ma NON usa VAP. Il turn-taking e gestito esplicitamente (reservation window).

### Possibili estensioni per la tesi
1. **VAP-informed moderation**: usare predizioni VAP per anticipare quando un speaker sta per finire, permettendo al moderatore di preparare il prossimo intervento
2. **Barge-in detection via VAD**: rilevare tentativi di interruzione e segnalarli al moderatore
3. **Adaptive endpointing**: usare VAP per migliorare il rilevamento di fine turno (evitare premature cutoffs per speaker che pausano piu a lungo)
4. **Estensione VAP a multi-party con audio WebRTC separati**: AIutami ha gia stream audio separati per partecipante -- vantaggio architetturale per applicare VAP a coppie di canali

## Termini per query Scopus

### VAD
`"voice activity detection"`, `"speech activity detection"`, `"speech/non-speech detection"`, `"SAD"`, `"VAD"`

### VAP
`"voice activity projection"`, `"voice activity prediction"`, `"turn-taking prediction"`, `"turn prediction"`

### Turn-taking (vedi anche turn-taking.md)
`"turn-taking"`, `"end-of-turn detection"`, `"endpointing"`, `"backchannel prediction"`
