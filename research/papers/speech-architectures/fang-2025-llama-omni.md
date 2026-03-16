# LLaMA-Omni: Seamless Speech Interaction with Large Language Models

- **Autori**: Fang, Guo, Zhou, Ma, Zhang, Feng
- **Anno**: 2025
- **Fonte**: ICLR 2025 (conference paper)
- **arXiv**: 2409.06666v2
- **Codice**: https://github.com/ictnlp/LLaMA-Omni
- **Modello**: https://huggingface.co/ICTNLP/Llama-3.1-8B-Omni

## Problema affrontato

Dopo GPT-4o, manca un'esplorazione open-source su come costruire modelli di speech interaction basati su LLM. I sistemi cascaded (ASR + LLM + TTS) hanno latenza elevata perche generano sequenzialmente trascrizione, risposta testuale e risposta vocale. I modelli end-to-end esistenti (SpeechGPT) hanno qualita bassa e latenza comunque alta per via della generazione sequenziale chain-of-modality (prima testo istruzione, poi testo risposta, poi speech).

## Approccio: architettura half-cascade con generazione simultanea text+speech

LLaMA-Omni genera **simultaneamente** risposta testuale e risposta vocale. L'LLM produce testo, e un speech decoder NAR (non-autoregressivo) genera in streaming le discrete units corrispondenti partendo dagli hidden states dell'LLM.

### Componenti

1. **Speech Encoder** (frozen)
   - Whisper-large-v3 encoder
   - Parametri frozen durante tutto il training

2. **Speech Adaptor**
   - Downsampling 5x delle speech representations
   - 2-layer MLP con ReLU
   - Mappa nello spazio embedding dell'LLM

3. **LLM**
   - Llama-3.1-8B-Instruct
   - Fine-tuned (non frozen, a differenza di Freeze-Omni)
   - Genera la risposta testuale direttamente dallo speech input (no trascrizione intermedia)

4. **Speech Decoder** (streaming, NAR)
   - 2 Transformer layers (architettura LLaMA), 4096 hidden, 32 heads, ~425M parametri
   - Input: hidden states dell'LLM, upsampled di fattore lambda=25
   - Output: discrete units via CTC (Connectionist Temporal Classification)
   - Discrete units: HuBERT features quantizzate con K-means (K=1000 clusters)

5. **Vocoder**
   - HiFi-GAN con duration predictor
   - Converte discrete units in waveform

### Training strategy (2 stage)

**Stage 1 -- Speech-to-Text:**
- Speech encoder frozen, adaptor + LLM trainabili
- Loss: cross-entropy sulla text response (L_LLM)
- L'LLM impara a rispondere direttamente dallo speech, senza trascrizione

**Stage 2 -- Text-to-Speech:**
- Speech encoder, adaptor e LLM tutti frozen
- Solo speech decoder trainabile
- Loss: CTC sulla sequenza di discrete units (L_CTC)

Training totale: ~65 ore su 4 NVIDIA L40 GPU.

### Streaming inference

- L'LLM genera testo autoregressivamente
- Ad ogni token testuale, gli hidden states sono upsampled e passati al speech decoder
- Il speech decoder (NAR con causal attention) genera le discrete units in parallelo per ogni chunk
- Quando le units accumulate raggiungono una soglia Omega, vengono inviate al vocoder per sintesi immediata
- Risultato: l'utente inizia a sentire la risposta vocale **prima** che la generazione testuale sia completa

### Dataset: InstructS2S-200K

Costruito in 3 step:
1. **Instruction Rewriting**: istruzioni testuali riscritte con filler words ("hey", "uh", "um"), numeri in forma parlata, brevita (Llama-3-70B-Instruct)
2. **Response Generation**: risposte concise, senza parentesi/liste/formattazione (adatte a speech), generate da Llama-3-70B-Instruct
3. **Speech Synthesis**: istruzioni con CosyVoice-300M-SFT (voci maschili/femminili random), risposte con VITS (voce standard LJSpeech)

200K samples: 50K da Alpaca + 150K da UltraChat (solo primo turno).

## Risultati chiave

**Offline scenario (InstructS2S-Eval, 199 istruzioni):**

| Modello | ChatGPT Score S2TIF | ChatGPT Score S2SIF | ASR-WER | UTMOS |
|---------|---------------------|---------------------|---------|-------|
| SpeechGPT | 2.98 | 2.19 | 45.00 | 3.90 |
| SALMONN + Orca | 3.44 | 3.40 | 3.78 | 3.83 |
| Qwen2-Audio + Orca | 3.47 | 3.38 | 6.77 | 3.61 |
| **LLaMA-Omni** | **3.99** | **3.47** | 10.82 | **3.93** |

**Streaming scenario (latenza minima):**

| Modello | Latenza minima | ChatGPT Score |
|---------|----------------|---------------|
| **LLaMA-Omni** (Omega=10) | **236ms** | 3.54 |
| LLaMA-Omni (Omega=40) | 347ms | 3.52 |
| SALMONN + Orca (Theta=1) | 232ms | 3.28 |
| Qwen2-Audio + Orca (Theta=1) | 309ms | 2.79 |
| SpeechGPT | >4500ms | ~2.2 |
| GPT-4o (riferimento) | 320ms (avg) | - |

- LLaMA-Omni raggiunge **236ms** di latenza, inferiore alla media di GPT-4o (320ms)
- Performance stabile al variare della latenza (speech rate ~2.74 WPS costante)
- I sistemi cascaded (SALMONN/Qwen2-Audio + Orca) a bassa latenza degradano significativamente in qualita e speech rate

**Human evaluation:**
- LLaMA-Omni preferito rispetto ai sistemi cascaded sia per helpfulness che naturalness

## Limiti

- **LLM fine-tuned** (non frozen): a differenza di Freeze-Omni, l'LLM viene aggiornato nello stage 1, potenziale catastrophic forgetting (non valutato)
- **Solo dyadic**: nessun supporto multiparty
- **Solo inglese**: dataset e valutazione solo in inglese
- **Single speaker**: una sola voce per le risposte (VITS su LJSpeech)
- **ASR-WER 10.82%**: piu alto dei sistemi cascaded con TTS industriale (3.78%), indica che l'allineamento speech-text ha margini di miglioramento
- **Nessuna capacita duplex**: il modello non gestisce interruzioni o turni sovrapposti
- **Dataset sintetico**: InstructS2S-200K e interamente generato da LLM + TTS, non da speech reale
- Nessuna valutazione su spoken Q&A benchmark (non confrontabile direttamente con Freeze-Omni su Web Q./LlaMA Q./Trivia QA)

## Classificazione architetturale

| Tipo | Descrizione | LLaMA-Omni? |
|------|-------------|-------------|
| Pipeline STT-TTT-TTS | Componenti separati e indipendenti | No |
| **Half-cascade** | LLM con encoder/decoder speech integrati | **Si** |
| End-to-end | Singolo modello nativo speech-in/speech-out | No |

LLaMA-Omni e un **half-cascade**: il ragionamento avviene in text space (l'LLM genera testo), ma lo speech decoder usa gli hidden states dell'LLM (non il testo output) per generare speech in parallelo. A differenza di un pipeline, non c'e un modulo TTS esterno indipendente.

Differenza con Freeze-Omni: LLaMA-Omni **fine-tuna l'LLM** (stage 1), mentre Freeze-Omni lo tiene frozen. LLaMA-Omni usa **CTC** per l'allineamento speech-text, Freeze-Omni usa un codec AR.

## Rilevanza per la tesi

**Alta**. Punti chiave per la tesi:

1. **Generazione simultanea text+speech**: paradigma interessante -- l'utente riceve speech in tempo reale mentre il modello "pensa" in testo. Potenzialmente applicabile ad AIutami per ridurre la latenza percepita.

2. **Confronto con AIutami**: AIutami ha latenza aggiuntiva perche il TTS (Azure) parte solo dopo che l'LLM ha finito di generare. LLaMA-Omni mostra come la generazione simultanea riduce drasticamente la latenza.

3. **Dataset design per speech interaction**: InstructS2S-200K affronta esplicitamente il problema dello stile delle risposte (concise, senza formattazione, con filler words). Rilevante per la moderazione AI di AIutami che deve produrre risposte "parlabili".

4. **Limite multiparty**: come Freeze-Omni, solo dyadic. Conferma il gap.

5. **Pubblicazione ICLR 2025**: paper peer-reviewed di alto livello, citabile con sicurezza.

### Differenze chiave con AIutami

| Aspetto | LLaMA-Omni | AIutami |
|---------|------------|---------|
| Architettura | Half-cascade (LLM fine-tuned) | Pipeline STT-TTT-TTS |
| LLM | Llama-3.1-8B-Instruct (locale) | Azure OpenAI (cloud) |
| Speech encoder | Whisper-large-v3 (frozen) | Azure STT (servizio) |
| Speech output | NAR decoder + HiFi-GAN vocoder | Azure TTS (servizio) |
| Generazione | Simultanea text+speech | Sequenziale (LLM poi TTS) |
| Latenza | 236ms (streaming) | Dipende da API Azure (stimabile >1s) |
| Multiparty | No | Si (N utenti + 1 AI) |
| Training | 65h su 4 GPU, 200K samples | Nessun training (API) |

### Confronto con Freeze-Omni

| Aspetto | LLaMA-Omni | Freeze-Omni |
|---------|------------|-------------|
| LLM frozen? | No (fine-tuned stage 1) | Si (completamente frozen) |
| Speech decoder | NAR + CTC + HiFi-GAN vocoder | NAR + AR + codec (TiCodec) |
| Spoken Q&A eval | Non valutato | Si (Web Q., LlaMA Q., Trivia QA) |
| Duplex | No | Si (VAD + state prediction) |
| Latenza | 236ms (streaming) | ~1.2s (con rete) |
| Venue | ICLR 2025 | arXiv preprint |

## Paper correlati da approfondire

- **SpeechGPT** (Zhang et al., 2023) -- gia nella lista, baseline principale
- **Moshi** (Defossez et al., 2024) -- gia nella lista, approccio full-duplex
- **Mini-Omni** (Xie & Wu, 2024) -- contemporaneo, streaming speech con LLM
- **CosyVoice** (Du et al., 2024) -- TTS model usato per data construction
- **SALMONN** (Tang et al., 2024) -- speech understanding LLM, baseline
- **Qwen2-Audio** (Chu et al., 2024) -- audio understanding model, baseline
