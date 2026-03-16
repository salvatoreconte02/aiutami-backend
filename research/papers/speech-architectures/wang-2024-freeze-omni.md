# Freeze-Omni: A Smart and Low Latency Speech-to-speech Dialogue Model with Frozen LLM

- **Autori**: Wang, Li, Fu, Shen, Xie, Li, Sun, Ma
- **Anno**: 2024
- **Fonte**: arXiv preprint (Tencent Youtu Lab / ASLP@NPU / Nanjing University)
- **DOI/arXiv**: 2411.00774v5
- **Codice/Demo**: https://freeze-omni.github.io/

## Problema affrontato

Il fine-tuning dell'LLM per integrare la modalita speech causa **catastrophic forgetting**: l'LLM perde "intelligenza" rispetto alla versione solo-testo. I modelli speech-to-speech esistenti (Moshi, LLaMA-Omni, Mini-Omni2, SpeechGPT) richiedono tutti di aggiornare i parametri dell'LLM, con dati speech Q&A difficili da raccogliere su larga scala. Risultato: gap evidente tra performance spoken Q&A e text Q&A.

## Approccio: architettura "half-cascade" con LLM frozen

Freeze-Omni connette speech encoder e speech decoder a un LLM testuale **senza mai aggiornarne i parametri**. Classificabile come approccio **half-cascade**: l'LLM rimane un modello testuale, ma encoder/decoder speech sono integrati strutturalmente (non sono componenti esterni indipendenti come in una pipeline STT+LLM+TTS classica).

### Componenti

1. **Speech Encoder** (streaming, chunk-wise)
   - Conv layers (4x downsampling) + 24 Transformer layers (hidden 1024) + adapter (2x downsampling)
   - ~350M parametri, output frame rate 12.5Hz
   - Input: mel-filter bank (25ms window, 10ms shift)

2. **LLM backbone** (frozen)
   - Qwen2-7B-Instruct negli esperimenti
   - Compatibile con qualsiasi LLM testuale (plug-and-play)

3. **Speech Decoder** (token-based, streaming)
   - NAR Prefix Decoder → NAR Speech Decoder → AR Speech Decoder → Codec Decoder
   - Codec: TiCodec single-codebook (1024 entries), speech token rate 40Hz, output 24kHz
   - NAR e AR decoder: 4-layer Llama decoder (hidden 896), ~120M parametri

### Training strategy (3+3 stages)

**Speech Input (3 stage):**
1. Speech encoder con CTC loss (ASR classico) su 110k ore di dati ASR (cinese+inglese)
2. Encoder + adapter connessi all'LLM frozen, label = transcript, special tokens trainabili
3. Solo **prompt embedding** trainabili + LLM frozen + encoder frozen. Dati: 60k multi-round Q&A (testo generato dall'LLM stesso, speech sintetizzato con TTS). Questo mantiene l'intelligenza dell'LLM intatta.

**Speech Output (3 stage):**
1. Training del codec model (TiCodec single-codebook) su dati speech (~3k ore)
2. NAR + AR decoder trainati su text-speech paired data; input = text tokens dall'embedding layer dell'LLM (frozen)
3. **Prefix kv-cache fine-tune**: NAR Prefix Decoder (unico componente trainabile) modella gli hidden states dell'LLM e passa kv-cache al NAR decoder. Colma il gap tra stile del testo generico (stage 2) e stile dell'output dell'LLM.

### Duplex dialogue

- VAD esterno (Silero VAD) rileva inizio speech
- Audio inviato chunk-by-chunk all'LLM
- Classification layer aggiunto dopo ultimo layer dell'LLM predice 3 stati per chunk:
  - **State 0**: continua a ricevere speech
  - **State 1**: utente ha finito, LLM deve rispondere (interruzione)
  - **State 2**: utente ha finito, non serve risposta
- "Model as a server": piu istanze del modello in parallelo, kv-cache separati per utente, qualsiasi istanza risponde a qualsiasi chunk

## Risultati chiave

**ASR (speech input):**
- aishell-1: 2.48% CER, LibriSpeech test-clean: 3.82% WER -- competitivo con Mini-Omni2

**Speech output (CER su 1000 utterances):**
- Con prefix + pre-network: 1.69% CER (top-k=2) -- significativo miglioramento rispetto a senza prefix (4.64%)

**Spoken Question Answering (risultato piu importante):**

| Modello | Web Q. | LlaMA Q. | Trivia QA |
|---------|--------|----------|-----------|
| SpeechGPT (7B) | 6.5 | 21.6 | 14.8 |
| Moshi (7B) | 26.6 | 62.3 | 22.8 |
| GLM-4-Voice (9B) | 32.2 | 64.7 | 39.1 |
| **Freeze-Omni (7B)** | **44.73** | **72** | **53.88** |
| Qwen2-7B (text only) | 45.13 | 77.67 | 63.93 |

- Gap Freeze-Omni vs backbone LLM testuale: minimo (~0.4% su Web Q., ~5.7% su LlaMA Q., ~10% su Trivia QA)
- Gap Moshi vs suo backbone (Helium): molto piu ampio -- conferma che il frozen LLM preserva l'intelligenza

**Latenza end-to-end:**
- Latenza statistica media: **745ms** (mediana 753ms, p90 1020ms)
- Con latenza non-statistica (160-320ms) + rete (200-300ms): ~**1.2 secondi** in scenari reali
- Breakdown: LLM generate (478ms) + prefill decoder (15ms) + generate speech tokens (237ms) + decode PCM (11ms)

## Limiti

- **Solo dyadic**: testato solo in conversazione 1-a-1 (utente + agente), nessun supporto multiparty
- **Single speaker output**: un solo parlante per il decoder, nessun multi-voice
- Richiede 110k ore di dati ASR per stage 1-2 dell'encoder (risorse non banali)
- Il codec single-codebook limita la qualita/espressivita della voce sintetizzata
- Nessuna valutazione su naturalezza/prosodia dell'output speech (solo CER)
- Latenza ~1.2s ancora percepibile rispetto a conversazione umana naturale (~200-500ms)
- Duplex dialogue basato su VAD + state prediction chunk-wise -- approccio semplificato rispetto a veri modelli full-duplex come Moshi

## Classificazione architetturale

Nella tassonomia delle architetture speech-based chatbot:

| Tipo | Descrizione | Freeze-Omni? |
|------|-------------|--------------|
| **Pipeline STT-TTT-TTS** | Componenti completamente separati e indipendenti | No |
| **Half-cascade** | LLM testuale con encoder/decoder speech integrati strutturalmente | **Si** |
| **End-to-end** | Singolo modello nativo speech-in/speech-out | No |

Freeze-Omni e un **half-cascade**: l'LLM ragiona in text space ma encoder e decoder sono accoppiati strutturalmente (hidden states, kv-cache), non sono servizi esterni. La differenza chiave con un pipeline e che il decoder usa gli hidden states dell'LLM (non solo il testo output).

## Rilevanza per la tesi

**Alta**. Freeze-Omni rappresenta un punto intermedio molto interessante nello spettro architetturale:

1. **Confronto con AIutami**: AIutami usa un pipeline STT-TTT-TTS classico (Azure STT → Azure OpenAI → Azure TTS). Freeze-Omni mostra come si puo evolvere verso un'integrazione piu stretta senza perdere l'intelligenza dell'LLM.

2. **Argomento forte per il frozen LLM**: I risultati di spoken Q&A dimostrano quantitativamente che mantenere l'LLM frozen preserva l'intelligenza -- argomento importante per la tesi quando si discute il trade-off tra architetture.

3. **Latenza**: Il paper fornisce un breakdown dettagliato della latenza (745ms statistici), utile per confrontare con la latenza di AIutami (che ha latenza aggiuntiva per network WebRTC + Azure API calls).

4. **Limite multiparty**: Come quasi tutti i modelli di questa categoria, Freeze-Omni e solo dyadic. Questo rafforza il gap identificato nella tesi: le architetture speech-to-speech avanzate non affrontano il caso multiparty.

### Differenze chiave con AIutami

| Aspetto | Freeze-Omni | AIutami |
|---------|-------------|---------|
| Architettura | Half-cascade (LLM frozen) | Pipeline STT-TTT-TTS |
| LLM | Qwen2-7B locale (frozen) | Azure OpenAI (cloud) |
| Speech input | Encoder integrato (350M params) | Azure STT (servizio esterno) |
| Speech output | Decoder integrato (120M params) | Azure TTS (servizio esterno) |
| Latenza e2e | ~1.2s | Dipende da latenza API Azure |
| Duplex | VAD + state prediction | Turn-taking esplicito con reservation |
| Multiparty | No | Si (N utenti + 1 AI moderator) |
| Training | 8 GPU, 60k Q&A + 110k ore ASR | Nessun training (usa API) |

## Paper correlati da approfondire

- **Moshi** (Defossez et al., 2024) -- gia nella lista, approccio end-to-end full-duplex
- **LLaMA-Omni** (Fang et al., 2024) -- gia nella lista, approccio simile ma con LLM fine-tuned
- **SpeechGPT** (Zhang et al., 2023) -- gia nella lista, approccio end-to-end
- **GLM-4-Voice** (Zeng et al., 2024) -- non nella lista, risultati competitivi (9B params)
- **Mini-Omni / Mini-Omni2** (Xie & Wu, 2024) -- approccio streaming con duplex
- **VALL-E 2** (Chen et al., 2024) -- codec language model per TTS, ispira il decoder di Freeze-Omni
