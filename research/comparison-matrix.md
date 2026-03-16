# Tabella Comparativa Integrata

Confronto trasversale di tutti i paper analizzati nella literature review.
18 contributi da 19 pubblicazioni (Addlesee 2024 HRI e EACL descrivono lo stesso sistema).
Aggiornato dopo verifica sistematica contro la letteratura (marzo 2026).

---

## Tabella 1: Panoramica generale

| # | Paper | Anno | Venue | Tipo | Tema |
|---|-------|------|-------|------|------|
| 1 | Defossez et al. (Moshi) | 2024 | arXiv | Sistema | Speech Architecture |
| 2 | Fang et al. (LLaMA-Omni) | 2025 | ICLR | Sistema | Speech Architecture |
| 3 | Wang et al. (Freeze-Omni) | 2024 | arXiv | Sistema | Speech Architecture |
| 4 | Zhang et al. (SpeechGPT) | 2023 | EMNLP Findings | Sistema | Speech Architecture |
| 5 | Huang et al. (WavChat) | 2024 | arXiv | Survey | Speech Architecture |
| 6 | Ekstedt & Skantze (VAP) | 2022 | arXiv | Modello | Turn-Taking |
| 7 | Ekstedt & Skantze (TurnGPT) | 2020 | EMNLP Findings | Modello | Turn-Taking |
| 8 | Skantze (LSTM) | 2017 | SIGDIAL | Modello | Turn-Taking |
| 9 | Houde et al. (Koala) | 2025 | IUI | Empirico (2 studi) | Multiparty CA |
| 10 | Addlesee et al. (ARI Robot) | 2024 | HRI + EACL | System Demo | Multiparty CA |
| 11 | Addlesee et al. (ASR eval) | 2020 | COLING | Empirico | Multiparty CA |
| 12 | Gu et al. (WHO/WHAT/WHOM) | 2022 | IJCAI | Survey | Multiparty CA |
| 13 | Adikari et al. (Co-facilitator) | 2022 | FGCS (Elsevier) | Framework | Multiparty CA |
| 14 | Zheng et al. (Polyadic UX) | 2022 | CHI | Literature Review | Multiparty CA |
| 15 | Wahlster (Dialogue History) | 2023 | Phil Trans R Soc | Review | Multiparty CA |
| 16 | Axelsson et al. (Furhat Robot) | 2025 | arXiv (2503.15496) | Sistema | Multiparty CA |
| 17 | MPCA Survey | 2025 | arXiv (2505.18845) | Survey | Multiparty CA |
| 18 | Hu et al. (DialogLab) | 2025 | UIST | Tool | Multiparty CA |

---

## Tabella 2: Dimensioni chiave

| # | Paper | Modalita | Architettura | Diadico / Multiparty | LLM | Deployment |
|---|-------|----------|-------------|----------------------|-----|------------|
| 1 | Moshi | Speech | End-to-End | Diadico (2 stream) | Helium 7B (custom, aggiornato) | Demo pubblica |
| 2 | LLaMA-Omni | Speech | Half-Cascade | Diadico | Llama-3.1-8B (fine-tuned) | Open-source |
| 3 | Freeze-Omni | Speech | Half-Cascade | Diadico | Qwen2-7B (frozen) | Demo |
| 4 | SpeechGPT | Speech | End-to-End | Diadico | LLaMA-13B (fine-tuned) | Open-source |
| 5 | WavChat | -- (survey) | Copre tutte | Diadico (assunto) | Copre tutti | -- |
| 6 | VAP | Speech (audio) | -- (modello TT) | Diadico (2 parlanti) | No LLM | Offline |
| 7 | TurnGPT | Testo (trascrizioni) | -- (modello TT) | Diadico | GPT-2 / DialoGPT (fine-tuned) | Offline |
| 8 | Skantze LSTM | Speech (prosodia) | -- (modello TT) | Diadico | No LLM | Offline + robot |
| 9 | Koala | Testo (Slack) | -- (bot) | **Multiparty** (3+1) | Llama 2 → Llama 3 | Prototipo interno IBM |
| 10 | ARI Robot | Speech + gaze + gesti | Cascaded (STT-LLM-TTS) | **Multiparty** (2+1) | Vicuna-13b (locale) | Deployato in ospedale |
| 11 | ASR eval | Speech | -- (valutazione ASR) | **Multiparty** (fino a 4) | No LLM | -- (benchmark) |
| 12 | WHO/WHAT/WHOM | Testo | -- (survey) | **Multiparty** | Copre vari | -- |
| 13 | Co-facilitator | Testo (chat) | -- (framework) | **Multiparty** (N+AI+terapista) | No LLM (pre-LLM) | Prototipo |
| 14 | Polyadic UX | Testo (prevalente) | -- (review) | **Multiparty** | -- | -- |
| 15 | Wahlster | Multimodale | -- (review) | **Multiparty** (VIRTUAL HUMAN) | No LLM (pre-LLM) | Storico |
| 16 | Furhat Robot | Speech + gaze + gesti | Cascaded (STT-LLM-TTS) | **Multiparty** (2+1) | GPT-3.5 (cloud) | Prototipo (lab) |
| 17 | MPCA Survey | -- (survey) | -- | **Multiparty** | Copre vari | -- |
| 18 | DialogLab | Misto (authoring tool) | -- | **Multiparty** | GPT-based | Tool open-source |
| -- | **AIutami** | **Speech (WebRTC)** | **Cascaded (STT-LLM-TTS)** | **Multiparty (N+1)** | **Azure OpenAI (cloud)** | **Deployato (web)** |

---

## Tabella 3: Confronto tecnico (solo sistemi con implementazione)

| Sistema | Architettura | Latenza | Turn-Taking | Full-Duplex | Info Paralinguistiche | Multiparty |
|---------|-------------|---------|-------------|-------------|----------------------|------------|
| Moshi | E2E | ~200ms | Implicito (multi-stream) | Si | Preservate (audio nativo) | No |
| LLaMA-Omni | Half-Cascade | 236ms | No (single-turn) | No | Parziali (speech encoder) | No |
| Freeze-Omni | Half-Cascade | ~1.2s | VAD + state prediction | Parziale | Parziali (speech encoder) | No |
| SpeechGPT | E2E | >4500ms | No (chain-of-modality sequenziale) | No | Perse (HuBERT discretizza) | No |
| Koala | -- (text bot) | N/A (testo) | Implicito (text-based) | N/A | N/A (testo) | **Si** (3+1) |
| ARI Robot | Cascaded | Non misurata | Addressee detection (gaze+LLM, 85.4%) | No | Parziali (gaze, gesti) | **Si** (2+1) |
| Furhat Robot | Cascaded | 1.35s media | Gaze-based (92.6% con gaze, 26.8% audio-only) | No | Parziali (gaze, gesti) | **Si** (2+1) |
| Co-facilitator | -- (text) | N/A (testo) | N/A (chat asincrona) | N/A | N/A (testo) | **Si** (N) |
| VIRTUAL HUMAN | Simbolico | Non misurata | Multi-modal rules | No | Si (avatar, gesti) | **Si** (2+3) |
| **AIutami** | **Cascaded** | **Dipende da API Azure** | **Esplicito (request + reservation 8s)** | **No** | **Perse (bottleneck testo)** | **Si (N+1)** |

---

## Tabella 4: Confronto multiparty (solo paper sul tema)

| Paper | Modalita | N partecipanti | Ruolo AI | Meccanismo WHEN | Controllo utente | Addressee | Contesto |
|-------|----------|---------------|----------|-----------------|-----------------|-----------|----------|
| Koala (Houde 2025) | Testo | 3 umani + 1 AI | Partecipante/contributor | Self-scoring LLM (soglia 0-100) | Pannello in-session (soglia, dove, ruolo) | Keyword (@Koala) | Brainstorming aziendale |
| ARI (Addlesee 2024) | Speech+gaze | 2 umani + 1 robot | Receptionist/intrattenitore | Addressee detection (gaze+LLM) | Nessuno | Gaze + testo (85.4%) | Memory clinic ospedaliera |
| Furhat (Axelsson 2025) | Speech+gaze | 2 umani + 1 robot | Partner conversazionale | Gaze + silenzio prolungato | Nessuno | Gaze (92.6%), audio-only (26.8%) | Open-ended |
| Co-facilitator (Adikari 2022) | Testo | N umani + AI + terapista | Co-facilitatore (background) | Negativity threshold (Markov, lambda>0.5) | Nessuno (uso terapista) | N/A (chat di gruppo) | Oncologia (support group) |
| VIRTUAL HUMAN (Wahlster) | Multimodale | 2 umani + 3 agenti | Moderatore + esperti | Regole simboliche | Nessuno | Multi-modal rules | Quiz sportivo |
| **AIutami** | **Speech** | **N umani + 1 AI** | **Moderatore attivo** | **Trigger-based (timer + condizioni)** | **Config iniziale sessione** | **Bypass (moderatore → gruppo)** | **Multi-contesto** |

---

## Tabella 5: Confronto turn-taking

| Approccio | Paper | Input | Output | Multiparty | Scalabilita | Real-time |
|-----------|-------|-------|--------|------------|-------------|-----------|
| LSTM predittivo | Skantze (2017) | Prosodia + POS (manual features) | P(speech) per N frame futuri, bin indipendenti | In teoria estendibile, non testato | 1 istanza per parlante | Si (continuo a 20fps) |
| Transformer linguistico | TurnGPT (2020) | Testo (trascrizioni) | P(turn-shift) per ogni token | Non testato | Limitato dal context window | Offline (dipende da ASR) |
| Voice Activity Projection | VAP (2022) | Audio raw + VA history | Distribuzione su 256 stati (bin dipendenti) | No -- 2^(4N) stati per N parlanti | Esplode esponenzialmente | Si (ogni 10ms) |
| Multi-stream implicito | Moshi (2024) | 2 stream audio tokenizzati | Audio output continuo (full-duplex) | No (esattamente 2 stream) | Non estendibile a N stream | Si (12.5Hz, 200ms) |
| VAD + state prediction | Freeze-Omni (2024) | Chunk audio | 3 stati (continua/rispondi/ignora) | No (1 utente) | Solo diadico | Si (chunk-wise) |
| Addressee detection | ARI Robot (2024) | Testo ASR + gaze | Binario (robot e addressee?) | Limitato (2 umani + 1 robot) | Dipende da gaze hardware | Si |
| Gaze-based | Furhat Robot (2025) | Gaze + voice direction | Binario (robot guardato + silenzio) | Limitato (2 umani + 1 robot) | Dipende da gaze hardware | Si |
| **Esplicito con reservation** | **AIutami** | **Richiesta utente (WebSocket)** | **Turno assegnato + reservation 8s** | **Si (N partecipanti)** | **Lineare con N** | **Si** |

---

## Tabella 6: Copertura dei gap per paper

Quali paper toccano (direttamente o indirettamente) ciascun gap identificato.

| Gap | Moshi | LLaMA-O | Freeze-O | SpeechGPT | WavChat | VAP | TurnGPT | Skantze17 | Koala | ARI | Furhat | ASR eval | WHO/WHAT | Co-facil | Polyadic UX | Wahlster | MPCA Surv | AIutami |
|-----|-------|---------|----------|-----------|---------|-----|---------|-----------|-------|-----|--------|----------|----------|----------|-------------|----------|-----------|---------|
| **G1** Multiparty speech+AI | | | | | | | | | | ~ | ~ | | | | | ~ | ~ | **X** |
| **G2** E2E/half-cascade per multiparty | ~ | ~ | ~ | ~ | ~ | | | | | | | | | | | | | |
| **G3** Tassonomia design speech multiparty | | | | | | | | | ~ | | | | | | ~ | | | |
| **G4** Addressee audio-only N>2 | | | | | | | | | | ~ | **X** | | ~ | | | | | |
| **G5** Controllo dinamico in speech | | | | | | | | | **X** | | | | | | ~ | | | |
| **G6** Utterance incomplete multiparty | | | | | | | | | | **X** | | ~ | | | | | | |
| **G7** Benchmark multiparty speech CA | | | | | | | | | | | | ~ | | | ~ | | **X** | |
| **G8** Proattivita in speech | | | | | | | | | **X** | | | | | | **X** | | | ~ |

Legenda: **X** = affronta direttamente | ~ = tocca indirettamente o identifica il problema | (vuoto) = non coperto

Nota: Furhat (2025) e marcato **X** su G4 perche fornisce evidenza quantitativa diretta (26.8% audio-only vs 92.6% con gaze). MPCA Survey (2025) e marcato **X** su G7 perche identifica esplicitamente le limitazioni dei benchmark attuali.

---

## Tabella 7: Posizionamento -- le due dimensioni chiave

```
                          TEXT-BASED                    SPEECH-BASED
                    ┌────────────────────────────┬────────────────────────────┐
                    │                            │                            │
    DIADICO         │  (ampia letteratura)       │  Moshi (2024)              │
    (1 umano +      │  ChatGPT, Siri, Alexa      │  LLaMA-Omni (2025)         │
     1 AI)          │  TurnGPT (2020)            │  Freeze-Omni (2024)        │
                    │                            │  SpeechGPT (2023)          │
                    │                            │  VAP (2022)                │
                    │                            │  Skantze (2017)            │
                    ├────────────────────────────┼────────────────────────────┤
                    │                            │                            │
    MULTIPARTY      │  Koala (Houde, 2025)       │                            │
    (N umani +      │  Co-facilitator (2022)     │    ★ AIutami ★             │
     1+ AI)         │  WHO/WHAT/WHOM (Gu, 2022)  │    ARI Robot (2024)        │
                    │  Polyadic UX (Zheng, 2022) │    Furhat Robot (2025)     │
                    │  MMAgents (2025)           │    (entrambi 2+1, con gaze)│
                    │  DialogLab (2025)          │                            │
                    │  Kim et al. (2020, 2021)   │    ASR eval (Addlesee 2020)│
                    │  VIRTUAL HUMAN (Wahlster)  │    (solo valutazione)      │
                    │                            │                            │
                    └────────────────────────────┴────────────────────────────┘
```

Il quadrante **multiparty + speech-based** e estremamente scarso. I soli 2 sistemi (ARI, Furhat) hanno entrambi: solo 2 umani, dipendenza da gaze/video, AI non moderatrice.

AIutami e l'unico sistema che combina:
- Speech (non testo)
- N partecipanti (non solo 2+1)
- Audio-only (non dipende da gaze/video)
- AI come moderatore attivo (non receptionist o partner)
- LLM-based (non regole simboliche)

---

## Note per le slide

Questa matrice puo generare almeno 4 slide:

1. **Slide "Panoramica letteratura"** → Tabella 1 semplificata (18 paper, venue, tema)
2. **Slide "Il quadrante quasi vuoto"** → Tabella 7 (la matrice 2x2 text/speech x diadico/multiparty)
3. **Slide "Confronto architetture"** → Tabella 3 (latenza, turn-taking, full-duplex, multiparty)
4. **Slide "Gap e direzioni"** → Tabella 6 semplificata (8 gap, copertura)

## Nota sulla validazione (marzo 2026)

I gap sono stati verificati contro la letteratura piu recente tramite ricerca su arXiv, ACM, Scopus, IEEE. Paper aggiunti dopo la verifica:
- **Furhat Robot (Axelsson et al., 2025)**: sfuma GAP 1 (non siamo gli unici speech multiparty) ma conferma GAP 4 (audio-only 26.8%)
- **MPCA Survey (arXiv:2505.18845, 2025)**: valida GAP 7 (conferma mancanza benchmark multimodali)
- **DialogLab (Google, UIST 2025)**: rilevante per GAP 3 (tool di design, non tassonomia)
- **MMAgents (Frontiers, 2025)**: text-based multi-agent, non impatta i gap speech
- **SD-Eval (NeurIPS 2024)** e **Full-Duplex-Bench (2025)**: benchmark spoken dialogue diadici, confermano GAP 7
