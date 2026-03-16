# SpeechGPT: Empowering Large Language Models with Intrinsic Cross-Modal Conversational Abilities

- **Autori**: Zhang, Li, Zhang, Zhan, Wang, Zhou, Qiu
- **Anno**: 2023
- **Fonte**: Findings of EMNLP 2023 (peer-reviewed)
- **Pagine**: 15757-15773
- **Codice**: https://github.com/0nutation/SpeechGPT

## Problema affrontato

I modelli speech-language esistenti adottano il paradigma **cascaded** (ASR + LLM + TTS), con tre limiti: (1) nessun trasferimento di conoscenza inter-modale -- l'LLM funziona solo come generatore di contenuto testuale, (2) perdita di segnali paralinguistici (emozione, prosodia) nel passaggio speech→text→speech, (3) i modelli generativi di spoken language (AudioLM, VALL-E) sintetizzano speech ma non comprendono la semantica. Manca un LLM **nativo** capace sia di percepire che generare speech.

## Approccio: LLM end-to-end con speech tokens nel vocabolario

SpeechGPT e il **primo** LLM multimodale che percepisce e genera speech trattando lo speech come sequenza di token discreti nel vocabolario dell'LLM stesso. Approccio **end-to-end**: un unico modello gestisce input/output in entrambe le modalita (text e speech).

### Componenti

1. **Discrete Unit Extractor**
   - HuBERT (mHuBERT multilingual) per convertire speech continuo in discrete units
   - K-means clustering sulle rappresentazioni intermedie di HuBERT
   - Rimozione indici duplicati adiacenti → sequenza ridotta

2. **Large Language Model**
   - LLaMA-13B (Touvron et al., 2023)
   - Vocabolario espanso con K token speech aggiuntivi
   - Embedding matrix estesa per i nuovi token

3. **Unit Vocoder**
   - HiFi-GAN multi-speaker
   - Converte discrete units → waveform
   - Speaker embedding per supportare piu voci

### Training strategy (3 stage)

**Stage 1: Modality-Adaptation Pre-training**
- Pre-training su LibriLight (60K ore di speech non etichettato)
- Task: next-token prediction su sequenze di discrete units
- Obiettivo: l'LLM impara a "capire" la distribuzione dei token speech
- 96 A100 GPU, 900 steps, batch size 768, tutti i 13B parametri trainabili

**Stage 2: Cross-modal Instruction Fine-Tuning**
- Dataset: SpeechInstruct (Cross-Modal Instruction) -- 9M coppie unit-text da Gigaspeech, Common Voice, LibriSpeech + dati testo da moss-002-sft
- Task: ASR (speech→text) e TTS (text→speech) con 100 diverse descrizioni per task generate da GPT-4
- 96 A100 GPU, 4000 steps, batch size 1536

**Stage 3: Chain-of-Modality Instruction Fine-Tuning**
- **Innovazione chiave**: Chain-of-Modality (CoM) prompting
  - Speech input → [tq] trascrizione testo → [ta] risposta testo → [ua] risposta speech
  - Decompone il task complesso (speech→speech) in sotto-task piu semplici
- 37,969 quadruple (SpeechI, TextI, TextR, SpeechR) da moss-002-sft
- Fine-tuning con **LoRA** (rank 8, alpha 16) -- solo 6M parametri trainabili
- 8 A100 GPU, 4200 steps

### Dataset: SpeechInstruct

Due parti:
1. **Cross-Modal Instruction**: 9M coppie unit-text per task ASR/TTS
2. **Chain-of-Modality Instruction**: 37,969 quadruple per 4 formati (S→S, S→T, T→S, T→T)

Evaluation set: 100 campioni in 6 ruoli (enciclopedia, assistente, chat partner, poeta, psicologo, educatore).

## Risultati chiave

**Main results (100 test samples, ChatGPT Score 1-5):**

| Modello | S2SIF | S2TIF | T2SIF | T2TIF |
|---------|-------|-------|-------|-------|
| Speech-Alpaca-13B (cascaded) | 2.74 | 3.31 | 2.71 | 3.83 |
| Speech-LLaMA-MOSS (cascaded) | 2.87 | 3.50 | 3.23 | 3.82 |
| **SpeechGPT** | **3.42** | **3.52** | **3.53** | 3.64 |

- SpeechGPT supera i sistemi cascaded su task con speech input (S2SIF, S2TIF)
- NMOS (naturalness) significativamente piu alto dei cascaded (3.65 vs 3.12-3.14 su S2SIF)

**Chain-of-Modality prompting e fondamentale:**

| Training | Inference | ChatGPT Score (S2SIF) |
|----------|-----------|----------------------|
| Standard | Standard | 2.15 |
| Standard | CoM | 2.12 |
| CoM | Standard | 2.35 |
| **CoM** | **CoM** | **3.42** |

- Senza CoM, performance molto bassa (2.15) -- il mapping diretto speech→speech e troppo complesso
- CoM necessario sia in training che inference

**Trasferimento di conoscenza text→speech:**
- Modello inizializzato da LLaMA ha ASR-PPL consistentemente piu basso del modello from-scratch
- Conferma: la conoscenza testuale dell'LLM beneficia la modalita speech

**Text capability preservata:**
- A 40K samples di training, SpeechGPT raggiunge performance T2TIF simile a LLaMA-MOSS-002
- Nessun catastrophic forgetting significativo (attribuito ai 13B parametri)

## Limiti

- **Latenza molto alta**: la generazione Chain-of-Modality e sequenziale (prima testo trascritto, poi testo risposta, poi speech units) → latenza >4500ms misurata da LLaMA-Omni
- **No paralinguistic info**: la discretizzazione HuBERT perde emozione/prosodia
- **Max sequence length**: una singola risposta speech puo saturare il context window (2048 token), impedendo multi-turn
- **Risorse massive**: stage 1-2 richiedono 96 A100 GPU
- **Solo inglese**
- **Solo dyadic**: nessun supporto multiparty
- **Qualita speech limitata**: ASR-WER 45% misurata da LLaMA-Omni (molto alto)
- **Risposte brevi**: per stare nel context window, le risposte sono limitate a ~35 parole

## Classificazione architetturale

| Tipo | Descrizione | SpeechGPT? |
|------|-------------|------------|
| Pipeline STT-TTT-TTS | Componenti separati | No |
| Half-cascade | LLM testuale + encoder/decoder speech | No |
| **End-to-end** | Singolo modello nativo speech-in/speech-out | **Si** |

SpeechGPT e un vero **end-to-end**: speech tokens sono nel vocabolario dell'LLM, che li gestisce nativamente come testo. Non ci sono encoder/decoder speech separati (solo un discretizzatore in input e un vocoder in output).

**Pero** in pratica usa Chain-of-Modality che e concettualmente simile a un pipeline interno: l'LLM prima trascrive (ASR interno), poi ragiona in testo (LLM), poi genera speech tokens (TTS interno). La differenza e che tutto avviene in un singolo modello con un unico forward pass autoregressivo.

## Rilevanza per la tesi

**Media-alta**. Importanza storica come primo tentativo, ma superato da modelli successivi.

1. **Primo LLM speech end-to-end**: fondamentale come riferimento storico nella literature review. Definisce il paradigma "speech tokens nel vocabolario LLM".

2. **Chain-of-Modality**: insight importante -- la generazione diretta speech→speech e troppo difficile, il passaggio intermedio per testo migliora enormemente la qualita. Questo vale anche per AIutami che usa esplicitamente il testo come intermediario.

3. **Baseline per confronti**: SpeechGPT e usato come baseline da Freeze-Omni e LLaMA-Omni, i cui risultati mostrano quanto sia stato superato (ChatGPT Score S2SIF: SpeechGPT 2.19 vs LLaMA-Omni 3.47, ASR-WER: 45% vs 10.82%).

4. **Trasferimento text→speech**: la dimostrazione che la conoscenza testuale beneficia lo speech e un argomento per l'approccio half-cascade (dove l'LLM testuale e il "cervello").

5. **Limite multiparty**: come tutti, solo dyadic.

### Confronto con AIutami

| Aspetto | SpeechGPT | AIutami |
|---------|-----------|---------|
| Architettura | End-to-end (speech tokens in LLM vocab) | Pipeline STT-TTT-TTS |
| LLM | LLaMA-13B (fine-tuned) | Azure OpenAI (cloud) |
| Speech I/O | Discrete units (HuBERT) nel vocabolario | Azure STT/TTS (servizi) |
| Chain-of-Modality | Si (interno al modello) | Si (pipeline esplicita esterna) |
| Latenza | >4500ms | Dipende da API Azure |
| Multiparty | No | Si |
| Risorse | 96 A100 GPU | Nessun training |

## Paper correlati da approfondire

- **SpeechGPT-Gen** (Zhang et al., 2024) -- evoluzione con chain-of-information per qualita migliore
- **AudioPaLM** (Rubenstein et al., 2023) -- approccio simile da Google
- **AnyGPT** (Zhan et al., 2024) -- multimodale unificato con discrete tokens
- **AudioLM** (Borsos et al., 2022) -- generative spoken language model pre-LLM
- **HuggingGPT/AudioGPT** -- approcci cascaded basati su hub di modelli
