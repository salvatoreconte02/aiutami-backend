# Simulazione Presentazione alla Prof. Garzotto

## Slide 1 — Titolo (10 secondi)

"Buongiorno professoressa. La mia tesi si intitola *Architectures and AI Moderation Strategies for Multi-Party Speech Conversational Systems*."

---

## Slide 2 — Gap 1 e 2 (1 minuto)

"Dallo stato dell'arte ho identificato alcuni gap. Il primo: i sistemi conversazionali vocali sono quasi sempre diadici — un utente e un agente. I sistemi multiparty esistono, ma sono quasi tutti text-based — chat, forum, Slack. Se guardiamo il quadrante speech + multiparty, è praticamente vuoto. Gli unici tentativi sono ARI e Furhat, che supportano solo 2 umani più un robot e dipendono dalla vista per capire a chi rivolgersi. AIutami si posiziona in quel quadrante."

---

## Slide 3 — Gap 3 e 4 (1 minuto)

"Terzo gap: le architetture vocali attuali — pipeline, half-cascade, end-to-end — assumono tutte un singolo parlante che parla con un singolo agente. Nessuna è progettata per gestire N stream audio in parallelo con turn-taking tra più partecipanti.

Quarto gap: l'AI nei sistemi conversazionali è quasi sempre un assistente o un sistema di risposta. Pochissimi lavori studiano l'AI nel ruolo di moderatore di una discussione di gruppo — che gestisca il turn-taking, bilanci la partecipazione e guidi la discussione senza suggerire risposte."

---

## Slide 4 — Direzione di tesi (30 secondi)

"La tesi ha tre contributi. Primo: un'architettura per multiparty speech con AI moderatore — N stream audio, turn-taking esplicito, pipeline STT-LLM-TTS con ASR gating. Secondo: strategie di moderazione AI — quando e come intervenire, prompt engineering per il ruolo di moderatore. Terzo: una valutazione empirica, per cui oggi le presento due proposte."

---

## Slide 5 — Proposta A, Murder Mystery (1.5 minuti)

"La prima proposta replica il task usato da Dubini nella sua tesi — il murder mystery di Stasser. Tre partecipanti ricevono versioni diverse di un caso poliziesco, e solo combinando gli indizi critici possono trovare il colpevole. L'idea è trasporre lo stesso task dalla chat testuale di Dubini alla discussione vocale su AIutami, e fare un confronto qualitativo.

Il design è single-condition: tutti i gruppi usano il moderatore AI. Poi confrontiamo i risultati con quelli di Dubini come baseline storica.

Però ha dei limiti importanti. Il confronto è sporco — cambiano la modalità, la piattaforma, i partecipanti. Le sessioni sono lunghe, 75 minuti, difficile per volontari non pagati. E la metrica principale è binaria — giusto o sbagliato — quindi ha basso potere statistico. Dubini con 60 persone su Prolific non ha trovato significatività."

---

## Slide 6 — Proposta B, Desert Survival (2 minuti)

"La seconda proposta usa il Desert Survival Problem di Lafferty ed Eady, 1974. Il task è semplice: dopo un incidente aereo nel deserto, il gruppo deve classificare 15 oggetti in ordine di utilità per la sopravvivenza. Esiste un ranking corretto degli esperti, che ci dà una metrica oggettiva e continua.

Il vantaggio chiave è il design sperimentale. Propongo due sotto-opzioni.

B1, between-subjects: 5 gruppi con moderatore, 5 senza. Tutti fanno Desert Survival. Confronto pulito, unica variabile è il moderatore.

B2, within-subjects: ogni gruppo fa due sessioni — una con moderatore e una senza, usando Desert e Arctic Survival come varianti equivalenti. Ordine controbilanciato: metà dei gruppi inizia con moderatore, metà senza. Così ogni gruppo è il proprio controllo, e abbiamo più potere statistico con meno persone.

Le sessioni durano circa 40 minuti — molto più gestibile per volontari non pagati."

---

## Slide 7 — Confronto (1 minuto)

"In sintesi: la proposta A ha il vantaggio del confronto con Dubini, ma il design è debole — single-condition, metrica binaria, sessioni lunghe. La proposta B ha un design sperimentale pulito, metriche continue, sessioni corte, ed è più facile da reclutare. Per questo la mia raccomandazione è la proposta B."

---

## Slide 8 — Letteratura Survival Task (1.5 minuti)

"Il survival task è un paradigma consolidato da oltre 50 anni. Hall e Watson nel 1970 hanno mostrato che i gruppi che ricevono istruzioni di consenso — cercare le differenze di opinione, evitare il voto a maggioranza — raggiungono strong synergy a tassi più alti.

Hamada nel 2020 con 119 partecipanti ha confermato che i gruppi battono gli individui, ma ha trovato che la discussione libera, senza guida, non basta — serve una guida al processo deliberativo.

E Hémon nel 2024 ha usato proprio il Desert Survival in videoconferenza con 125 partecipanti, dimostrando che guidare il processo deliberativo migliora la sinergia di gruppo. Questo è esattamente ciò che il moderatore AI di AIutami fa in tempo reale.

Questi paper ci danno sia la validazione del task in contesti online, sia l'evidenza che una guida al processo — che nel nostro caso è il moderatore AI — può fare la differenza."

---

## Chiusura (15 secondi)

"Professoressa, questa è la mia proposta. Lei cosa ne pensa? Ha una preferenza tra le due, o suggerimenti?"

---

## Domande probabili e risposte preparate

**"Quanti partecipanti pensi di reclutare?"**
"12-15 persone, 4-5 gruppi da 3. Con il within-subjects ogni gruppo fa entrambe le condizioni, quindi ho 4-5 data points per condizione dove ogni gruppo è il proprio controllo."

**"Non sono pochi?"**
"Sì, è un campione piccolo. Non mi aspetto significatività statistica, ma riporterò effect size con Cohen's d e i trend osservati. Per una tesi magistrale, con metriche continue e within-subjects, è un campione difendibile. Anche Dubini con 60 persone non ha trovato significatività."

**"Perché non usi Prolific come Dubini?"**
"Dubini ha avuto problemi di qualità con i partecipanti Prolific — non leggevano i materiali, non partecipavano seriamente. I pilot interni con amici andavano molto meglio. Con volontari motivati mi aspetto dati più puliti, anche se il campione è più piccolo."

**"Perché within-subjects e non between?"**
"Con il within-subjects ogni gruppo è il proprio controllo, elimino la variabilità tra gruppi. Con 12 persone ho lo stesso potere statistico che avrei con 30 in between-subjects. E il controbilanciamento — metà inizia con moderatore, metà senza — neutralizza l'effetto ordine."

**"Come garantisci che Arctic e Desert siano equivalenti?"**
"Sono varianti della stessa famiglia di task, create dagli stessi autori, con la stessa struttura: ranking di 15 oggetti con soluzione esperta. Sono usate in combinazione negli studi within-subjects dalla letteratura dagli anni '70."

**"Il moderatore non potrebbe influenzare il risultato suggerendo risposte?"**
"Il prompt del moderatore è progettato per essere neutrale: bilancia la partecipazione, sintetizza, rilancia, ma non suggerisce mai risposte o soluzioni. Questo è un punto di design che documento nella tesi."

**"Che metriche UX usi?"**
"SUS per l'usabilità, poi scale Likert 1-5 per helpfulness del moderatore, naturalezza della voce, equità dei turni, e willingness to reuse. Più un feedback aperto che analizzo con thematic analysis."

**"E se i risultati non sono significativi?"**
"Riporto comunque i trend e gli effect size. Il contributo principale non è il p-value, ma il protocollo di valutazione per speech-based multiparty AI moderators — che ad oggi non esiste in letteratura. Anche un risultato 'non significativo con effetto medio' è informativo."
