# Moshi: a speech-text foundation model for real-time dialogue

- **Autori**: Defossez, Mazare, Orsini, Royer, Perez, Jegou, Grave, Zeghidour (Kyutai)
- **Anno**: 2024
- **Fonte**: arXiv preprint
- **DOI/arXiv**: 2410.00037v2
- **Codice/Demo**: https://github.com/kyutai-labs/moshi / https://moshi.chat/

## Problema affrontato

I sistemi di dialogo vocale attuali si basano su pipeline di componenti indipendenti (VAD → ASR → LLM testuale → TTS) che presentano tre limiti fondamentali:
1. **Latenza alta**: la complessita della pipeline introduce latenze di diversi secondi, lontane dai ~230ms medi delle conversazioni umane
2. **Bottleneck testuale**: il testo come modalita intermedia perde informazioni paralinguistiche (emozione, prosodia, suoni non-speech)
3. **Modello turn-based**: la segmentazione in turni non gestisce sovrapposizioni, interruzioni e backchannel (10-20% del tempo parlato)

## Approccio: architettura end-to-end full-duplex

Moshi e un modello speech-to-speech end-to-end che genera e ascolta audio simultaneamente, eliminando il concetto di turni espliciti. E composto da tre componenti principali:

### 1. Helium (LLM backbone, 7B parametri)

- Autoregressive Transformer testuale, pre-trainato su 2.1T token di dati inglesi
- Architettura: RMS norm, RoPE, GaLU (SiLU), context 4096 token, SentencePiece tokenizer (32k)
- Competitivo con Llama 2, Falcon, MPT su benchmark standard (MMLU 54.3)
- Dati: mix di fonti curate (Wikipedia, StackExchange, pes2o) + CommonCrawl filtrato

### 2. Mimi (neural audio codec)

- Autoencoder con bottleneck discreto basato su Residual Vector Quantization (RVQ)
- **Split RVQ**: un VQ semantico (distillato da WavLM) + 7 livelli RVQ acustici in parallelo
- Encoder/decoder: SeaNet convoluzionale **causale** + Transformer nel bottleneck (8 layers)
- Frame rate: 12.5 Hz, 8 codebook, bitrate 1.1 kbps, audio 24kHz mono
- Streaming compatibile (primo frame dopo 80ms)
- Trainato con sole loss avversariali (no reconstruction loss), MUSHRA 81.0 -- superiore a RVQGAN, SpeechTokenizer, SemantiCodec

### 3. RQ-Transformer (generazione gerarchica)

Architettura a due livelli per generare token audio in modo efficiente:
- **Temporal Transformer** (grande, inizializzato da Helium): modella la sequenza temporale, processa S timestep
- **Depth Transformer** (piccolo, 6 layers, dim 1024): modella i K sotto-token per ogni timestep (text + semantic + acoustic)
- Parametrizzazione depthwise: pesi diversi per ogni livello RVQ nel Depth Transformer
- Acoustic delay di 1-2 step tra token semantici e acustici per ridurre le dipendenze intra-step

### Multi-stream modeling

- Due stream audio paralleli: uno per Moshi (output) e uno per l'utente (input)
- Il modello processa entrambi gli stream congiuntamente -- nessun confine esplicito tra turni
- Puo parlare e ascoltare simultaneamente (full-duplex)
- Addestrato su Fisher dataset (2000 ore di conversazioni telefoniche con canali separati)

### Inner Monologue

Innovazione chiave: per ogni timestep, il modello predice **prima** un token testuale allineato temporalmente, **poi** i token semantici e acustici. Gerarchia: testo → semantico → acustico.
- Migliora drasticamente la qualita linguistica e la fattualita del discorso generato
- Triplicata l'accuratezza su spoken Q&A rispetto a Moshi senza Inner Monologue
- Compatibile con streaming (a differenza di Chain-of-Modality che richiede la generazione completa del testo prima dell'audio)
- Cambiando il delay text-audio si ottengono streaming ASR o streaming TTS dallo stesso modello

### Training (4 fasi)

1. **Pre-training audio** (single-stream): 7M ore di audio, 1M step, LLM frozen 50% text batches
2. **Post-training multi-stream**: diarizzazione PyAnnote per simulare due stream, 100k step
3. **Fine-tuning Fisher**: conversazioni reali multi-stream, 10k step
4. **Instruct fine-tuning**: 20k+ ore di dati sintetici (conversazioni generate da Helium + TTS multi-stream), con data augmentation aggressiva (rumore, eco, riverbero)

## Risultati chiave

**Spoken Question Answering (0-shot):**

| Modello | Web Q. | LlaMA Q. | Trivia QA |
|---------|--------|----------|-----------|
| SpeechGPT (7B) | 6.5 | 21.6 | 14.8 |
| Spectron (1B) | 6.1 | 22.9 | - |
| **Moshi (7B)** | **26.6** | **62.3** | **22.8** |
| Moshi senza Inner Monologue | 9.2 | 21.0 | 7.3 |
| Helium (solo testo) | 32.3 | 75.0 | 56.4 |

- Moshi SOTA tra i modelli speech-text per spoken Q&A
- Inner Monologue triplica le performance rispetto a audio-only
- Gap con Helium (testo): moderato su Web Q. (-6), ampio su Trivia QA (-34)

**Latenza:**
- Teorica: **160ms** (acoustic delay 1 @ 12.5Hz = 2 frame = 160ms)
- Pratica: **~200ms**
- Inferiore alla media delle conversazioni umane (~230ms, Stivers et al. 2009)

**Audio quality (Mimi codec):**
- MUSHRA 81.0 (adversarial-only) vs 58.8 (reconstruction + adversarial)
- Superiore a RVQGAN (31.3), SemantiCodec (64.8), SpeechTokenizer (45.1) a bitrate inferiori

**Dialogue modeling:**
- Turn-taking naturale: gap, overlap e pause vicini ai valori del ground truth (Fisher)
- Qualita linguistica (DialoGPT perplexity) comparabile a un sistema cascaded

**Quantizzazione:**
- W4A8 (4.37 GB) mantiene qualita audio quasi intatta
- MMLU degrada da 49.7 a ~42-46 a 4 bit

## Limiti

- **Solo dyadic**: modella esattamente 2 stream (1 utente + 1 sistema), nessun supporto multiparty nativo
- **Catastrophic forgetting parziale**: MMLU scende da 54.3 (Helium) a 49.7 dopo training audio, gap significativo su Trivia QA
- **Dati di training massicci**: 7M ore audio + 2.1T token testo + 170 ore supervised multi-stream
- **Solo inglese**: trainato e valutato esclusivamente su dati in lingua inglese
- **Singola voce output**: Moshi usa una voce fissa (single voice actor), non multi-voice
- **Valutazione conversazionale limitata**: testato su Fisher (conversazioni telefoniche) e dati sintetici, non su dialoghi reali con utenti nel loop
- **Metriche audio inaffidabili**: il paper stesso evidenzia scarsa correlazione tra metriche oggettive (VisQOL, MOSNet) e qualita percepita soggettiva (MUSHRA)

## Classificazione architetturale

| Tipo | Descrizione | Moshi? |
|------|-------------|--------|
| **Pipeline STT-TTT-TTS** | Componenti completamente separati e indipendenti | No |
| **Half-cascade** | LLM testuale con encoder/decoder speech integrati strutturalmente | No |
| **End-to-end** | Singolo modello nativo speech-in/speech-out | **Si** |

Moshi e un modello **end-to-end**: opera direttamente nello spazio audio per input e output. L'LLM testuale (Helium) e integrato come backbone del Temporal Transformer, ma i suoi parametri vengono aggiornati durante il training audio (a differenza di Freeze-Omni). L'Inner Monologue genera testo come sottoprodotto interno, non come modalita intermedia obbligatoria -- il modello rimane fundamentalmente speech-to-speech.

## Rilevanza per la tesi

**Molto alta**. Moshi e il paper piu ambizioso e completo nella categoria delle architetture speech-based chatbot ed e il riferimento principale per l'approccio end-to-end.

1. **Riferimento architetturale end-to-end**: Moshi rappresenta l'estremo opposto rispetto al pipeline STT-TTT-TTS di AIutami. Nella tesi si colloca come punto di arrivo dello spettro architetturale: pipeline → half-cascade (Freeze-Omni) → end-to-end (Moshi).

2. **Full-duplex e turn-taking implicito**: Moshi e l'unico modello che elimina completamente il concetto di turni espliciti. Nella tesi questo e un confronto importante con il turn-taking esplicito di AIutami (TurnManager con reservation).

3. **Inner Monologue**: dimostra che anche nei modelli end-to-end, il testo come "scaffold" interno migliora drasticamente la qualita. Questo suggerisce che il vantaggio dei pipeline (ragionamento testuale) non va necessariamente perso negli end-to-end.

4. **Limite multiparty (gap chiave)**: Moshi modella esattamente 2 stream (utente + sistema). L'estensione a N stream per conversazioni multiparty e una direzione non esplorata. Questo e uno dei gap centrali della tesi: nessuna architettura end-to-end o half-cascade supporta nativamente conversazioni di gruppo.

5. **Trade-off quantitativo**: il paper fornisce numeri concreti per confrontare il costo del passaggio pipeline → end-to-end:
   - Latenza: ~200ms (Moshi) vs secondi (pipeline classici)
   - Dati richiesti: 7M ore + 2.1T token (Moshi) vs zero training per pipeline API-based (AIutami)
   - Intelligenza: MMLU 49.7 (Moshi) vs 54.3 (Helium testo) -- degradazione misurabile

### Differenze chiave con AIutami

| Aspetto | Moshi | AIutami |
|---------|-------|---------|
| Architettura | End-to-end (speech-to-speech) | Pipeline STT-TTT-TTS |
| LLM | Helium 7B locale (aggiornato) | Azure OpenAI (cloud, frozen) |
| Speech input | Mimi codec (12.5Hz, streaming) | Azure STT (servizio esterno) |
| Speech output | Mimi codec (24kHz) | Azure TTS (servizio esterno) |
| Latenza e2e | ~200ms | Dipende da latenze API Azure |
| Full-duplex | Si (sempre ascolta + parla) | No (turn-taking esplicito) |
| Multiparty | No (2 stream fissi) | Si (N utenti + 1 AI moderator) |
| Training | 7M ore audio, 2.1T token testo | Nessun training (usa API) |
| Informazione paralinguistica | Preservata (audio nativo) | Persa (bottleneck testuale) |

### Confronto con Freeze-Omni (half-cascade)

| Aspetto | Moshi (end-to-end) | Freeze-Omni (half-cascade) |
|---------|--------------------|----------------------------|
| LLM params | Aggiornati | Frozen |
| Catastrophic forgetting | Presente (MMLU -4.6) | Minimo (Web Q. -0.4) |
| Latenza | ~200ms | ~1.2s |
| Full-duplex | Si | No (VAD + state prediction) |
| Qualita voce | Alta (Mimi MUSHRA 81) | Limitata (TiCodec single-codebook) |
| Inner Monologue | Si (testo come prefix interno) | No (testo solo in decoder) |

## Paper correlati

- **Freeze-Omni** (Wang et al., 2024) -- gia analizzato, half-cascade con LLM frozen
- **LLaMA-Omni** (Fang et al., 2024) -- gia analizzato, half-cascade con LLM fine-tuned
- **SpeechGPT** (Zhang et al., 2023) -- gia analizzato, end-to-end con Chain-of-Modality
- **dGSLM** (Nguyen et al., 2023) -- unico precedente full-duplex, ma proof-of-concept (no text LLM, no acoustic tokens, non real-time)
- **Spirit-LM** (Nguyen et al., 2024) -- speech-text interleaving con modality switch, MMLU 36.9 vs Moshi 49.7
- **Spectron** (Nachmani et al., 2024) -- Chain-of-Modality, non streaming
- **PSLM** (Mitsui et al., 2024) -- text e speech token in parallelo, ma single-stream
