# Gap nella Letteratura

Scopo (dal tutor): "capire cosa non e stato fatto e vale la pena approfondire"

## Gap identificati

### GAP 1: Multiparty speech-based con AI moderatore -- il quadrante quasi vuoto

**Il gap centrale della tesi.** La letteratura si divide in:
- Multiparty text-based con AI: Koala (Houde 2025), Kim et al. (2020/2021), Adikari (2022), MMAgents (2025)
- Diadico speech-based con AI: Moshi, GPT-4o, LLaMA-Omni, Freeze-Omni
- Multiparty speech-based con AI: **estremamente scarso** -- solo Addlesee (2024) con 2 umani + 1 robot e Furhat robot (Axelsson et al., 2025) con 2 umani + 1 robot

Entrambi i sistemi multiparty speech-based esistenti hanno limitazioni significative: solo 2 utenti umani, dipendenza da gaze/video per l'addressee detection, e l'AI non agisce come moderatore (receptionist in Addlesee, partner conversazionale in Furhat). Nessun sistema combina: speech-based + N partecipanti + AI come moderatore attivo + LLM.

Il survey MPCA (arXiv:2505.18845, 2025) conferma indirettamente questo gap: non distingue sistematicamente tra sistemi text-based e speech-based, segnalando che la dimensione speech e sottorappresentata nella letteratura multiparty.

**Fonti**: Gu (2022) copre solo text-based; Zheng (2022) conferma che quasi tutti i polyadic CA sono text-based; tutti i modelli E2E e half-cascade (WavChat survey, 2024) sono diadici; Axelsson et al. (2025) e Addlesee (2024) sono gli unici 2 sistemi multiparty speech ma con 2+1 partecipanti e dipendenza da gaze.

**Validazione**: gap confermato da ricerca sistematica (marzo 2026) su Scopus, arXiv, ACM, IEEE. Nessun sistema trovato che occupi la stessa posizione di AIutami.

---

### GAP 2: Architetture speech E2E / half-cascade per il multiparty

I modelli speech-to-speech recenti (Moshi, GPT-4o, LLaMA-Omni, Freeze-Omni, Qwen3-Omni) sono progettati esclusivamente per conversazioni diadiche. Non esiste ricerca su come adattare queste architetture al multiparty, dove servono:
- Gestione di N stream audio in ingresso
- Speaker diarization o stream separati
- Turn-taking tra N partecipanti (non solo "io parlo, tu rispondi")
- Decisione di **quando** e **a chi** rispondere

L'unica architettura con supporto multiparty dimostrato e la pipeline cascaded (STT-TTT-TTS), usata da AIutami e da Addlesee (2024).

**Fonti**: speech-architectures.md (confronto), Addlesee (2020) sulle sfide ASR multiparty.

---

### GAP 3: Tassonomia di design per multiparty speech-based

Houde (2025) crea una tassonomia eccellente per il controllo dell'agente in gruppo (WHEN/WHAT/WHERE + SPECIFY/ACCESS/IMPLEMENT), ma la valida solo su Slack (text-based). Il passaggio a speech cambia lo spazio di design:

- **WHEN**: in speech, la latenza conta -- l'agente deve decidere in <1s se intervenire
- **WHAT**: la voce e sequenziale e non-skippabile -- un messaggio lungo blocca il canale; nel testo si puo scorrere
- **WHERE**: non ci sono "thread" in speech -- l'agente puo solo parlare nel canale condiviso o in un canale privato
- **SPECIFY**: come si controlla l'agente durante una conversazione vocale? Non c'e un pannello da cliccare mentre si parla
- Le proprieta Visible/Ignorable/Accountable (Zheng 2022) assumono significati diversi in speech

DialogLab (Google, UIST 2025) fornisce un tool per progettare e testare conversazioni di gruppo umano-AI, ma e uno strumento di authoring/simulazione, non una tassonomia di design per speech deployato, e non affronta i vincoli specifici della modalita vocale.

**Fonti**: Houde (2025), Zheng (2022), DialogLab (Hu et al., UIST 2025).

---

### GAP 4: Addressee detection audio-only in gruppi N>2

Addlesee (2024) raggiunge 85.4% di accuratezza nell'addressee detection, ma usando **gaze + testo** con solo 2 umani. Axelsson et al. (2025, Furhat) raggiungono 92.6% con gaze per 2 umani, ma il riconoscimento **audio-only crolla al 26.8%** per utterance parallele. In contesti audio-only (senza video, come WebRTC voice-only o telefonate di gruppo), e con N>2 partecipanti, il problema e aperto:
- Senza gaze, il solo testo trascritto non basta (53.4% accuratezza, Addlesee 2024)
- Solo audio, il riconoscimento speaker in parallelo e 26.8% (Axelsson et al. 2025)
- Con N speaker, il numero di possibili addressee cresce linearmente
- Soluzioni alternative: cues prosodiche, nomina esplicita, o bypass strutturale (turn-taking esplicito come AIutami)
- Lee & Deng (ICMI 2024, Best Paper Runner-up) affrontano end-of-turn prediction per 3 parti, ma richiedono motion capture con 8 telecamere

**Fonti**: Addlesee (2024 EACL), Axelsson et al. (2025), Lee & Deng (ICMI 2024), Gu (2022).

**Validazione**: gap confermato. I risultati di Furhat (26.8% audio-only) rafforzano la tesi che l'addressee detection audio-only in multiparty e un problema aperto.

---

### GAP 5: Controllo dinamico dell'agente in contesti vocali

Houde (2025) dimostra che gli utenti vogliono regolare il comportamento dell'agente **durante** la sessione (non solo prima). In text, questo si fa con un pannello UI o comandi in-chat. In speech:
- Non si puo cliccare un pannello mentre si parla
- I comandi vocali all'agente ("moderatore, parla meno") confondono il canale conversazionale con il canale di controllo
- Possibili soluzioni non esplorate: gesti (se c'e video), interfaccia web parallela, comandi vocali con keyword detection

**Fonti**: Houde (2025), Zheng (2022) su Ignorable/Accountable.

---

### GAP 6: Gestione utterance incomplete in multiparty speech

Addlesee (2024) introduce le clarification requests (iCR) per gestire pause di pazienti con demenza. Ma in multiparty speech generico:
- L'endpointing ASR puo tagliare utterance a meta (specialmente con pause di riflessione)
- Con N speaker, le interruzioni e i false-endpoint sono piu frequenti
- Nessun sistema multiparty implementa iCR o strategie di recovery per utterance troncate
- Il problema e amplificato in pipeline STT-LLM: l'LLM riceve testo incompleto e genera risposte incoerenti

**Fonti**: Addlesee (2024 EACL), Addlesee (2020) su ASR incrementale.

---

### GAP 7: Benchmark e protocolli di valutazione per multiparty speech CA

Non esiste:
- Un dataset condiviso di conversazioni multiparty con AI speech-based
- Un benchmark standardizzato per confrontare sistemi
- Un protocollo di valutazione che copra sia metriche tecniche (latenza, WER, diarization) che UX (discussion quality, even participation, perceived group climate)

Zheng (2022) propone metriche UX per polyadic CA, ma solo text-based. Addlesee (2020) propone metriche ASR incrementali, ma senza considerare l'LLM downstream.

Benchmark recenti per spoken dialogue esistono ma sono **diadici**: SD-Eval (NeurIPS 2024) valuta comprensione paralinguistica, Full-Duplex-Bench (2025) valuta turn-taking e interruzioni. Nessuno dei due affronta il multiparty.

Il survey MPCA (arXiv:2505.18845, 2025) conferma esplicitamente questo gap: *"current MPCA evaluation benchmarks have three limitations: (i) each dataset focuses on a single specific skill of MPCAs; (ii) lack of benchmarks for multi-modal settings; (iii) lack of realistic metrics/simulations for evaluation."*

**Fonti**: Zheng (2022) Appendix A.1, Addlesee (2020), SD-Eval (NeurIPS 2024), Full-Duplex-Bench (2025), MPCA Survey (arXiv:2505.18845, 2025).

**Validazione**: gap confermato direttamente dal survey MPCA 2025.

---

### GAP 8: Proattivita dell'agente in speech -- il rischio amplificato

Houde (2025) mostra che Koala proattivo in text era percepito come "pedantic student who wouldn't create space for others". In speech, il rischio e amplificato:
- La voce dell'AI occupa il canale audio condiviso -- non si puo "scrollare via"
- Un intervento lungo blocca fisicamente la conversazione
- L'effetto "production blocking" (gli umani si fermano e aspettano che l'AI finisca) e piu forte in speech
- Il bilanciamento tra moderazione attiva e rispetto del flusso conversazionale non e stato studiato per speech

AIutami mitiga con reservation window (8s) e trigger condizionali, ma senza validazione empirica dell'equilibrio.

**Fonti**: Houde (2025) su proattivita dirompente, Zheng (2022) su Ignorable.

---

## Possibili direzioni per la tesi

(Da discutere con la prof -- ogni direzione affronta uno o piu gap)

### Direzione A: Evoluzione architetturale di AIutami verso half-cascade
Integrare un speech encoder direttamente nell'LLM per preservare informazioni prosodiche (emozione, esitazione, enfasi) che nella pipeline STT-TTT-TTS vengono perse. Mantenere il turn-taking esplicito per il multiparty. Affronta **GAP 2**.

### Direzione B: Sistema di controllo dinamico del moderatore in-session
Progettare e valutare meccanismi per consentire ai partecipanti di regolare il comportamento del moderatore AI durante la sessione vocale (comandi vocali, interfaccia web parallela, gesti). Affronta **GAP 3, 5**.

### Direzione C: Addressee-aware moderation per audio-only multiparty
Estendere AIutami con addressee detection basata su cues prosodiche e contestuali (senza video), per permettere al moderatore di capire a chi un partecipante si sta rivolgendo. Affronta **GAP 4**.

### Direzione D: Emotion-aware multiparty moderation
Integrare analisi del sentimento (dal testo trascritto e/o dalla prosodia) nelle decisioni del moderatore. Il moderatore interviene non solo per gestire il flusso ma anche per regolare il clima emotivo del gruppo. Affronta **GAP 8**, collegato ad Adikari (2022).

### Direzione E: VAP-informed turn management per multiparty
Integrare Voice Activity Projection (Ekstedt & Skantze, 2022) nel turn-taking di AIutami per anticipare le transizioni di turno e ridurre la latenza percepita. Affronta la scalabilita di VAP da diadico a multiparty. Affronta **GAP 2** dal lato turn-taking.

### Direzione F: Valutazione empirica comparativa
Condurre uno user study che confronti diversi gradi di proattivita del moderatore AI in contesti speech multiparty, producendo il primo benchmark di riferimento per il campo. Affronta **GAP 7, 8**.
