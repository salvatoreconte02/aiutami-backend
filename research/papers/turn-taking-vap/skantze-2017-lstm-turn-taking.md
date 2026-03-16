# Towards a General, Continuous Model of Turn-taking in Spoken Dialogue using LSTM Recurrent Neural Networks

- **Autori**: Gabriel Skantze (KTH, Stockholm)
- **Anno**: 2017
- **Fonte**: SIGDIAL 2017 (Proceedings of the 18th Annual SIGdial Meeting on Discourse and Dialogue)
- **Link/DOI**: ACL Anthology W17-3627

## Problema affrontato

I modelli di turn-taking precedenti erano addestrati per decisioni specifiche (es. distinguere SHIFT da HOLD nelle pause), usando feature engineering manuale su finestre brevi. Mancava un modello **generale** e **continuo** che:
- Non fosse trainato per una singola decisione ma per predire l'attivita vocale futura in generale
- Operasse in modo continuo (ad ogni timestep), non solo in corrispondenza di eventi (es. fine di un IPU)
- Potesse modellare il contesto dialogico a lungo termine senza heuristic manuali

## Approccio

### Modello predittivo continuo con LSTM

Un RNN con un layer LSTM viene addestrato a **predire la probabilita che un parlante parli nei prossimi N frame** (finestra di 3 secondi = 60 frame a 20fps, con frame da 50ms).

- **Input**: feature estratte per ogni frame da entrambi i canali dei parlanti (S0 e S1)
- **Output**: vettore N-dimensionale con probabilita di speech per i prossimi N frame per S0
- **Training**: dati di dialogo umano-umano; per ogni dialogo il modello e addestrato due volte, scambiando i ruoli dei parlanti
- **Applicazione**: due istanze del network in parallelo (una per parlante), le predizioni vengono confrontate per prendere decisioni

### Feature

Due configurazioni testate:
- **Prosody** (12 feature): voice activity (binaria), pitch (relativa, assoluta, voiced flag), power, spectral stability -- per entrambi i parlanti. LSTM con 10 nodi nascosti.
- **Full** (130 feature): tutte le precedenti + POS tags one-hot (59 tag per parlante). LSTM con 40 nodi nascosti.

### Generalita del modello

Il modello non e trainato per una decisione specifica ma per predire attivita vocale futura. Le decisioni concrete (SHIFT/HOLD, SHORT/LONG) vengono derivate a posteriori dalle predizioni, senza re-training.

## Risultati chiave

### Task 1: SHIFT vs HOLD nelle pause (HCRC Map Task corpus)

| Modello | F-score |
|---------|---------|
| Majority class baseline | 0.421 |
| Logistic Regression (solo prosodia) | 0.590 |
| Naive Bayes (tutte le feature) | 0.677 |
| **Osservatori umani** | **0.709** |
| RNN Prosody | 0.724 |
| **RNN Full** | **0.762** |

- Il modello LSTM supera sia i modelli tradizionali sia gli osservatori umani
- Buone performance gia dopo 50ms di pausa (F=0.763), non serve aspettare 500ms
- Bias iniziale verso HOLD (conservativo) -- comportamento desiderabile per un sistema di dialogo

### Task 2: SHORT vs LONG al speech onset

- F-score: **0.786** (Full model)
- Distingue backchannel brevi da utterance lunghe gia all'inizio del parlato
- Superiore a Naive Bayes (0.684)

### Applicazione a dialogo umano-robot

- Applicazione diretta: F-score modesto (0.582) -- gap tra dati di training (umano-umano) e test (umano-robot)
- **Come feature extractor**: F-score 0.751 con Logistic Regression sui nodi nascosti dell'LSTM, anche con solo 20% dei dati di training (F=0.72)

## Limiti

- **Solo dyadico**: testato su conversazioni a 2 parlanti (anche se l'autore nota che il modello e in principio estendibile a multi-party)
- **Corpus limitato**: solo HCRC Map Task (128 dialoghi, 10.7 ore di training), un task-oriented corpus
- **Feature manuali**: richiede estrazione esplicita di pitch, power, spectral stability, POS
- **POS idealizzato**: usa annotazione POS manuale, non ASR automatico
- **Gap umano-umano → umano-robot**: trasferimento diretto non efficace, serve fine-tuning

## Rilevanza per la tesi

**Alta**. Questo paper e il fondamento della linea di ricerca su Voice Activity Projection (VAP) e stabilisce concetti chiave ripresi da TurnGPT e dal modello VAP successivo.

1. **Concetto fondamentale**: il turn-taking puo essere formulato come predizione continua di voice activity futura, non come classificazione binaria ad-hoc. Questo framework e alla base di tutta la ricerca successiva di Skantze/Ekstedt.

2. **Confronto con AIutami**: AIutami usa un turn-taking esplicito con TurnManager e reservation (8 secondi). Il modello di Skantze mostra che un approccio predittivo continuo puo superare le performance umane nel predire chi parlera dopo una pausa.

3. **Applicabilita multi-party**: l'autore nota esplicitamente che il modello e estendibile a multi-party (un'istanza per parlante), ma non lo testa. Questo e un gap rilevante per la tesi.

4. **Feature extractor**: l'idea di usare gli hidden states dell'LSTM come feature per decisioni di turn-taking in sistemi di dialogo e un pattern riutilizzabile.
