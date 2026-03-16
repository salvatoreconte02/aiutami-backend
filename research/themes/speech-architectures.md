# Architetture Speech-Based Chatbots

Tema indicato dal tutor: "capire i vari modi per realizzare speech based chatbots"

## Tassonomia

La letteratura usa tre categorie principali (tassonomia consolidata da WavChat, Ji et al. 2024):

1. **Cascaded / Pipeline (STT-TTT-TTS)** -- approccio modulare tradizionale
2. **Half-Cascade / Semi-Cascaded** -- ibridi che fondono 2 dei 3 stadi
3. **End-to-End (Speech-to-Speech)** -- modello unico audio-in audio-out

## 1. STT-TTT-TTS Pipeline (Cascaded)

**Come funziona**: ASR (speech→text) → LLM (text→text) → TTS (text→speech). Ogni componente e indipendente.

**Sistemi chiave**:
- Azure/Google/AWS commercial pipelines
- X-Talk (2025, arXiv:2512.18706) -- dimostra che cascaded ottimizzato resta competitivo
- ESPnet-SDS (NAACL 2025, arXiv:2503.08533) -- toolkit unificato per valutazione
- **AIutami** (Azure Speech STT + Azure OpenAI + Azure TTS)

**Vantaggi**:
- Modulare: ogni componente sostituibile e testabile indipendentemente
- Production-ready, maturo, affidabile
- Testo intermedio interpretabile (logging, moderazione contenuti)
- Costo di training basso (usa componenti pre-addestrati)

**Svantaggi**:
- Latenza cumulativa (2-5s tipico; turni umani ~200ms)
- Error propagation: errori ASR si propagano nell'LLM
- Perde info paralinguistiche (prosodia, emozione, identita speaker)
- No duplex nativo (rigidamente turn-based)

## 2. Half-Cascade / Semi-Cascaded

**Come funziona**: fonde due dei tre stadi. Tre varianti principali:

**Variante A -- Speech-In + LLM** (elimina ASR separato):
L'LLM ingesta direttamente features audio (embedding continui o token discreti). Preserva info prosodiche.
- SALMONN (Tsinghua/ByteDance, ICLR 2024) -- dual encoder Whisper+BEATs → LLM
- Freeze-Omni (2024) -- LLM testuale FROZEN, aggiunge speech encoder/decoder trainabili, <1s latenza

**Variante B -- LLM → Speech-Out** (elimina TTS separato):
L'LLM genera direttamente speech tokens (da neural audio codec).
- LLaMA-Omni (ICT/CAS, ICLR 2025) -- speech encoder + Llama-3.1 + speech decoder streaming
- LLaMA-Omni 2 (ACL 2025) -- Qwen2.5 backbone, 0.5B-14B params, <583ms latenza

**Variante C -- Inner Monologue** (testo interno come scaffold):
Il modello genera testo internamente come passo di ragionamento, poi produce speech tokens. Il testo non e l'interfaccia tra moduli ma uno scaffold per qualita linguistica.
- Moshi (Kyutai, 2024) -- predice testo time-aligned come prefisso ai token audio, frame-by-frame
- SpeechGPT (Fudan, 2023) -- "Chain-of-Modality": speech→text reasoning→speech, tutto in un modello

**Vantaggi**:
- Latenza ridotta vs cascaded (meno stadi sequenziali)
- Comprensione piu ricca (preserva features prosodiche/emotive)
- Sfrutta capacita LLM esistenti (Freeze-Omni tiene LLM frozen)

**Svantaggi**:
- Complessita architetturale e di training
- Rischio degradazione reasoning dell'LLM (catastrophic forgetting)
- Qualita speech generata spesso inferiore a TTS dedicati

## 3. End-to-End (Speech-to-Speech)

**Come funziona**: un solo modello neurale prende speech in input e produce speech in output. Nessuna rappresentazione testuale esplicita intermedia (testo puo esistere internamente per Inner Monologue).

**Tecnologie abilitanti**:
- **Neural Audio Codecs**: convertono speech continuo in token discreti per transformer
  - SoundStream (Google, 2021) -- Residual Vector Quantization (RVQ)
  - EnCodec (Meta, 2022) -- open-source
  - Mimi (Kyutai, 2024) -- 12.5 Hz, streaming, usato da Moshi

**Sistemi chiave**:
- **Moshi** (Kyutai, 2024, arXiv:2410.00037) -- primo full-duplex real-time, 200ms latenza, dual audio streams
- **GPT-4o** (OpenAI, 2024) -- tokenizzazione unificata text/speech/vision, proprietario
- **Gemini 2.5 Native Audio** (Google DeepMind, 2025) -- voce espressiva, 24+ lingue
- **Qwen3-Omni** (Alibaba, 2025) -- architettura Thinker-Talker MoE
- **Kimi Audio** (Moonshot AI, 2025) -- input ibrido continuo/discreto, 13M+ ore pre-training
- **dGSLM** (Meta FAIR, 2022-23) -- primo modello "textless" di dialogo

**Vantaggi**:
- Latenza minima possibile (~200ms, vicino al turn-taking umano)
- Preserva cues paralinguistiche (prosodia, emozione, identita)
- Full-duplex nativo (overlapping speech, backchannels, interruzioni)
- Modellazione olistica della conversazione

**Svantaggi**:
- Reasoning degradato vs LLM text-only di pari dimensione (URO-Bench, EMNLP 2025)
- Costo di training estremamente alto
- Qualita audio spesso inferiore a cascaded (ESPnet-SDS)
- Inaffidabile: hallucination, interruzioni incoerenti ("rude", ICLR 2025)
- Non interpretabile (no testo intermedio per audit)
- **NON production-ready** (X-Talk 2025: "often unsuitable for deployment")

## Confronto

| Aspetto | STT-TTT-TTS (Cascaded) | Half-Cascade | End-to-End (S2S) |
|---------|------------------------|--------------|-----------------|
| Latenza | 2-5s tipico | 0.5-1.5s | 160-500ms |
| Qualita reasoning | Alta (best-in-class LLM) | Buona (rischio degradazione) | Spesso degradata |
| Info paralinguistiche | Perse (bottleneck testuale) | Parzialmente preservate | Completamente preservate |
| Qualita audio output | Alta (TTS dedicato) | Media-alta | Variabile, spesso inferiore |
| Full-duplex | No (workaround ingegneristici) | Limitato | Nativo |
| Modularita | Alta (swap componenti) | Media | Bassa (monolitico) |
| Costo training | Basso | Medio | Molto alto |
| Production-ready | Si (maturo) | In parte | No (2025) |
| Interpretabilita | Alta (testo intermedio) | Media | Bassa |
| Error propagation | ASR errors cascade | Ridotta | Minima |
| **Supporto multiparty** | **Si (AIutami)** | **Non esplorato** | **Non esplorato** |
| Esempi | AIutami, X-Talk, Azure | SALMONN, LLaMA-Omni, Freeze-Omni | Moshi, GPT-4o, Gemini 2.5 |

## Gap critico: multiparty

**Quasi tutti i modelli E2E e half-cascade sono progettati per conversazioni DIADICHE.** Il multiparty speech-based con AI moderatore e praticamente inesplorato -- questo e il contributo di AIutami.

## Survey di riferimento

1. **WavChat** (Ji et al., Nov 2024, arXiv:2411.13577) -- 60pp, survey piu completa su spoken dialogue models
2. **On The Landscape of Spoken Language Models** (Apr 2025, arXiv:2504.08528) -- TMLR
3. **Recent Advances in Speech Language Models** (Oct 2024, arXiv:2410.03751) -- ACL 2025
4. **From Turn-Taking to Synchronous Dialogue** (Sep 2025, arXiv:2509.14515) -- full-duplex models
5. **ESPnet-SDS** (NAACL 2025, arXiv:2503.08533) -- toolkit per valutazione comparativa

## Posizionamento di AIutami

AIutami usa l'architettura cascaded, che e la piu matura e production-ready. La scelta e giustificata perche:
1. E l'unica architettura con supporto multiparty dimostrato
2. La modularita permette di usare servizi enterprise-grade (Azure)
3. Il testo intermedio abilita il logging e la moderazione dei contenuti
4. Il sistema di trigger e il summary evolutivo compensano la mancanza di info paralinguistiche
5. L'ASR gating (trascrizione solo per speaker corrente) mitiga l'error propagation

Possibile direzione futura: evoluzione verso semi-cascaded (speech encoder → LLM per preservare prosodia) mantenendo il turn-taking esplicito per il multiparty.
