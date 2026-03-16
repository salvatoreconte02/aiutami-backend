# WavChat: A Survey of Spoken Dialogue Models

- **Autori**: Huang et al.
- **Anno**: 2024
- **Fonte**: arXiv preprint
- **DOI/arXiv**: arXiv 2024 (survey)
- **Codice/Demo**: -

## Problema affrontato

Mancava un survey sistematico che organizzasse i spoken dialogue models (SDM) moderni -- dai classici assistenti vocali (Alexa, Siri) ai modelli "omni" multimodali -- coprendo rappresentazioni del parlato, training, streaming/duplex, dataset e metriche. Il survey colma questo vuoto proponendo tassonomie operative e mappando le tecnologie abilitanti.

## Approccio: tassonomia e organizzazione sistematica

### Definizione di Spoken Dialogue Model

Un SDM e un sistema che genera risposte verbali intelligenti a partire da input speech. Deve unire:
- **Text intelligence**: ragionamento, conoscenza, instruction following
- **Speech intelligence**: comprensione/generazione di tratti acustici oltre il testo (timbro, emozione, stile, rumore, eventi audio)

Il survey propone 9 categorie funzionali per gli SDM moderni: text intelligence, speech intelligence, comprensione/generazione audio/musica, multilingua, context learning, capacita di interazione, latenza streaming, multimodalita.

### Classificazione principale: Cascaded vs End-to-End

**A) Cascaded (pipeline)**
- Paradigma classico: ASR → LLM (testo) → TTS
- L'LLM produce solo testo, la voce e "aggiunta" dopo
- Anche con encoder multimodali, se l'LLM non genera direttamente rappresentazioni speech il sistema resta cascaded
- Regola discriminante: se il "cuore LLM" genera solo testo → cascaded

**B) End-to-end (speech-in/speech-out)**
- Training e inference operano direttamente su speech
- Molti approcci cercano comunque di allineare speech e testo per sfruttare LLM pre-addestrati (sproporzione dati testo vs speech)
- Regola discriminante: se il "cuore LLM" sa comprendere e generare rappresentazioni speech → end-to-end
- Primo end-to-end "puro" citato: dGSLM (prova concettuale di duplex end-to-end, senza text intelligence)

### Le 4 tecnologie chiave

1. **Speech representations** (tokenizer/detokenizer): unita discrete vs continue
2. **Training/inference/generation**: come allineare speech e testo preservando l'intelligenza dell'LLM; architetture e training multi-stage
3. **Interazione**: streaming, duplex, naturalezza conversazionale
4. **Dati e valutazione**: dataset di training, metriche, benchmark

### Streaming e duplex

Il survey insiste che gli SDM hanno natura temporale e interattiva. Non basta generare una risposta "dopo" -- occorre gestire:
- Latenza percepita
- Segnali conversazionali (backchannel, esitazioni)
- Sovrapposizioni e interruzioni

**Tecniche per streaming end-to-end:**
- Causal convolution (rispetto causalita, bassa latenza)
- Causal attention (mascheramento per evitare dipendenza dal futuro)
- Queue management (gestione real-time di frame/chunk audio)

**Pattern di design per full-duplex (esempi):**
- **SyncLLM**: chunking temporale e interleaving multi-stream; predizione chunk-wise per sincronizzazione e robustezza a latenza
- **OmniFlatten**: training progressivo da half-duplex a full-duplex; rimozione graduale di stream testuali
- **Freeze-Omni**: decisione chunk-wise dello stato conversazionale (continuare ad ascoltare / interrompere / rispondere), con VAD nell'innesco

### Dataset, metriche e benchmark

Per il testo esistono metriche consolidate. Per lo speech "nativo" le metodologie sono piu immature.

**Benchmark citati:**
- **VoiceBench**: conoscenza, instruction-following, sicurezza; variabilita speaker, rumore, disfluenze
- **SUPERB**: suite classica speech (ASR, keyword spotting, diarization, intent/slot, emotion)
- **AudioBench / AIR-Bench**: compiti audio eterogenei (speech, sound scenes, paralinguistica)

**Sicurezza speech-specific**: punto aperto -- mancano dataset e procedure consolidate su attacchi via audio, avvelenamento dati vocali, metriche di difesa.

## Risultati chiave

Essendo un survey, non presenta risultati sperimentali propri. I contributi principali sono:

1. **Tassonomia operativa** cascaded vs end-to-end con regola discriminante chiara
2. **Strutturazione in 4 aree tecniche** (rappresentazioni, training, interazione, valutazione) che copre sistematicamente il campo
3. **Evidenziazione del gap streaming/duplex** come la caratteristica piu distintiva rispetto ai dialoghi testuali
4. **Mappatura dei limiti della valutazione** speech-native, soprattutto per sicurezza e robustezza

## Limiti

- **Non copre multiparty**: il survey si concentra su dialogo dyadico (1 utente + 1 sistema), le conversazioni di gruppo non sono trattate
- **Bias verso modelli recenti**: la copertura pre-2023 e limitata
- **Nessuna valutazione comparativa propria**: le tabelle comparative riprendono risultati pubblicati dai singoli paper senza benchmark unificato
- **Limitato su turn-taking formale**: il turn-taking e discusso come feature di interazione ma senza approfondimento sulla letteratura specifica di conversation analysis

## Rilevanza per la tesi

**Molto alta** come riferimento strutturale per lo stato dell'arte.

1. **Framework organizzativo**: la divisione cascaded vs end-to-end e le 4 aree tecniche forniscono una struttura direttamente utilizzabile per organizzare i capitoli della literature review.

2. **Posizionamento di AIutami**: il survey permette di classificare AIutami come sistema **cascaded** (Azure STT → Azure OpenAI → Azure TTS) e motivare perche il cascaded e ancora pragmatico (zero training, modularita, facilita di deployment).

3. **Collegamento streaming/duplex → turn-taking**: il blocco su streaming, interruzioni e duplex si collega direttamente ai temi suggeriti dal tutor (turn-taking, VAD/VAP). Il survey conferma che questa e l'area piu innovativa e meno matura.

4. **Gap multiparty**: il survey NON tratta conversazioni multiparty, confermando che questo e un gap nella letteratura. Tutti i modelli e le tassonomie discusse assumono 2 partecipanti.

5. **Benchmark e valutazione**: la sezione su metriche e dataset e utile per la tesi quando si discute come valutare il proprio sistema -- e per evidenziare la mancanza di benchmark multiparty.

### Come usare il survey nella tesi

| Sezione tesi | Contenuto dal survey |
|--------------|---------------------|
| Inquadramento paradigmi | Cascaded vs end-to-end, regola discriminante, posizionamento AIutami |
| Architetture speech-based | Mappa dei modelli (SpeechGPT, Moshi, Freeze-Omni, LLaMA-Omni...) |
| Interazione naturale | Streaming, duplex, interruzioni → collegamento a turn-taking + VAD/VAP |
| Valutazione | Benchmark pertinenti, gap su sicurezza e valutazione speech |
| Gap e contributo | Assenza di multiparty come direzione non coperta |
