# Metriche per la Valutazione Empirica — AIutami

## 1. Metriche di Task Performance

### Murder Mystery (riferimento Dubini 2024)

| Metrica | Cosa misura | Come si calcola | Tipo |
|---------|------------|-----------------|------|
| Correct culprit | Il gruppo ha indovinato il colpevole? | Sì (Eddie) = 1, No = 0 | Binaria |
| Critical clues | Quanti indizi chiave sono emersi nella discussione | Codifica manuale delle trascrizioni: ogni versione (A/B/C) ha 3 indizi critici unici, 9 totali | Conteggio |
| Non-critical clues | Quanti indizi generici sono emersi | Stesso metodo, per gli indizi condivisi | Conteggio |
| Discussion Focus | La discussione si è concentrata sulle cose importanti? | Critical clues / Totale info emerse | Rapporto (0-1) |
| Info Request | Quanto i partecipanti si sono chiesti informazioni a vicenda | Conteggio richieste esplicite ("tu cosa sai di...?") | Conteggio |
| Inference | Quanto i partecipanti hanno ragionato | Conteggio ragionamenti inferenziali ("se X allora Y, quindi...") | Conteggio |

**Limite principale:** la metrica chiave (correct culprit) è binaria → basso potere statistico. Dubini con 60 persone (20 gruppi) non ha trovato significatività statistica.

### Desert Survival (proposta tesi)

| Metrica | Cosa misura | Come si calcola | Tipo |
|---------|------------|-----------------|------|
| Decision accuracy | Qualità della classifica del gruppo | Correlazione di Spearman (ρ) tra ranking del gruppo e ranking degli esperti. Va da -1 (opposto) a +1 (identico) | Continua |
| Synergy score | Il gruppo ha fatto meglio dei singoli? | Errore medio individuale − errore del gruppo. Se positivo → synergy (il gruppo ha aggiunto valore). Se negativo → process loss | Continua |
| Strong synergy | Il gruppo ha battuto il suo membro migliore? | Ranking del gruppo migliore del ranking del miglior individuo? Sì/No | Binaria |
| Discussion time | Durata effettiva della discussione | Minuti dal primo al ultimo turno di parola | Continua |
| Turn count | Numero di turni nella discussione | Conteggio turni dal backend | Conteggio |

**Vantaggio:** la decision accuracy è continua → molto più potere statistico rispetto alla metrica binaria del Murder Mystery.

### Confronto moderatore ON vs OFF (within-subjects)

Ogni gruppo fa 2 sessioni (ordine controbilanciato). Per ogni metrica si confronta:

| | Sessione con moderatore ON | Sessione con moderatore OFF |
|---|---|---|
| Decision accuracy | ρ_ON | ρ_OFF |
| Synergy score | synergy_ON | synergy_OFF |
| Gini Index | gini_ON | gini_OFF |
| SUS | sus_ON | sus_OFF |

**Ipotesi:** con moderatore ON ci aspettiamo decision accuracy più alta, synergy score più alto, Gini più basso (partecipazione più equa).

**Analisi statistica:** test dei ranghi di Wilcoxon (paired, non-parametrico) per confrontare ON vs OFF. Con campione piccolo (4-5 gruppi) riportiamo effect size (Cohen's d) e trend anche se non significativi.

---

## 2. Metriche di Partecipazione

Identiche per entrambi i task e per entrambe le condizioni (ON/OFF).

| Metrica | Cosa misura | Come si calcola |
|---------|------------|-----------------|
| Gini Index | Equità della partecipazione | Va da 0 (tutti parlano uguale) a 1 (uno parla, gli altri zitti). Calcolato sul tempo di parola di ciascun partecipante |
| Speaking time per participant | Quanto ha parlato ciascuno | Secondi di parlato per persona (dal turn-taking del backend) |
| AI Intervention Rate | Frequenza di intervento del moderatore | Numero interventi AI / numero turni umani (solo per condizione ON) |

### Gini Index — esempio concreto

- 3 persone, ognuna parla 5 min → Gini = 0 (perfetto equilibrio)
- 3 persone: una parla 13 min, le altre 1 min ciascuna → Gini ≈ 0.53 (sbilanciato)
- Ipotesi: con moderatore ON, Gini più basso (partecipazione più equa)

---

## 3. Metriche UX (soggettive)

Raccolte tramite questionario post-sessione.

| Metrica | Cosa misura | Scala |
|---------|------------|-------|
| SUS (System Usability Scale) | Usabilità percepita del sistema | 10 domande standardizzate, punteggio 0-100. Sopra 68 = sopra la media |
| Moderator helpfulness | Il moderatore è stato utile? | Likert 1-5 |
| Naturalness of AI voice | La voce del moderatore era naturale? | Likert 1-5 |
| Fairness of turn distribution | I turni erano distribuiti equamente? | Likert 1-5 |
| Willingness to reuse | Useresti questo sistema per un meeting reale? | Likert 1-5 |
| Open-ended feedback | Commenti liberi | "Cosa ha funzionato? Cosa no? Come hai percepito il moderatore?" |

---

## 4. Risultati di Dubini (2024) — riferimento

- 60 partecipanti Prolific (pagati), 20 gruppi da 3, 2 condizioni (control/experimental)
- Statistiche usate: Mann-Whitney U, chi-quadro, correlazione biseriale
- **Risultato:** nessuna significatività statistica su nessuna metrica
- **Problema principale:** qualità bassa dei partecipanti Prolific (non leggevano, non partecipavano seriamente)
- **Pilot interni** (amici, non pagati) andavano molto meglio → motivazione > compenso economico

---

## 5. Design dello studio — Desert Survival within-subjects

### Setup (4-5 gruppi, 12-15 persone)

| Gruppo | Sessione 1 | Sessione 2 |
|--------|-----------|-----------|
| G1 | Desert + moderatore ON | Arctic + moderatore OFF |
| G2 | Desert + moderatore ON | Arctic + moderatore OFF |
| G3 | Desert + moderatore OFF | Arctic + moderatore ON |
| G4 | Desert + moderatore OFF | Arctic + moderatore ON |

### Controbilanciamento
Metà dei gruppi inizia con moderatore ON, metà con OFF. Questo neutralizza l'effetto ordine (es. il secondo task va meglio perché i partecipanti si sono "scaldati").

### Procedura per sessione (~40 min)
1. Briefing + consenso (5 min)
2. Lettura scenario + ranking individuale (5 min)
3. Discussione vocale su AIutami (20 min) → ranking di gruppo
4. Questionari UX (10 min)
