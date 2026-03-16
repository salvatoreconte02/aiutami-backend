# WHO Says WHAT to WHOM: A Survey of Multi-Party Conversations

- **Autori**: Jia-Chen Gu, Chongyang Tao, Zhen-Hua Ling
- **Anno**: 2022
- **Fonte**: IJCAI-22 (Survey Track)
- **DOI**: 10.24963/ijcai.2022/768
- **Citazioni**: 33

## Problema affrontato

Manca un survey aggiornato sulle conversazioni multiparty (MPCs). L'ultimo survey sistematico era Traum 2004. La maggior parte della ricerca si concentra su conversazioni a due (TPC), ma le MPC sono piu pratiche e complesse.

## Differenza fondamentale TPC vs MPC

- **TPC**: flusso informativo sequenziale -- due persone si alternano linearmente
- **MPC**: flusso informativo a grafo -- ogni utterance puo essere detta da chiunque e indirizzata a chiunque, creando strutture parallele (piu sotto-conversazioni simultanee)

## Tassonomia proposta

Il paper organizza la ricerca MPC in due macro-categorie:

### 1. Conversational Context Modeling (come modellare il contesto)

**Discourse Parsing**
- Analizzare le relazioni tra utterance (reply-to, clarification, elaboration, acknowledgement)
- Dataset di riferimento: STAC corpus (gioco Settlers of Catan)
- Approcci: ILP per decoding globale, neural models, edge-centric GNN (SOTA: Wang et al. 2021)

**Information Flow**
- **Sequenziale**: trattare MPC come sequenza di utterance (limitato, non cattura relazioni parallele tipo U3 e U4 che rispondono entrambe a U2)
- **A grafo**: modellare MPC con topologia a grafo
  - Grafi omogenei (solo utterance come nodi)
  - Grafi eterogenei (utterance + interlocutori come nodi, con edge type-dependent) -- SOTA: Lee & Choi 2021

**Self-supervision**
- Pre-training: post-training di PLM con MLM/NSP su dati MPC, poi fine-tuning su task specifici (es. MPC-BERT)
- Auxiliary training: task ausiliari (topic prediction, topic disentanglement, speaker prediction) allenati insieme al task principale

### 2. Conversational Component Modeling (WHO says WHAT to WHOM)

**WHO Speaks (Speaker Modeling)**
- *Turn-taking (utterance-unaware)*: predire il prossimo speaker basandosi solo sulla storia. Approcci: CRF, FSA rule-based, ML (MLE, SVM, CNN, LSTM)
- *Speaker identification (utterance-aware)*: identificare chi ha detto cosa, condizionato sulla semantica dell'utterance. Include speaker segmentation e speaker change detection.

**Say WHAT (Utterance Modeling)**
- *Retrieval-based*: selezionare la risposta migliore da un set di candidati. Key: matching semantico tra contesto MPC e risposta. SOTA: TopicBERT (Wang et al. 2020) con dynamic topic tracking
- *Generation-based*: generare risposte con NLG. Approcci: encoder-decoder con interlocutor-aware context (ICRED), graph-structured neural networks (GSN), grafi eterogenei (HeterMPC -- SOTA: Gu et al. 2022)

**Address WHOM (Addressee Modeling)**
- *Esplicito (Addressee Recognition)*: predire il destinatario di un'utterance. Evoluzione: da predire solo l'ultimo addressee a predire tutti gli addressee della conversazione. SOTA: MPC-BERT
- *Implicito (Dialogue Disentanglement)*: separare conversazioni intrecciate in thread distinti. Dataset chiave: #Linux IRC, #Ubuntu IRC (Kummerfeld et al. 2019, 16x piu grande dei precedenti). SOTA: pointer networks (Yu & Joty 2020)

## Open Challenges identificati

1. **Universal MPC Understanding**: i modelli sono progettati per task singoli, ma i task sono complementari. Servono modelli unificati che gestiscano discourse parsing + turn-taking + addressee recognition insieme. Servono anche topic tracking dinamico e tracking di sotto-conversazioni parallele a granularita fine.

2. **Modeling Heterogeneity**: tendenza a usare grafi omogenei (solo utterance). Servono grafi eterogenei che includano speaker, addressee, e relazioni type-dependent.

3. **High-level MPC Applications**: summarization e reading comprehension in MPC sono difficili perche le informazioni chiave sono sparse tra utterance di interlocutori diversi, con topic drift e bassa densita informativa. Servono sistemi cross-domain.

4. **Low/Zero-resource MPC Modeling**: annotare dataset MPC e costoso. Transfer learning da domini accessibili a domini scarsi non e ancora esplorato per MPC (solo per TPC).

## Limiti del paper

- Focus esclusivamente su **text-based** MPC -- non copre speech-based
- Non tratta aspetti multimodali (audio, video, gesti)
- Non copre LLM moderni (il paper e del 2022, pre-ChatGPT)
- I dataset discussi sono quasi tutti in inglese o cinese

## Rilevanza per la tesi

**Molto alta**. Questo paper fornisce:

1. **La mappa concettuale** del campo MPC: la tassonomia WHO/WHAT/WHOM e direttamente applicabile per posizionare AIutami nella letteratura
2. **Il gap principale** che conferma il tema della tesi: tutta la ricerca e text-based. L'estensione a speech-based MPC e un'area inesplorata
3. **Collegamento con AIutami**:
   - Il turn-taking di AIutami (reservation window + moderation-in-progress) e un approccio rule-based simile al FSA di de Bayser et al.
   - L'addressee modeling in AIutami e implicito (il moderatore AI parla al gruppo, non a un singolo)
   - La response generation in AIutami e generation-based (LLM) ma con trigger-based decision-making, non puramente generativa
4. **Open challenges rilevanti**: il gap su speech-based + il challenge su universal MPC understanding sono esattamente dove si posiziona la tesi

## Paper citati da approfondire

- **de Bayser et al. (2018, 2019)**: sistema "finch" con turn-taking FSA per chatbot multiparty -- confrontabile con AIutami
- **MPC-BERT (Gu et al. 2021)**: pre-training per MPC understanding
- **Kummerfeld et al. (2019)**: dataset Ubuntu IRC per dialogue disentanglement
- **Traum (2004)**: il survey originale sulle MPC -- utile per background storico
