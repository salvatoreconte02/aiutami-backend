# TurnGPT: a Transformer-based Language Model for Predicting Turn-taking in Spoken Dialog

- **Autori**: Erik Ekstedt, Gabriel Skantze (KTH, Stockholm)
- **Anno**: 2020
- **Fonte**: Findings of EMNLP 2020
- **Link/DOI**: ACL Anthology, Findings of EMNLP 2020
- **Codice**: https://github.com/ErikEkstedt/TurnGPT

## Problema affrontato

I modelli di turn-taking precedenti usavano rappresentazioni linguistiche semplicistiche (POS tags, parole singole) che non catturavano la **completezza pragmatica** delle utterance -- ovvero se un'unita conversazionale e realmente "finita" nel contesto del dialogo. La completezza sintattica (es. "when will you meet") non implica completezza pragmatica (la domanda non e finita senza "again"). Serviva un modello linguistico piu potente per catturare queste distinzioni contestuali.

## Approccio

### Formulazione come language modeling

Il turn-taking viene formulato come task di language modeling: i turni dei parlanti vengono concatenati con token speciali di speaker-shift (`<speaker1>`, `<speaker2>`) inseriti all'inizio di ogni turno. Il modello impara la distribuzione di probabilita di questi token di turno insieme a tutti gli altri token.

- La probabilita associata ai token di turn-shift rappresenta la probabilita di un **Transition-Relevant Place (TRP)**
- Approccio **probabilistico** (non binario) ai TRP: la transition-relevance e un continuo, non un si/no

### Architettura: GPT-2 fine-tuned

- Base: GPT-2 (Radford et al., 2019) o DialoGPT (Zhang et al., 2019)
- Modelli small: 12 layers, 12 heads, 768 hidden units
- Tre tipi di embedding: word, position, speaker id
- Fine-tuned su dataset di dialogo con cross-entropy loss
- Solo feature linguistiche (parole) -- nessuna prosodia

### Dataset (8 corpora)

| Categoria | Dataset | # Dialoghi |
|-----------|---------|------------|
| Assistant (task-oriented) | Taskmaster, MultiWoZ, MetaLWoZ, CCPE | 30.4K-37.9K |
| Written Social | Persona, DailyDialog | 10.9K-13.1K |
| Spontaneous Spoken | Maptask, Switchboard | 128-2.4K |

### Baseline

- **POS bigrams**: modello statistico su coppie di POS tags consecutive
- **LSTM** (fino a 3 layer, 768 hidden): classificatore binario di turn-shift

## Risultati chiave

### Performance (balanced accuracy)

| Modello | Assistant | Spoken | Written |
|---------|-----------|--------|---------|
| POS bigrams | 0.750 | 0.675 | 0.732 |
| LSTM | 0.869 | 0.748 | 0.830 |
| **TurnGPT** | **0.913** | **0.823** | **0.906** |

- TurnGPT supera entrambe le baseline su tutti i dataset
- GPT-2 e DialoGPT danno risultati simili
- Performance migliore quando si include training su tutti i dataset (Full)
- I dialoghi spontanei (Spoken) sono piu difficili da predire

### Context ablation

- La performance migliora con piu contesto (da 0 a 4 turni precedenti)
- Il calo maggiore avviene passando da "qualche contesto" a "nessun contesto"
- L'LSTM beneficia meno del contesto rispetto a TurnGPT

### Analisi del modello

- **Attention analysis**: ~70% dell'attenzione e sul turno corrente, il restante 30% sui turni precedenti -- contributo sostanziale del contesto
- **Integrated Gradient**: il turno corrente contribuisce positivamente alla predizione di turn-shift; i turni precedenti contribuiscono negativamente (riducono la probabilita), possibilmente perche forniscono evidenza che una completezza sintattica non e una completezza pragmatica
- **Esempio chiave**: "yesterday" a inizio turno ha bassa probabilita TRP (servono altre informazioni); "tomorrow" come risposta alla domanda "when will you meet again?" ha alta probabilita TRP -- il modello cattura la completezza pragmatica

### Future projection

- Il modello puo generare testo autoregressivamente e contare i token fino al prossimo speaker-token
- Permette di **proiettare** (non solo rilevare) la fine del turno, dando al sistema tempo per preparare la risposta

## Limiti

- **Solo feature linguistiche**: nessuna prosodia, gaze o gesture -- gli autori lo riconoscono esplicitamente come passo intermedio
- **Dipende da trascrizione**: richiede parole (da ASR o trascrizione), non opera direttamente su audio
- **Nessuna valutazione real-time**: testato offline su trascrizioni, non in un sistema di dialogo funzionante
- **Solo dyadico**: tutti i dataset sono conversazioni a 2 parlanti
- **Punteggiatura rimossa**: la rimozione di punteggiatura simula condizioni ASR ma potrebbe perdere informazione

## Rilevanza per la tesi

**Alta**. TurnGPT connette il turn-taking alla ricerca sui language model (GPT), creando un ponte tra NLP e analisi conversazionale.

1. **Turn-taking come language modeling**: l'idea che i TRP possano essere appresi come distribuzione di probabilita in un language model e elegante e scalabile. Nella tesi questo approccio puo essere confrontato con il turn-taking esplicito di AIutami.

2. **Completezza pragmatica**: il paper fornisce evidenza empirica che la comprensione del contesto dialogico (non solo della sintassi) e cruciale per il turn-taking. Questo e rilevante perche in un setting multiparty il contesto e ancora piu complesso.

3. **Evoluzione della linea di ricerca**: Skantze 2017 (LSTM) → TurnGPT 2020 (Transformer, solo testo) → VAP 2022 (audio + VA, self-supervised). TurnGPT e il passo intermedio che motiva il passaggio a modelli multimodali.

4. **Gap multiparty**: come il paper precedente, testato solo su dialogo dyadico. L'estensione a conversazioni multiparty (dove i TRP dipendono da N parlanti e da chi seleziona il prossimo speaker) non e esplorata.

5. **Future projection**: la capacita di proiettare la fine del turno (non solo rilevarla) e particolarmente rilevante per sistemi real-time come AIutami, dove il sistema deve preparare la risposta in anticipo.
