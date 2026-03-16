# Proposte di Valutazione Empirica — AIutami

**Autore:** Salvatore Conte
**Data:** 10 marzo 2026
**Scopo:** Presentare alla Prof. Garzotto due proposte alternative per la valutazione empirica del sistema AIutami, da discutere al primo incontro.

---

## Contesto

AIutami è una piattaforma di conferenza vocale in tempo reale con moderatore AI.
La tesi si concentra su *architetture e strategie di moderazione AI per sistemi speech-based multiparty*.

La valutazione empirica mira a:
1. Valutare l'esperienza utente (HCI) dell'interazione con un moderatore AI vocale in discussioni di gruppo
2. Raccogliere metriche oggettive di task performance e bilanciamento della partecipazione
3. Contribuire a colmare il GAP 7 identificato nello stato dell'arte: l'assenza di benchmark e protocolli per valutare speech-based multiparty AI moderators

**Reclutamento:** volontari tra amici, parenti, conoscenti e studenti universitari (25-40 persone stimate).

---

## Proposta A — Murder Mystery (confronto con Dubini 2024)

### Idea
Replicare il task di Stasser & Stewart (1992) usato da Dubini nella sua tesi (2024), trasponendolo dalla chat testuale alla discussione vocale su AIutami. I risultati vengono confrontati qualitativamente con quelli di Dubini per esplorare le differenze tra moderazione testuale e vocale.

### Research Question
*How do participants interact with an AI speech-based moderator in a collaborative decision-making task, and how do the outcomes compare qualitatively with those observed in a text-based implementation of the same task?*

### Design
- **Single-condition:** tutti i gruppi usano AIutami con moderatore AI attivo
- **Confronto qualitativo** con i dati di Dubini (condizione control senza moderatore + condizione sperimentale con moderatore testuale) come historical baseline
- Non è un confronto sperimentale rigoroso (cambiano modalità, piattaforma, partecipanti), ma un'esplorazione delle differenze tra le due implementazioni

### Partecipanti
- 30-36 volontari → 10-12 gruppi da 3 persone
- Stesse condizioni di Dubini: 3 persone, Solve, Hidden Profile

### Task
Murder mystery di Stasser & Stewart (1992):
- 3 partecipanti ricevono ciascuno una versione diversa di un caso poliziesco (versioni A, B, C)
- Ogni versione contiene 32 dettagli (condivisi), 15 indizi non-critici (condivisi) e 3 indizi critici (unici per versione)
- Solo combinando i 9 indizi critici il gruppo può identificare il vero colpevole (Eddie)
- Il gruppo deve discutere e votare un colpevole

### Flow sessione (~75 min, sincrona)
1. **Briefing + Consent** (5 min)
2. **Reading dei materiali** (30 min) — booklet cartacei o PDF, individuale. Fatto contestualmente alla sessione per evitare che i partecipanti usino AI per analizzare i materiali.
3. **Pre-discussion questionnaire** (5 min) — 7 domande di comprensione (attention check) + "chi pensi sia il colpevole?"
4. **Discussione vocale su AIutami** (30 min) — con moderatore AI attivo + voto finale
5. **Post-discussion questionnaire** (10 min) — SUS + metriche UX + feedback aperto

### Metriche

**Task Performance (identiche a Dubini, per confronto):**
| Metrica | Descrizione |
|---------|-------------|
| Correct culprit | Percentuale di gruppi che identifica Eddie |
| Critical / Non-critical clues | Conteggio indizi emersi nella discussione (codifica manuale delle trascrizioni) |
| Discussion Focus | Critical / Total info |
| Info Request | Richieste esplicite di informazioni |
| Inference | Ragionamenti inferenziali dei partecipanti |
| Discussion Time | Minuti effettivi di discussione |
| Gini Index (adjusted) | Bilanciamento partecipazione (calcolato su tempo di parola) |
| AI Intervention Rate | Messaggi moderatore / messaggi utenti |

**UX (aggiunta rispetto a Dubini):**
- SUS (System Usability Scale) — 10 items standardizzati
- Perceived moderator helpfulness (scala 1-5)
- Perceived naturalness of AI voice (scala 1-5)
- Perceived fairness of turn distribution (scala 1-5)
- Open-ended: "Cosa ha funzionato? Cosa no? Come hai percepito il moderatore?"

### Punti di forza
- Confronto diretto con un lavoro precedente (Dubini 2024) sullo stesso task
- Task validato in letteratura (Stasser & Stewart, 1992)
- Metriche già definite e codificate

### Limitazioni
- Confronto "sporco": cambiano modalità, piattaforma, prompt del moderatore, popolazione
- Sessioni lunghe (75 min) → rischio dropout
- Rischio AI cheating sui materiali (mitigato dalla lettura contestuale)
- Metrica principale binaria (giusto/sbagliato) → basso potere statistico

---

## Proposta B — Consensus-Reaching Task (Desert Survival) ⭐ Raccomandata

### Idea
Utilizzare un task di consensus-reaching (Desert Survival Problem, Lafferty & Eady 1974) per valutare l'effetto del moderatore AI sulla qualità delle decisioni di gruppo, il bilanciamento della partecipazione e l'esperienza utente. Questo task è ampiamente usato nella letteratura HCI, CSCW e group decision-making, ed è naturalmente adatto alla discussione vocale.

### Research Question
*How does an AI speech-based moderator affect group decision quality, participation balance, and perceived user experience in a consensus-reaching task?*

### Task
Desert Survival Problem:
- Scenario: incidente aereo nel deserto del Sonora, 15 oggetti recuperabili
- Ogni partecipante individualmente classifica i 15 oggetti dal più al meno utile per la sopravvivenza
- Il gruppo discute e produce una classifica condivisa
- Esiste una **classifica "corretta" degli esperti** → metrica oggettiva continua (distanza dal ranking esperto)

Varianti equivalenti (per design within-subjects): Arctic Survival, NASA Moon Survival.

### Design — Due sotto-opzioni

#### Opzione B1: Between-subjects (più semplice)
- **5 gruppi** (15 persone): Desert Survival **con moderatore AI** su AIutami
- **5 gruppi** (15 persone): Desert Survival **senza moderatore** su AIutami (AI spento, solo canale vocale)
- Totale: 30 persone, 10 gruppi
- Ogni gruppo fa il task **una sola volta**
- Confronto pulito: stessa piattaforma, stessa modalità, unica variabile = moderatore

#### Opzione B2: Within-subjects (più potere statistico)
- Ogni gruppo fa **2 sessioni** su AIutami:
  - Desert Survival con moderatore AI ON
  - Arctic Survival con moderatore AI OFF (o viceversa, ordine randomizzato)
- Totale: 18-24 persone, 6-8 gruppi, ma 12-16 data points
- Più potere statistico (ogni gruppo è il proprio controllo)
- Sessione più lunga (~80 min totale per le due sessioni)

### Flow sessione (~40 min per sessione, sincrona)
1. **Briefing + Consent** (5 min)
2. **Lettura scenario + ranking individuale** (5 min) — un foglio A4 con scenario e lista oggetti
3. **Discussione vocale su AIutami** (20 min) — il gruppo deve concordare un ranking condiviso
4. **Ranking finale del gruppo** — conferma del ranking concordato
5. **Post-discussion questionnaire** (10 min) — SUS + metriche UX + feedback aperto

### Metriche

**Task Performance (oggettive):**
| Metrica | Descrizione |
|---------|-------------|
| Decision accuracy | Distanza (Spearman ρ o Kendall τ) tra ranking del gruppo e ranking degli esperti |
| Synergy score | Il ranking del gruppo è migliore della media dei ranking individuali? |
| Discussion time | Minuti effettivi di discussione |
| Turn count / duration | Numero di turni e durata media |

**Participation balance:**
| Metrica | Descrizione |
|---------|-------------|
| Gini Index (adjusted) | Bilanciamento partecipazione (su tempo di parola) |
| Speaking time per participant | Distribuzione del tempo di parola |
| AI Intervention Rate | Frequenza di intervento del moderatore |

**UX (soggettive):**
| Metrica | Descrizione |
|---------|-------------|
| SUS | System Usability Scale — 10 items standardizzati |
| Moderator helpfulness | Scala 1-5 |
| Naturalness of AI voice | Scala 1-5 |
| Fairness of turn distribution | Scala 1-5 |
| Willingness to reuse | "Useresti questo sistema per un meeting reale?" (1-5) |
| Open-ended feedback | Cosa ha funzionato / cosa no / percezione moderatore |

### Punti di forza
- **Confronto sperimentale pulito** (unica variabile: moderatore on/off)
- **Task naturale per la voce** — discussione argomentativa, niente materiali lunghi
- **Metrica continua** (ranking distance) → più potere statistico della metrica binaria del murder mystery
- **Sessioni corte** (40 min) → facile reclutare, basso dropout
- **Basso rischio AI cheating** — il task è argomentativo, non ha una "soluzione nascosta"
- **Letteratura enorme** — centinaia di studi usano questo task dagli anni '70
- **Contributo al GAP 7** — propone un protocollo replicabile per valutare speech-based multiparty AI moderators
- Possibilità di within-subjects con varianti (Desert/Arctic/NASA)

### Limitazioni
- Nessun confronto diretto con Dubini (task diverso)
- Il task è relativamente semplice — potrebbe non stressare abbastanza il moderatore
- 5 gruppi per condizione (between-subjects) è un campione piccolo

---

## Confronto tra le proposte

| Dimensione | Proposta A (Murder Mystery) | Proposta B (Desert Survival) |
|---|---|---|
| Confronto con Dubini | Sì (qualitativo) | No |
| Confronto con/senza moderatore | No (single-condition) | Sì (between o within) |
| Rigore sperimentale | Basso (troppi confound) | Alto (unica variabile) |
| Durata sessione | ~75 min | ~40 min |
| Facilità reclutamento | Media | Alta |
| Rischio AI cheating | Medio | Basso |
| Tipo metrica principale | Binaria | Continua |
| Letteratura di riferimento | Stasser 1992, Dubini 2024 | Lafferty 1974, centinaia di studi |
| Contributo HCI | Medio (UX aggiunta) | Alto (protocollo + UX + confronto) |
| Contributo GAP 7 | Parziale | Diretto |

---

## Nota sul moderatore AI

In entrambe le proposte, il prompt del moderatore AI deve istruire l'LLM a:
- **Moderare** la discussione (bilanciare partecipazione, sintetizzare, rilanciare)
- **Non suggerire risposte** o soluzioni al task
- Comportarsi come un moderatore umano neutrale

Questo è un punto di design critico che va documentato nella tesi.

---

## Prossimi passi suggeriti

1. Presentare entrambe le proposte alla Prof. Garzotto per feedback
2. Scegliere la direzione (A, B, o una combinazione)
3. Se scelta B: decidere tra between-subjects (B1) e within-subjects (B2)
4. Preparare i materiali (scenario, questionari, consent form)
5. Iniziare il reclutamento dei volontari
6. Pilot test con 1-2 gruppi per validare il protocollo
