# A Comprehensive Evaluation of Incremental Speech Recognition and Diarization for Conversational AI

- **Autori**: Addlesee, Yu, Eshghi
- **Anno**: 2020
- **Fonte**: COLING 2020 (28th International Conference on Computational Linguistics)
- **Pagine**: 3492-3503
- **Citazioni**: 14 (dalla query Scopus)
- **Codice**: https://github.com/wallscope-research/incremental-asr-evaluation

## Problema affrontato

I sistemi ASR vengono valutati principalmente con WER non-incrementale (batch), ma per i Spoken Dialogue Systems (SDS) servono metriche diverse. Un ASR per conversational AI deve operare **incrementalmente in tempo reale**, essere **reattivo**, **stabile**, e **robusto** alle caratteristiche peculiari del parlato conversazionale: disfluenze (pause piene, auto-correzioni, edit terms) e sovrapposizioni tra parlanti. Inoltre, in contesti multiparty, serve **speaker diarization (SD)** incrementale per sapere chi sta parlando.

## Sistemi valutati

Tre servizi ASR cloud-based (stato al maggio 2020):
1. **Microsoft Azure Speech to Text**
2. **IBM Watson Speech to Text**
3. **Google Speech to Text**

Per la speaker diarization: solo IBM e Google (Microsoft non offriva SD all'epoca).

## Metriche di valutazione incrementale

### 1. Latenza
- **First Occurrence (FO) latency**: tempo dal momento in cui una parola inizia ad essere pronunciata al momento in cui appare la prima ipotesi ASR
- **Final Decision (FD) latency**: tempo dalla fine della pronuncia di una parola al momento in cui l'ipotesi diventa definitiva (puo essere negativa se il sistema decide prima che la parola sia finita)

### 2. Stabilita (Word Survival Rate - WSR)
- Percentuale di ipotesi che sopravvivono (non vengono cambiate) dopo un certo tempo dalla loro prima emissione
- Un sistema piu stabile cambia meno le proprie ipotesi

### 3. Fedelta al materiale disfluente
- Le disfluenze (pause piene come "uhm", edit terms come "cioe", auto-correzioni) sono informative per la comprensione del linguaggio naturale
- Misurata come **Disfluency WER gain**: se il WER *aumenta* quando si "pulisce" il gold standard, il sistema sta preservando le disfluenze (positivo per SDS)

### 4. Robustezza alle sovrapposizioni di parlato
- **Overlap WER gain**: differenza tra WER su audio combinato (tutti i parlanti) e WER su canali individuali (un parlante ciascuno)
- Minor gain = sistema piu robusto alle sovrapposizioni

## Dataset

1. **Switchboard Corpus (SWB)**: conversazioni telefoniche diadiche in inglese, open-domain, con annotazioni fine-grained di disfluenze. Standard de facto per valutazione ASR.
2. **AVDIAR**: dataset audio-visivo multiparty con conversazioni fino a 4 parlanti. Usato per la valutazione SD in contesto multiparty.

## Risultati principali

### ASR Incrementale (Table 1)

| Metrica | Microsoft | IBM | Google |
|---------|-----------|-----|--------|
| WER incrementale (%) | **32.89** | 35.55 | 33.62 |
| WER non-incrementale (%) | **5.1** | 5.5 | 6.8 |

**Nota critica**: il WER incrementale e ~6x peggiore del non-incrementale per tutti i sistemi. I modelli bidirezionali (non-incrementali) non possono funzionare in tempo reale perche usano token futuri.

### Latenza e Stabilita (Figure 2)

**Microsoft**:
- FO latency: ipotesi quasi immediate (frazioni di secondo)
- FD latency: decisione finale spesso prima che la parola finisca
- Stabilita: ~75% ipotesi non cambiano mai, 95% stabili entro 0.5s
- **Il piu reattivo e stabile complessivamente**

**IBM**:
- FO latency: lento (spesso >1.5s), perche invia ipotesi meno frequentemente (batch di piu parole)
- FD latency: cambia ipotesi anche secondi dopo
- Stabilita: >90% ipotesi non cambiano mai (alta stabilita iniziale, ma a costo di alta latenza)
- **Scelta di design**: sacrifica reattivita per stabilita

**Google**:
- FO latency: di solito <1s, spesso reattivo come Microsoft
- FD latency: simile a Microsoft
- Stabilita: ~65% ipotesi stabili inizialmente, >5% ancora instabili dopo 2.5s
- **Bilanciato** tra i due

### Fedelta alle disfluenze (Table 2)

| Condizione | Microsoft | IBM | Google |
|-----------|-----------|-----|--------|
| Self-corrections (SC) | +4.84 | +5.02 | +3.52 |
| Edit terms (ET) | +0.31 | +0.35 | +0.23 |
| Filled pauses (FP) | **+2.17** | +0.16 | **-0.21** |

- **Microsoft preserva le pause piene** (gain +2.17% su FP)
- **IBM e Google filtrano le pause piene** (IBM quasi neutro, Google le rimuove attivamente)
- Nessun sistema riscrive le auto-correzioni (troppo complesso incrementalmente)
- Nessun sistema filtra significativamente gli edit terms

**Implicazione per SDS**: la preservazione delle disfluenze e importante per la comprensione incrementale del linguaggio naturale. Microsoft e migliore per questo.

### Robustezza alle sovrapposizioni (Table 3)

| Servizio | Max WER Improvement (%) |
|----------|------------------------|
| Microsoft | 19.82 |
| IBM | **14.76** |
| Google | 20.09 |

- **IBM e il piu robusto** alle sovrapposizioni di parlato
- Microsoft e Google sono significativamente peggiori (~20% di degradazione)

### Speaker Diarization (Tables 4-5)

**Switchboard (diadico)**:

| Servizio | DER (%) |
|----------|---------|
| Google | 43.93 |
| IBM | **15.33** |

**AVDIAR (multiparty, fino a 4 speaker)**:

| # Speaker | Google DER | IBM DER |
|-----------|-----------|---------|
| 1 | 56.06 | 39.12 |
| 2 | 66.43 | 41.89 |
| 3 | 75.22 | 49.62 |
| 4 | - (fallito) | 67.32 |
| Overall | 68.79 | **48.94** |

- **IBM nettamente superiore** per SD sia in diadico che multiparty
- Google non riesce nemmeno a gestire conversazioni a 4 parlanti
- **Performance degrada significativamente** al crescere dei parlanti
- Il DER su AVDIAR e molto peggiore che su Switchboard (qualita audio inferiore, distanza dal microfono)

## Conclusioni del paper

1. **Microsoft**: ASR incrementale migliore (piu reattivo, stabile, accurato), preserva disfluenze, ma nessun sistema SD
2. **IBM**: piu robusto a sovrapposizioni, miglior SD incrementale -- adatto per contesti multiparty
3. **Google**: bilanciato tra i due
4. **Nessun sistema e ancora adeguato** per gestire in modo affidabile conversazioni naturali spontanee in tempo reale

## Limiti

- Valutazione del 2020 -- i sistemi sono molto migliorati da allora (specialmente con modelli Whisper, Conformer, etc.)
- Solo sistemi cloud-based (no modelli open-source come Whisper)
- Solo inglese
- Switchboard e telefonico (8kHz) -- non rappresentativo di audio WebRTC moderno
- AVDIAR ha audio di qualita inferiore -- potrebbe penalizzare i risultati
- Non valuta architetture end-to-end o half-cascade (solo pipeline STT tradizionale)
- Non considera l'impatto dell'LLM nella pipeline completa

## Rilevanza per la tesi

**Media-alta**. Questo paper e piu tecnico degli altri e fornisce il background necessario sulle sfide ASR per sistemi speech-based multiparty.

1. **AIutami usa Azure (Microsoft) STT**: questo paper conferma che Azure era il sistema ASR incrementale migliore nel 2020 per reattivita e stabilita. La scelta di AIutami e supportata dalla letteratura.

2. **Il problema delle sovrapposizioni**: AIutami risolve questo problema architetturalmente con l'**ASR gating** -- la trascrizione viene attivata solo per lo speaker corrente, evitando il problema delle sovrapposizioni. Questo e un approccio pratico che bypassa la debolezza identificata da Addlesee (Microsoft perde ~20% WER con overlap). Nella tesi puoi argomentare che il turn-taking esplicito di AIutami ha anche un beneficio tecnico sull'accuratezza ASR.

3. **Speaker diarization**: AIutami non usa diarization tradizionale. Grazie a WebRTC, ogni partecipante ha il proprio stream audio separato -- il "chi sta parlando" e gia noto a livello di architettura. Questo elimina completamente il problema SD che Addlesee identifica come critico per i sistemi multiparty.

4. **Metriche incrementali per la tesi**: le metriche di Addlesee (FO latency, FD latency, WSR, Disfluency WER gain, Overlap WER gain) potrebbero essere usate per valutare le performance ASR di AIutami se si decidesse di fare una valutazione tecnica.

5. **Gap WER incrementale vs non-incrementale**: il paper mostra che il WER incrementale e ~6x peggiore del non-incrementale. Questo e rilevante per la pipeline STT-TTT-TTS: gli errori ASR si propagano nel testo che l'LLM deve interpretare. Il tutor ha suggerito di esplorare architetture alternative (half-cascade, end-to-end) che potrebbero mitigare questo problema.

6. **Collegamento con le architetture speech dal tutor**: il paper si posiziona nel contesto della pipeline STT tradizionale. Le architetture half-cascade e end-to-end che il tutor ha suggerito di esplorare mirano proprio a superare i limiti che Addlesee identifica (latenza, instabilita, perdita di disfluenze).

### Come AIutami bypassa i problemi identificati

| Problema (Addlesee 2020) | Soluzione in AIutami |
|--------------------------|---------------------|
| Sovrapposizioni degradano WER | ASR gating: trascrizione solo per speaker corrente |
| SD inaffidabile per multiparty | WebRTC: stream audio separati per ogni partecipante |
| Latenza ASR incrementale | Azure STT streaming con risultati parziali |
| Disfluenze perse dall'ASR | Non critico: l'LLM downstream e robusto a trascrizioni imperfette |

## Collegamento con gli altri paper letti

- **Addlesee et al. (2024)**: stesso primo autore, 4 anni dopo. Nel 2024 usa un pipeline completa STT-LLM-TTS su un robot sociale. L'evoluzione mostra che le sfide ASR del 2020 sono state parzialmente risolte.
- **Gu et al. (2022)**: il framework WHO/WHAT/WHOM assume che il "WHO" (chi parla) sia risolvibile. Addlesee 2020 mostra quanto sia difficile tecnicamente con SD.
- **Zheng et al. (2022)**: conferma che quasi tutta la ricerca polyadic e text-based. Addlesee 2020 mostra uno dei motivi: le sfide tecniche speech-based (ASR, SD, overlap) sono enormi.

## Paper citati da approfondire

- **Baumann et al. (2016)**: "Recognising conversational speech: What an incremental ASR should do for a dialogue system" -- framework di riferimento per le metriche
- **Schlangen & Skantze (2011)**: modello generale per dialogue processing incrementale
- **Shafey et al. (2019)**: modello joint ASR+SD -- precursore delle architetture end-to-end
