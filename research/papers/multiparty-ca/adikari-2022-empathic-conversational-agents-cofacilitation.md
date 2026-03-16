# Empathic Conversational Agents for Real-Time Monitoring and Co-Facilitation of Patient-Centered Healthcare

- **Autori**: Adikari, de Silva, Moraliyage, Alahakoon, Wong, Gancarz, Chackochan, Park, Heo, Leung
- **Anno**: 2022 (ricevuto Dic 2020, accettato Ago 2021)
- **Fonte**: Future Generation Computer Systems, Vol. 126, pp. 318-329 (Elsevier)
- **DOI**: 10.1016/j.future.2021.08.015
- **Citazioni**: 51
- **Affiliazione**: La Trobe University (Australia), de Souza Institute (Canada), University of Toronto (Canada)

## Problema affrontato

I modelli di patient-centered care (PCC) si focalizzano sulle dimensioni cliniche (diagnosi, trattamento, recovery) ma trascurano il benessere mentale e emotivo dei pazienti. I gruppi di supporto online per pazienti oncologici sono moderati da terapisti umani, ma questi non riescono a monitorare in tempo reale le emozioni di ogni paziente, le dinamiche di gruppo e i cambiamenti comportamentali. Serve un sistema AI che faccia da **co-facilitatore** al terapista umano, rilevando emozioni, prevedendo transizioni emotive, misurando il comportamento del gruppo e generando risposte empatiche automatizzate.

## Framework proposto (Figure 1)

Un framework per conversational agent empatico con 4 capacita tecniche principali:

### 1. Patient Emotion Analysis
- **Emotion Sequence Extraction**: basata sulle 8 emozioni di Plutchik (anger, fear, sadness, disgust, joy, surprise, trust, anticipation)
- Vocabolario emotivo costruito con ensemble di **Word2Vec** (addestrato sui dati dei pazienti) + **GloVe** (pre-addestrato su Wikipedia/Gigaword) per catturare espressioni emotive sia in-context che out-of-context
- NLP engine che gestisce negazione, intensificatori, tempo verbale (emozioni passate pesano meno)
- **Emotion State Transitions via Markov Chains**: matrice di transizione tra stati emotivi per ogni paziente individualmente. Pazienti con alta probabilita di transizione verso emozioni negative vengono segnalati
- **Emotion Prediction**: Markov model del 2° ordine -- predice l'emozione successiva basandosi sulle ultime 2 emozioni

### 2. Group Emotions
- Rilevamento di espressioni di supporto, empowerment e collaborazione ("we are there for you", "group hug")
- Classificazione binaria (YES/NO) addestrata su 1334 post annotati da clinici
- Ensemble di 3 classificatori (Naive Bayes, MLP, Logistic Regression) con blending (maggioranza 2/3)
- **Group emotion score**: rapporto tra post con emozioni di gruppo e post totali in intervalli di 30 minuti

### 3. Patient Behavioral Metrics
- **Emotion engagement score**: frequenza relativa di post altamente emotivi, menzioni di emozioni di gruppo, e menzioni di concerns
- **Participation score**: volume di contenuto (lunghezza media post, numero medio post)
- I due score combinati tramite **fuzzy integral** (Sugeno lambda-measure) per un **patient behavioral score** complessivo
- Monitorato a intervalli di 10 minuti per identificare pazienti con basso engagement

### 4. Response Generation
- **Negativity threshold** (lambda): probabilita media di transizioni verso emozioni negative
- Se lambda > 0.5 -> trigger di risposta empatica basata su template predefiniti ("Do you want to talk about it more?", "You seem to be feeling down")
- **Resource recommendation**: quando il paziente esprime una concern (grief, fatigue, anxiety, etc.), il sistema suggerisce risorse cliniche rilevanti
- **Co-facilitation updates**: alert in tempo reale al terapista con informazioni sullo stato emotivo del paziente

## Contesto applicativo: Cancer Chat Canada

- **Cancer Chat Canada (CCC)**: gruppi di supporto online text-based, sincroni, moderati da terapisti professionisti per pazienti oncologici e caregiver in 6 province canadesi
- Dataset: **120,000 conversazioni** di 320 pazienti (2016-2017)
- Il chatbot non sostituisce il terapista ma agisce come **co-facilitatore**: "an extra pair of eyes"

## Risultati

### Emotion Detection
- F1 score medio di **0.7** per estrazione emozioni (validato da clinici)
- Errori principali: espressioni idiomatiche, espressioni indirette, riferimenti a esperienze altrui
- Matrici di transizione emotiva create per ogni paziente (Figure 3) -- profili emotivi individuali distinti
- Transizioni temporali a intervalli di 30 minuti (Figure 4) -- visualizzazione granulare dei cambiamenti emotivi durante una sessione

### Group Emotions
- F1 score medio di **0.8** con ensemble di 3 classificatori
- Migliori classificatori: Logistic Regression (F1=0.82), Naive Bayes (F1=0.79), MLP (F1=0.77)
- Score di gruppo calcolato a intervalli di 10 minuti (Figure 5)

### Patient Behavioral Metrics
- Score comportamentali a intervalli di 10 minuti (Figure 6)
- Utili per identificare pazienti con engagement decrescente o fluttuante

### Resource Recommendation
- F1 score di **0.87** per raccomandazione risorse (validato da terapisti)
- Concerns rilevati: grief/loss, depression, fatigue, anxiety, caregiver support, finance, distress

### Emotion Prediction (su dataset Kaggle, 3M messaggi)
- **79%** accuratezza nel predire emozione positiva vs negativa
- **63%** accuratezza nel predire l'emozione specifica corretta
- Accuratezza migliora con piu dati storici: 67.21% (>20 post) -> 72.83% (>30 post)

## Limiti

- Solo **text-based** -- nessun componente speech
- Pre-LLM (2021): usa Word2Vec + GloVe + classificatori classici, non transformer/LLM
- Risposte empatiche basate su **template predefiniti**, non generate dall'AI
- Solo contesto oncologico canadese
- Emotion extraction con F1=0.7 -- margine di miglioramento significativo
- Il framework e un co-facilitatore, non un moderatore autonomo
- Dataset non pubblico per privacy dei pazienti
- Non valuta l'impatto effettivo sul benessere dei pazienti (nessuna user study)

## Rilevanza per la tesi

**Media-alta**. Questo paper e rilevante per il concetto di co-facilitazione AI in contesti di gruppo, anche se il dominio (oncologia) e la modalita (text) sono diversi da AIutami.

1. **Co-facilitazione vs. Moderazione**: Adikari propone l'AI come **co-facilitatore** del terapista umano -- l'AI monitora e segnala, il terapista interviene. AIutami invece ha l'AI come **moderatore autonomo** della discussione. Sono due modelli complementari:
   - Adikari: AI in background, supporto al facilitatore umano
   - AIutami: AI in foreground, moderatore attivo con voce propria
   - Il modello di Adikari e piu conservativo e adatto a contesti clinici sensibili

2. **Emotion monitoring come trigger per interventi**: il "negativity threshold" di Adikari (lambda > 0.5 -> trigger risposta empatica) e concettualmente simile al trigger-based moderation di AIutami. Entrambi i sistemi usano soglie per decidere quando l'AI deve intervenire. La differenza:
   - Adikari: soglia basata su probabilita di transizione emotiva (Markov)
   - AIutami: soglia basata su condizioni temporali e conversazionali (timer, NO_PUSH_THRESHOLD)

3. **Group emotion detection**: il concetto di misurare la "atmosfera" del gruppo e rilevante per AIutami. Il moderatore di AIutami potrebbe beneficiare di un meccanismo simile per capire quando il gruppo sta collaborando bene e quando no.

4. **Patient behavioral metrics**: il punteggio di engagement individuale (partecipazione attiva/passiva) e direttamente collegato al problema che Zheng (2022) identifica come "mancanza di engagement" nelle MPC. AIutami affronta questo con il turn-taking bilanciato e la reservation window.

5. **Gap speech-based confermato**: anche questo paper e completamente text-based. Le tecniche di emotion detection da testo (Word2Vec, classificatori) non sono direttamente applicabili a speech -- servirebbero speech emotion recognition (SER) o analisi del testo trascritto via STT.

6. **Evoluzione tecnologica**: il paper e pre-LLM (2021). Con GPT/Claude, molte delle tecniche proposte (ensemble di classificatori, template predefiniti, Word2Vec per vocabolario emotivo) possono essere sostituite o migliorate da un singolo LLM che genera risposte empatiche contestuali. AIutami usa gia Azure OpenAI per questo.

### Confronto diretto con AIutami

| Aspetto | Adikari (CCC) | AIutami |
|---------|--------------|---------|
| Ruolo AI | Co-facilitatore (background) | Moderatore (foreground) |
| Modalita | Text-based (chat) | Speech-based (WebRTC + TTS) |
| Emotion detection | Word2Vec + GloVe + NLP rules | Non esplicito (l'LLM interpreta il contesto) |
| Trigger intervento | Negativity threshold (Markov, lambda>0.5) | Timer + condizioni conversazionali |
| Risposte | Template predefiniti | Generate dall'LLM in real-time |
| Facilitatore umano | Si, terapista come co-facilitatore | No, AI e il moderatore unico |
| Contesto | Oncologia (support group) | Multi-contesto (murder mystery, terapeutico, accademico) |
| Metriche gruppo | Group emotion score, behavioral score | Non esplicite (summary evolutivo) |
| Pre/Post LLM | Pre-LLM (Word2Vec, classificatori classici) | Post-LLM (Azure OpenAI) |

## Collegamento con gli altri paper letti

- **Zheng et al. (2022)**: le 4 sfide dei polyadic CA (comunicazione inefficiente, mancanza di engagement, mantenimento relazionale, costruzione connessioni) sono tutte affrontate dal framework di Adikari. In particolare, il group emotion monitoring affronta "mantenimento relazionale" e il patient behavioral score affronta "mancanza di engagement".
- **Houde et al. (2025)**: la tassonomia WHEN/WHAT/WHERE di Houde si applica ad Adikari: il "WHEN" e il negativity threshold, il "WHAT" sono le risposte empatiche e le risorse raccomandate, il "WHO has access" e il terapista che riceve gli alert.
- **Addlesee et al. (2024)**: entrambi operano in contesti multi-utente con un facilitatore AI, ma Addlesee e speech-based (robot) e Adikari e text-based (chatbot). AIutami combina elementi di entrambi.
- **Gu et al. (2022)**: il "WHO" di Gu non e rilevante per Adikari (nessuna speaker identification necessaria in text chat), ma il "WHAT" (content modeling) e affrontato dall'emotion extraction e concern detection.

## Paper citati da approfondire

- **Leung et al. (2020)** [16]: "An extra pair of eyes" -- protocollo clinico per il co-facilitatore AI per Cancer Chat Canada
- **Zhou et al. (2020)** [27]: XiaoIce di Microsoft -- social chatbot empatico, identificazione topic/intent/emozioni
- **Lin et al. (2020)** [28]: CAiRE -- chatbot empatico end-to-end
