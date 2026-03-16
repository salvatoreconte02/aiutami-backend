# Voice Activity Projection: Self-supervised Learning of Turn-taking Events

- **Autori**: Erik Ekstedt, Gabriel Skantze (KTH, Stockholm)
- **Anno**: 2022
- **Fonte**: arXiv preprint (2205.09812v1)
- **Link/DOI**: arXiv 2205.09812
- **Codice**: https://github.com/ErikEkstedt/vap_turn_taking

## Problema affrontato

I modelli di turn-taking precedenti (incluso Skantze 2017) predicevano la voice activity (VA) futura di ciascun parlante con bin **indipendenti** -- ogni bin modellato separatamente. Questo ha una debolezza teorica: le probabilita dei singoli bin non possono essere combinate in modo statisticamente corretto per modellare lo stato futuro della conversazione come un tutt'uno. Ad esempio, se ogni bin ha probabilita 0.5, non e chiaro se cio significhi che tutti gli stati futuri sono equiprobabili, o se stati fuori distribuzione (es. "un bin si, uno no, alternati") siano ugualmente probabili.

## Approccio

### Voice Activity Projection (VAP) come task self-supervised

VAP e definito come il task di **predire la voice activity futura di ciascun interlocutore** in un dialogo. E un obiettivo self-supervised: non richiede annotazioni manuali, i label vengono derivati direttamente dalla VA osservata.

### Modello Discrete (contributo principale)

- **Finestra di proiezione**: 2 secondi nel futuro, divisi in 4 bin di durata crescente (200, 400, 600, 800ms) per ciascuno dei 2 parlanti
- **Stato VAP**: 4 bin × 2 parlanti = 8 bit → **256 stati possibili**
- Il modello predice una **distribuzione di probabilita sui 256 stati**, modellando le dipendenze tra bin (a differenza del modello Independent che tratta ogni bin separatamente)
- Loss: cross-entropy sui 256 stati

### Architettura

- **Speech encoder**: CPC pre-trained, output 256-dim a 100Hz su waveform raw
- **VA module**: processa VA frame corrente (binario, 2-dim) + VA history (rapporto di attivita su finestre di {-inf:60, 60:30, 30:10, 10:5, 5:0} secondi)
- **Predictor**: Transformer causale (decoder-only), 256 hidden, 4 layer, 4 head
- **VAP-head**: layer lineare finale che produce logits per i 256 stati
- Input: audio mono (waveform dei 2 parlanti mixati in un singolo canale)

### Modelli di confronto

| Modello | Output | Dipendenza tra bin |
|---------|--------|-------------------|
| **Discrete (proposto)** | 256 stati (distribuzione) | Si (completa) |
| Independent | 2×4 bin (probabilita indipendenti) | No |
| Independent-40 | 2×40 bin (come Skantze 2017) | No |
| Comparative | Scalare (rapporto VA) | N/A |

### Zero-shot tasks (4 task senza training aggiuntivo)

Le predizioni del modello vengono mappate direttamente a classi rilevanti, senza fine-tuning:

1. **SHIFT vs HOLD (S/H)**: durante un silenzio mutuo, predire se il turno passera all'altro parlante o se il parlante corrente continuera
2. **SHIFT prediction (S-pred)**: predire un imminente cambio di turno **prima** che avvenga (500ms prima della fine del VA del parlante corrente) -- task nuovo
3. **Backchannel prediction (BC-pred)**: predire un imminente backchannel **prima** che avvenga -- task nuovo
4. **SHORT vs LONG (S/L)**: all'inizio di un segmento VA, distinguere se sara un backchannel breve o un'utterance lunga

### Training

- Dataset: **Switchboard** (2438 dialoghi telefonici)
- 11-fold cross-validation (2000 train / 205 validation, 135 test)
- Audio: volume normalized, 16kHz, mono
- Chunk: 10s con 2s overlap
- Early stopping su weighted F1 di S/H

## Risultati chiave

| Task | Discrete (proposto) | Independent | Ind-40 | Comparative |
|------|-------------------|-------------|--------|-------------|
| S/H | .899 | .897 | .896 | .893 |
| S/L | .786 | .786 | .778 | .546 |
| **S-pred** | **.733*** | .718 | .712 | .714 |
| **BC-pred** | **.723*** | .685 | .661 | N/A |

(*) = miglioramento statisticamente significativo (p < 0.025)

- Su S/H e S/L: performance comparabili tra modelli (il task e "facile")
- Su **S-pred e BC-pred** (task predittivi, piu complessi): il modello Discrete e significativamente migliore
- Il miglioramento maggiore e su **BC-pred**, il task con le dipendenze piu complesse tra gli stati futuri dei parlanti
- Conferma che modellare le dipendenze tra bin e cruciale per task predittivi complessi

## Limiti

- **Solo dyadico**: il framework e definito per 2 parlanti (2^8 = 256 stati). L'estensione a N parlanti causa crescita esponenziale degli stati (4 bin × N parlanti = 2^(4N) stati)
- **Solo Switchboard**: un singolo corpus di conversazioni telefoniche in inglese
- **Audio mono**: i due canali vengono mixati in un singolo canale, il modello deve disambiguare i parlanti
- **Nessuna feature linguistica**: opera solo su audio + VA, senza testo (complementare a TurnGPT che usa solo testo)
- **Zero-shot evaluation**: non testato in un sistema di dialogo reale, solo valutazione offline

## Rilevanza per la tesi

**Molto alta**. VAP e il modello piu maturo e recente nella linea di ricerca Skantze/Ekstedt sul turn-taking, e sintetizza le lezioni dei paper precedenti.

1. **Turn-taking come predizione di voice activity**: il framework VAP formalizza il turn-taking come predizione self-supervised di VA futura. E un paradigma alternativo sia al turn-taking esplicito di AIutami (reservation + TurnManager) sia al turn-taking implicito di Moshi (multi-stream senza turni).

2. **Evoluzione della linea di ricerca**:
   - Skantze 2017 (LSTM, feature manuali, bin indipendenti)
   - TurnGPT 2020 (Transformer, solo testo, TRP come token)
   - **VAP 2022** (Transformer, audio raw + VA, bin dipendenti, self-supervised)

3. **Scalabilita multiparty**: la crescita esponenziale degli stati (2^(4N)) e un problema fondamentale per l'estensione a multi-party. Nella tesi si puo discutere come gestire questo: gerarchie, approssimazioni, o formulazioni alternative.

4. **Complementarita con i modelli end-to-end**: Moshi elimina il turn-taking esplicito con multi-stream; VAP lo modella esplicitamente come predizione. La tesi puo confrontare questi due paradigmi e discutere quale sia piu adatto a conversazioni multiparty.

5. **Backchannel prediction**: la capacita di predire backchannel e particolarmente rilevante per un moderatore AI in conversazioni di gruppo (come AIutami), dove il sistema deve decidere se/quando dare feedback senza interrompere.

### Confronto approcci al turn-taking

| Aspetto | AIutami | VAP (Ekstedt 2022) | Moshi |
|---------|---------|-------------------|-------|
| Paradigma | Esplicito (regole + reservation) | Predittivo (VA futura) | Implicito (multi-stream) |
| Input | Nessuno (gestione turni manuale) | Audio + VA history | Audio tokenizzato |
| Granularita | Turno intero | Frame-level (ogni 10ms) | Frame-level (12.5Hz) |
| Multiparty | Si (N utenti + AI) | No (solo 2 parlanti) | No (solo 2 stream) |
| Backchannel | No | Si (predizione) | Si (modellato implicitamente) |
| Self-supervised | N/A | Si | No (supervised multi-stage) |
