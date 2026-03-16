# UX Research on Conversational Human-AI Interaction: A Literature Review of the ACM Digital Library

- **Autori**: Zheng, Tang, Liu, Liu, Huang
- **Anno**: 2022
- **Fonte**: CHI '22 (Conference on Human Factors in Computing Systems)
- **DOI**: 10.1145/3491102.3501855
- **Citazioni**: 87
- **Pagine**: 25

## Problema affrontato

Le literature review esistenti sui conversational agent (CA) coprono solo interazioni **dyadic** (1 utente + 1 agente). Manca una mappatura sistematica dei CA **polyadic**, cioe quelli che mediano interazioni umano-umano con piu utenti nella stessa conversazione. Questo paper colma il gap analizzando 36 paper polyadic e 135 dyadic dall'ACM Digital Library.

## Definizioni chiave

- **Dyadic CA**: interazione one-to-one tra un umano e un CA (es. Siri, Alexa, chatbot customer service)
- **Polyadic CA**: CA che interagiscono con piu di un utente e supportano anche interazioni umano-umano. Encompassano **hybrid social interactions**: human-CA, human-to-human, human-to-group

## Sfide fondamentali delle interazioni umano-umano che i polyadic CA affrontano (RQ1)

1. **Comunicazione inefficiente**: discussioni non strutturate, difficolta a raggiungere consenso, topic drift, gestione task complessa
2. **Mancanza di engagement**: partecipazione diseguale, difficolta a coinvolgere tutti, engagement passivo
3. **Barriere nel mantenimento relazionale**: mancanza di consapevolezza emotiva, difficolta nel regolare emozioni di gruppo, trust-building
4. **Necessita di costruire connessioni**: ice-breaking, trovare common ground, sfide cross-culturali

## Pratiche di design dei polyadic CA (RQ3)

### Domini applicativi
- Education/collaborative learning (8 paper)
- Work/productivity (7)
- Online communities (5)
- Group discussions (3)
- Guiding services (3)
- Virtual meetings (2)
- Games (2)
- Family (1)

### Modalita
- Text-only: 22 paper (maggioranza)
- Video: 9
- Audio only: pochi
- Ibrido audio-text: pochi

### Scala sociale
- Due individui: 18 paper
- Multi-user (3+): 18 paper (da piccoli gruppi di 3-5 a comunita online)

### Tipi di relazione
Co-learner, co-worker, collaborator, sconosciuti, membri di comunita online, visitatori, co-player, familiari

## Effetti provati dei polyadic CA (RQ4)

### 1. Efficienza comunicativa
- Aiutano a raggiungere consenso
- Migliorano comprensione (tagging, summarization)
- Gestione task e coordinamento (es. scheduling CA)

### 2. Group engagement
- Incoraggiano partecipazione attiva
- **Bilanciano partecipazione diseguale**: nudging dei membri meno attivi, downplay dei "talkative"
- Generano diversita di contenuto e opinioni

### 3. Mantenimento relazionale
- Monitorano sentimento delle conversazioni
- Regolano emozioni di gruppo
- "Ripple Effect": un agente che mostra vulnerabilita genera trust-related behaviors nel team

### 4. Costruzione di connessioni
- L'agreement/disagreement del CA influenza la percezione reciproca dei partner
- Potenziale per ice-breaking in conversazioni cross-culturali

## Metriche di valutazione (RQ5)

### Per polyadic CA:
**Log analysis**: discussion quality, consensus reaching, even participation, opinion diversity, team performance
**Survey**: communication effectiveness/fairness/efficiency, perceived group climate, social presence, perception of other members, anthropomorphism
**Interview**: perceived capability to promote contributions, overall UX, reflections on selves and others

### Differenze chiave polyadic vs dyadic:
- **Polyadic** focus su: group discussion, social behavior, education, embodied design
- **Dyadic** focus su: user-agent interaction, conversational design

## Problemi trascurati nei polyadic CA (RQ6)

### 1. "Visible" -- I CA devono essere visibili
- Gli utenti devono essere consapevoli della presenza del CA nel gruppo
- Il CA deve "annunciarsi" e rimanere visibile

### 2. "Ignorable" -- I CA devono essere ignorabili
- Se il CA e troppo persistente con i suoi interventi, l'effetto puo essere controproducente
- Gli studenti a volte ignorano o danno risposte frettolose al CA tutor
- Task reminder percepiti come invasivi, "too frequent", "not context sensitive"

### 3. "Accountable" -- I CA devono essere responsabili
- Chi "possiede" il CA? A chi e accountable?
- Come gestire conflitti interpersonali?
- Quale posizione prende il CA in caso di disaccordo?

## Proposta: Boundary-Awareness

Il paper propone il concetto di **boundary-awareness** per i polyadic CA:
- **Disclosure boundary**: gestire cosa il CA rende pubblico o privato
- **Temporal boundary**: gestire le aspettative nel tempo (passato, presente, futuro)
- **Identity boundary**: gestire il confine tra se e altri

I polyadic CA sono **unici da progettare** rispetto ai dyadic: per i dyadic conta la human-likeness (empatia, self-disclosure), per i polyadic contano i **social boundaries**.

## Limiti del paper

- Solo fonte ACM (no IEEE, Scopus, Web of Science)
- Focus su paper con user evaluation (esclude contributi puramente tecnici)
- Pre-LLM (2022) -- non copre l'era GPT/ChatGPT
- Soggettivita dell'analisi tematica
- Quasi tutti i paper polyadic sono **text-based** -- pochissimi speech-based

## Rilevanza per la tesi

**Molto alta**. Questo paper fornisce:

1. **Framework dyadic vs polyadic**: AIutami e un polyadic CA speech-based. Questo framework ti permette di posizionarlo chiaramente nella letteratura.

2. **Le 4 sfide delle interazioni umano-umano**: AIutami le affronta tutte:
   - Comunicazione inefficiente -> moderatore AI che fa summary e gestisce flusso
   - Mancanza di engagement -> turn-taking con reservation window che bilancia partecipazione
   - Mantenimento relazionale -> AI che monitora e interviene quando necessario
   - Costruzione connessioni -> contesti tematici (murder mystery, terapeutico) che facilitano il dialogo

3. **Il problema "Ignorable"**: direttamente rilevante per AIutami. Il tuo sistema ha trigger-based intervention e moderation-in-progress. Zheng et al. dicono che gli interventi troppo frequenti o non contestuali sono controproducenti -- il tuo sistema di trigger con soglie temporali affronta proprio questo.

4. **Il problema "Visible"**: AIutami rende il moderatore AI visibile come partecipante con voice (TTS). E una scelta di design importante.

5. **Boundary-awareness**: il moderatore di AIutami deve capire quando intervenire e quando no. Le soglie (NO_PUSH_THRESHOLD, timer-based triggers) sono una forma primitiva di boundary-awareness.

6. **Gap speech-based**: il paper conferma che quasi tutta la ricerca polyadic e text-based. Un polyadic CA speech-based con LLM (come AIutami) e un contributo originale.

7. **Metriche di valutazione**: la tabella delle metriche (Appendix A.1) e utilissima se nella tesi dovrai valutare il sistema con user study.

## Collegamento con gli altri paper letti

- **Gu et al. (2022)**: complementare. Gu copre il lato tecnico/NLP delle MPC (context modeling, component modeling). Zheng copre il lato UX/HCI.
- **Addlesee et al. (2024)**: sistema polyadic speech-based, ma non analizzato con il framework di Zheng. Potenziale per confronto.
- **Kim et al. (2020, 2021)**: citati come moderator chatbot per group discussion -- direttamente confrontabile con il ruolo di AIutami.

## Paper citati da approfondire

- **Kim et al. (2020)** [76]: "Bot in the Bunch" -- chatbot che facilita group chat, bilancia efficienza e partecipazione
- **Kim et al. (2021)** [77]: "Moderator Chatbot for Deliberative Discussion" -- effetti della struttura di discussione e facilitazione
- **Shamekhi et al. (2018)** [155]: "Face Value?" -- effetti dell'embodiment per un group facilitation agent
- **Seering et al. (2019)** [153]: "Beyond dyadic interactions" -- chatbot come community members
