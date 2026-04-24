# Analisi logica di moderazione e miglioramenti proposti

**Data:** 2026-04-20
**Contesto:** Brainstorming per tesi magistrale (AIutami). Analisi completa della pipeline di moderazione AI attuale, con identificazione di punti deboli e proposte di miglioramento discussi con l'assistente.
**Scopo del documento:** fissare lo stato attuale del sistema e i punti su cui tornare quando si passa all'implementazione. Ogni sezione "Proposta" riporta esplicitamente lo stato (da implementare / future work / in discussione) così da poter recuperare il contesto rapidamente.

---

## 1. Come funziona oggi la moderazione

### 1.1 Flusso end-to-end di un turno umano

```
Utente rilascia push-to-talk (WS "end_speak")
  → apps/turns/ws_consumer.py:_handle_end_speak()       [l.292-548]
     ├─ TurnManager.end_speak()                         [chiude turno]
     ├─ _set_moderation_in_progress(True)               [blocco nuovi turni]
     ├─ _append_to_session_transcript(...)              [salva turno umano]
     └─ ModerationOrchestrator.handle_human_turn_end()
            ├─ evaluate_triggers_on_human_turn_end()    [triggers.py:120]
            │    ├─ _should_force_summary(state)        [ogni 6 turni umani]
            │    ├─ timer 30 min → should_transition_to_conclusion
            │    ├─ messaggi statici (no_push, inactive_user, ecc.)
            │    └─ ritorna hard_action: NONE | FORCED_SUMMARY
            │
            └─ ModerationService.handle_human_turn_ended()   [service.py:76]
                 ├─ _decide_llm_mode()                  → "normal" | "forced_summary"
                 ├─ _call_llm()                         → OpenAI JSON mode
                 ├─ state.summary = llm_output["updated_summary"]
                 ├─ _decide_ai_intervention()           [filtri backend, vedi 1.3]
                 └─ save_moderation_state()
  → se ai_should_speak:
       ├─ TurnManager.ai_start()
       ├─ TTSService.synthesize_stream()               [OpenAI TTS → audio hub]
       ├─ wait_ai_playout()
       ├─ TurnManager.ai_end()
       └─ broadcast via WebSocket
```

**FORCED_CONCLUSION** non passa dai trigger post-turno: viene eseguita direttamente in `_execute_forced_conclusion()` (`ws_consumer.py:531`) quando scade il timer 30 min o tutti i partecipanti sono "ready".

### 1.2 Tre modalità di prompt LLM

Tutte condividono lo scheletro `_build_system_prompt(mode, task)` in `service.py:830-848`, con sostituzione del blocco scenario task-specifico (`task.task_context_block(mode)`).

| Modalità | File/linee | Input payload | Output JSON | Temperature |
|---|---|---|---|---|
| **normal** | `_build_normal_mode_prompt()` l.751-828 | summary + last_turn + turns_per_participant + phase | `{updated_summary, should_ai_speak, message_to_say, reason, intervention_score}` | 0.4 |
| **forced_summary** | `_build_forced_summary_system_prompt()` l.685-748 | summary + last_turn + participants + total_turns | `{updated_summary, message_to_say, correction_reason}` | 0.4 |
| **forced_conclusion** | `_build_forced_conclusion_system_prompt()` l.503-550 | summary + conclusion_reason + duration | `{updated_summary, message_to_say}` | 0.5 |

Le 6 ground rules di Hall & Watson (1970) sono iniettate come testo informativo nello scenario block di nasa_moon (`apps/tasks/nasa_moon/prompts.py:9-16`). **Non sono agganciate in modo strutturato né alla `reason` né all'output dell'LLM.**

### 1.3 Filtri backend sulla proposta LLM

`_decide_ai_intervention()` in `service.py:363-418`. Primo match vince:

| # | Condizione | Effetto |
|---|-----------|---------|
| 1 | `mode ∈ {forced_summary, forced_conclusion}` | Parla sempre (bypassa tutto). Se message vuoto → fallback a `state.summary`. |
| 2 | `llm_should_speak=False` o `llm_message` vuoto | Non parla |
| 3 | `llm_score < 0.7` | Non parla (soglia hardcoded) |
| 4 | `llm_reason ∉ {conflict, user_request}` **e** `now - last_ai_intervention_at < 60s` | Non parla (cooldown) |
| 5 | `session_phase != "ACTIVE"` | Non parla |
| — | altrimenti | **Parla** |

**Parametri:** `AI_INTERVENTION_COOLDOWN=60s`, `COOLDOWN_BYPASS_REASONS={conflict, user_request}`, `SUMMARY_TURNS_INTERVAL=6`, soglia score `0.7` — tutti in `service.py:44-46` e in fondo a `_decide_ai_intervention`.

Il contatore `ai_interventions_count` si incrementa solo in normal mode ed è oggi **solo telemetria** (non confrontato con un max).

### 1.4 Stato persistente (Redis `moderation:{session_id}`, TTL infinito)

`ModerationState` in `state.py:17-40`:
- `summary: str` — running summary della discussione
- `human_turns_since_last_summary: int` — reset dopo FORCED_SUMMARY
- `ai_interventions_count: int` — solo telemetria oggi
- `last_ai_intervention_at: datetime` — base del cooldown
- `turns_per_participant: dict[str,int]`
- `conclusion_reason: str | None`
- `forced_conclusion_done: bool`

### 1.5 Reason enum (normal mode)

Il prompt normal vincola `reason ∈ {monopolization, exclusion, off_topic, conflict, user_request, all_ok}`.
**Attualmente il valore di `reason` viene:**
- usato per decidere il bypass del cooldown (solo `conflict` e `user_request`)
- loggato in `[MODERATION][LLM][RESPONSE]`

Oltre a questo, viene buttato via: non entra in stato persistente, non finisce nel report finale.

---

## 2. Punti di miglioramento identificati

### 2.1 [COMPLETATO] Registrare `interventions_log` nel report finale

**Stato:** implementato (2026-04-24). Solo `interventions_log` (normal mode), senza `forced_events_log` (concordato con utente: forced_summary verrà rimosso).

**Motivazione:** `reason` era solo log e spariva alla fine della sessione. Per la valutazione empirica (NASA Moon + Lost at Sea) serve sapere quanti interventi AI ci sono stati e di che tipo.

**Cosa è stato fatto:**

1. **`apps/moderation/state.py`** — aggiunto campo `interventions_log: list[dict]` al dataclass `ModerationState`, con serializzazione Redis (load/save). Ogni entry: `{ts, reason, score, speaker, message}`.

2. **`apps/moderation/service.py`** — in `handle_human_turn_ended()`, dopo l'incremento di `ai_interventions_count` in normal mode (riga 144), append della entry a `interventions_log` con timestamp ISO, reason, score, speaker e messaggio AI.

3. **`apps/sessions/services.py`** — `_collect_report_data()` legge `interventions_log` da `ModerationState` e lo include nel dict `report_data`. Finisce automaticamente in `Session.report_data` (JSONField già esistente, nessuna migration). Redis viene pulito normalmente al cleanup.

4. **Prompt LLM report aggiornati** in tutti e 4 i task:
   - `apps/tasks/base.py` — prompt default
   - `apps/tasks/murder_mystery/report.py`
   - `apps/tasks/nasa_moon/report.py`
   - `apps/tasks/lost_at_sea/report.py`

   Tutti istruiscono l'LLM a generare una sezione "INTERVENTI DEL MODERATORE" con totale, breakdown per reason, e dettaglio per intervento.

5. **`apps/reports/pdf_service.py`** — nuovo metodo `_build_interventions_section()` che genera una tabella ReportLab con colonne (#, Timestamp, Speaker, Reason, Score) + riga di riepilogo con breakdown per reason. Inserita dopo la sezione partecipazione.

6. **Test (10 nuovi, tutti verdi):**
   - `apps/moderation/tests.py` → classe `InterventionsLogTests`: stato iniziale vuoto, persistenza Redis, append in normal mode, no append se AI non parla, no append in forced_summary, struttura entry corretta.
   - `apps/reports/tests_metrics.py` → classi `CollectReportDataInterventionsLogTests` e `ReportPDFInterventionsTests`: inclusione in report_data, log vuoto senza mod_state, PDF con e senza interventions_log.

**Flusso runtime:**
```
Intervento AI normal mode → append a interventions_log (Redis)
Chiusura sessione → interventions_log letto da Redis → salvato in Session.report_data (JSONField)
                  → passato all'LLM per report text → sezione nel PDF
                  → Redis pulito
```

**161/161 test verdi** dopo l'implementazione.

---

### 2.2 [FUTURE WORK] Differenziare tono/lunghezza del messaggio per reason

**Stato:** future work, solo SE dopo i test si osservano messaggi AI troppo uniformi nel registro.

**Motivazione:** il prompt normal attuale dà un'unica istruzione stilistica ("1-2 frasi, 20-30 parole max"). Ma un intervento per `conflict` e uno per `exclusion` richiedono registri diversi (fermo vs invitante).

**Soluzione (una sola chiamata LLM, nessun overhead):**
aggiungere al prompt normal una sezione tipo:

```
## Come modulare il messaggio in base alla reason

Se reason == conflict: tono fermo e calmo, 1 frase, es. "Torniamo al tema con rispetto reciproco."
Se reason == exclusion: tono caldo, coinvolgi per nome, es. "Lucia, tu cosa ne pensi?"
Se reason == off_topic: frase breve di riancoraggio, es. "Interessante, ma torniamo al tema."
Se reason == monopolization: gentile e indiretto, invita qualcun altro senza mettere in imbarazzo
Se reason == user_request: rispondi direttamente alla richiesta
```

**Trade-off:** nessun costo aggiuntivo, solo complessità del prompt. Da attivare solo se i test mostrano messaggi troppo omogenei. Non è un blocker per la consegna iniziale.

---

### 2.3 [FUTURE WORK] Rendere `forced_summary` una capability task-specific (o eliminarlo del tutto)

**Stato:** future work. Il problema osservato è reale ma la decisione richiede test A/B o discussione tutor.

**Motivazione:** la ricapitolazione periodica ogni 6 turni toglie naturalezza alla discussione, soprattutto su NASA Moon Survival dove il ragionamento è continuo e il momentum è importante. Originariamente introdotta per "dare freschezza mentale" al gruppo, ma nei test percepita come meccanica.

**Cosa fa oggi `forced_summary` che andrebbe preservato se eliminato:**
- Reset di `human_turns_since_last_summary` → unused dopo eliminazione, si può rimuovere
- Aggiornamento di `state.summary` → **già fatto anche in normal mode** (`service.py:121`), non blocca
- Detection di `off_topic` e `conflict` → **già fatto anche in normal mode** con le stesse categorie

**Conseguenze effettive della rimozione:** sparisce solo la ricapitolazione audio periodica. Il summary interno continua ad aggiornarsi turno per turno, quindi il report finale non ne soffre.

**Opzione A — rimozione totale:** elimina `SUMMARY_TURNS_INTERVAL`, `_should_force_summary()`, `_build_forced_summary_system_prompt()`, `call_llm_for_summary()`, `_fallback_forced_summary()`. Semplifica parecchio.

**Opzione B (preferita) — task-specific via TaskDefinition:**
```python
# apps/tasks/base.py
class TaskDefinition:
    def periodic_summary_enabled(self) -> bool:
        return True  # default

# apps/tasks/nasa_moon/task.py
def periodic_summary_enabled(self) -> bool:
    return False
```
E in `triggers.py:_should_force_summary()`:
```python
return task.periodic_summary_enabled() and (
    state.human_turns_since_last_summary + 1 >= SUMMARY_TURNS_INTERVAL
)
```

**Perché B è meglio per la tesi:** contributo architetturale esplicito ("the moderator's strategy is adapted per task, not universal") — si aggancia al contributo 2 della tesi ("Strategie di moderazione AI"). Permette anche esperimento A/B: un braccio con forced_summary attivo, uno senza, misurando impatto percepito.

**Decisione finale:** da prendere dopo discussione con i tutor.

**Nota implementativa — collasso di `evaluate_triggers_on_human_turn_end()`:**
Se si elimina il forced_summary, la funzione `evaluate_triggers_on_human_turn_end()` in `triggers.py` perde il suo unico trigger hard — resta solo il check timer 30 min (che è anche in `evaluate_time_based_triggers`). A quel punto la funzione è quasi vuota (raccoglie solo messaggi statici come la prenotazione speaker). Valutare se collassarla nell'orchestrator o tenerla come hook per futuri trigger.

---

### 2.4 [DA IMPLEMENTARE] Passare l'ultimo intervento AI all'LLM

**Stato:** da implementare.

**Data ultima revisione:** 2026-04-24

**Problema:** l'LLM non sa cosa ha detto nel suo ultimo intervento. Questo causa due problemi concreti:

1. **Ripetizione inutile:** AI dice "Lucia, tu cosa ne pensi?" → Lucia parla → l'LLM non sa di aver appena coinvolto Lucia → potrebbe dire di nuovo "Lucia non ha parlato"
2. **Mancato riconoscimento della risoluzione:** AI dice "calmiamo i toni" → i turni successivi sono civili → l'LLM non sa di aver già affrontato il problema → potrebbe re-intervenire

Un facilitatore umano si ricorda naturalmente cosa ha detto 2 minuti fa. Senza questa informazione il bot è "smemorato del proprio comportamento".

**Soluzioni alternative considerate e scartate:**

1. **Due call LLM separate (Decision + Generation, poi Summary Update):** scartata perché aggiunge complessità e latenza per risolvere un problema (qualità del summary) che non si è osservato nei test. Il summary funziona bene con una singola call.

2. **Sliding window degli ultimi 3 turni:** scartata perché il summary già copre le informazioni dei turni recenti. Aggiungere i turni raw è contesto ridondante senza beneficio chiaro. Se il summary è di qualità sufficiente (confermato dai test), i turni espliciti non aggiungono valore.

**Soluzione adottata: `last_ai_message` + `last_ai_reason`**

Aggiungere a `ModerationState` (`state.py`):
```python
last_ai_message: Optional[str] = None     # testo ultimo intervento AI (normal mode)
last_ai_reason: Optional[str] = None      # reason ultimo intervento AI
```

Nel payload JSON mandato all'LLM:
```json
"last_ai_intervention": {
    "message": "Lucia, tu cosa ne pensi di questo punto?",
    "reason": "exclusion"
}
```

Con istruzione nel prompt:
```
Se `last_ai_intervention` è presente, tieni conto di cosa hai detto
l'ultima volta. Non ripetere lo stesso tipo di intervento se il problema
è stato affrontato nei turni successivi.
```

**Implementazione:**
1. Estendere `ModerationState` con i due campi
2. In `handle_human_turn_ended`, dopo un intervento AI in normal mode, salvare `last_ai_message` e `last_ai_reason` nello stato
3. In `_call_llm()`, aggiungere `last_ai_intervention` al payload JSON
4. In `_build_normal_mode_prompt()`, aggiungere l'istruzione nel prompt

**Impatto architetturale:**
- **Latenza:** zero overhead (stessa singola call LLM, ~20 token in più nel payload)
- **Codice:** modifiche minime a `state.py`, `service.py` (payload + prompt), serializzazione Redis

---

### 2.5 [DA IMPLEMENTARE] Metric-informed moderation per monopolization/exclusion

**Stato:** da implementare. Feedback tutor ricevuto (2026-04-21): contributo minor (non isolabile sperimentalmente con solo 2 condizioni), ma valido come buona teoria dietro il meccanismo di intervento. Tutti i parametri devono essere giustificati con citazione o motivazione solida.

**Data proposta:** 2026-04-21

**Motivazione:** oggi il prompt normal passa `turns_per_participant` come numeri grezzi all'LLM e gli chiede di valutare monopolizzazione ed esclusione senza soglie né metriche strutturate. Il risultato dipende dall'interpretazione del modello, non è riproducibile né calibrabile.

I dati per una valutazione quantitativa sono già disponibili ad ogni turno (il dict `turns_per_participant` è in `ModerationState`). L'idea è **pre-calcolare metriche di partecipazione nel backend e passarle all'LLM** come dato strutturato, con regole esplicite nel prompt.

**Approccio: soglie 2×/0.5× media (real-time) + Gini index (report)**

Due livelli distinti:

1. **Nel prompt LLM (real-time):** il backend calcola e passa all'LLM solo le soglie over/under-participator. Il Gini **non** entra nel prompt — non serve una soglia Gini per la decisione, e il suo valore varia con il numero di partecipanti rendendo difficile giustificare un threshold fisso.

2. **Nel report finale (post-sessione):** il Gini index resta come metrica descrittiva dell'equità complessiva. Non ha bisogno di una soglia giustificata — è un numero che si riporta e si commenta nel report.

**Payload aggiunto al JSON mandato all'LLM** (calcolato in `_call_llm()`):

```json
"participation_metrics": {
    "over_participators": ["Marco"],
    "under_participators": ["Lucia"],
    "avg_turns": 4.0
}
```

Dove:
- **over_participators**: chi ha parlato > 2× la media dei turni
- **under_participators**: chi ha parlato < 0.5× la media dei turni
- **avg_turns**: media turni per partecipante

**Regole nel prompt LLM (sezione aggiuntiva):**

```
### Metriche di partecipazione (pre-calcolate)
Il sistema ti fornisce `participation_metrics`:
- `over_participators`: partecipanti con turni > 2× la media
- `under_participators`: partecipanti con turni < 0.5× la media

Regole:
- Se ci sono nomi in `over_participators` → valuta monopolization
- Se ci sono nomi in `under_participators` → valuta exclusion
- Queste soglie si applicano solo se total_turns >= 6
- Se entrambe le liste sono vuote → ignora monopolization/exclusion
```

**Esempio con 3 partecipanti (setup sperimentale):**

| Scenario | Turni (A, B, C) | Media | Over (>2×) | Under (<0.5×) | Risultato |
|---|---|---|---|---|---|
| Equilibrato | 4, 3, 2 | 3.0 | nessuno (>6) | nessuno (<1.5) | Nessun flag |
| Esclusione | 5, 5, 1 | 3.7 | nessuno (>7.3) | C (<1.8) | Flag exclusion su C |
| Monopolizzazione + esclusione | 9, 2, 1 | 4.0 | A (>8) | C (<2) | Flag mono su A + exclusion su C |
| Troppo presto (turno 4) | 3, 1, 0 | 1.3 | A (>2.7) | C (<0.7) | **Nessun flag** (total_turns < 6) |

**Soglie e parametri con giustificazioni:**

| Parametro | Valore | Giustificazione |
|-----------|--------|----------------|
| Over-participator | > 2× media | Soglia usata in *"Observe, Ask, Intervene"* (Srinivasan et al., CHI 2025, arXiv:2501.10553) per rilevare partecipanti dominanti in meeting virtuali con AI agent |
| Under-participator | < 0.5× media | Soglia simmetrica dallo stesso paper per rilevare partecipanti sotto-rappresentati |
| Turni minimi | >= 6 | Con N=3 partecipanti (setup sperimentale), 6 turni = 2× N, ovvero almeno 2 opportunità di parola a testa in media. Sotto questa soglia la distribuzione è statisticamente non significativa |
| Cooldown | 60s (globale) | Principio di *minimum intervention* nella facilitazione: il facilitatore non reagisce a singoli eventi ma attende un pattern (Heron, 1999, *The Complete Facilitator's Handbook*). 60s con turni medi di ~10-15s = circa 4-6 turni tra un intervento e l'altro. Il cooldown è **globale** (ultimo intervento AI, qualsiasi reason) perché lo scopo è limitare la frequenza complessiva delle interruzioni, non la frequenza per-topic. Bypass per `conflict` e `user_request` (urgenza/esplicita richiesta) |
| Score >= 0.7 | 0.7 | Soglia conservativa che favorisce precision over recall: meglio un falso negativo (non intervenire quando serviva) che un falso positivo (interrompere la discussione inutilmente). Coerente con il principio di minimo intervento |

**Riferimento bibliografico principale:**
- Srinivasan et al. (2025), *"Observe, Ask, Intervene: Designing AI Agents for More Inclusive Meetings"*, CHI 2025 (arXiv:2501.10553) — usa soglie 2×/0.5× della media per rilevare squilibri di partecipazione in meeting virtuali con AI agent. Il nostro contesto è diverso (moderazione vocale multiparty con AI) ma il principio è lo stesso.

**Riferimenti complementari:**
- DiMicco & Bender (2007), *"Second Messenger"* — mostra che rendere visibile lo sbilanciamento partecipativo influenza il comportamento. Nel nostro caso il "destinatario" delle metriche è l'LLM moderatore.
- Jayagopi et al. (2012), *"Estimating Conversational Dominance in Multiparty Interaction"* — dominance come costrutto multi-dimensionale (sequenziale, partecipativo, quantitativo).
- Samrose et al. (2021), *"MeetingCoach"*, CHI 2021 — dashboard AI che monitora partecipazione e fornisce feedback post-meeting per migliorare inclusività.
- Heron (1999), *The Complete Facilitator's Handbook* — principio di minimo intervento e dimensione "confronting" (intervento immediato solo quando c'è danno al gruppo).

**Impatto architetturale:**
- **Latenza:** zero overhead. Stessa singola call LLM, payload leggermente più ricco.
- **Codice:** modifica a `_call_llm()` (calcolo metriche) e `_build_normal_mode_prompt()` (sezione prompt).
- **Filtro backend:** invariato. Cooldown 60s, soglia score 0.7, bypass per conflict/user_request restano identici.

**Note implementative (da affrontare in fase di sviluppo):**

1. **Inizializzare `turns_per_participant` con tutti i partecipanti della sessione.**
   Oggi il dict parte vuoto e si popola man mano che i partecipanti parlano. Un partecipante che non ha mai parlato non è nel dict — questo causa due problemi:
   - Le soglie over/under si calcolano su N-1 partecipanti invece di N (media falsata)
   - `under_participators` non include chi ha 0 turni (il caso più grave di esclusione)

   **Soluzione:** all'inizio della sessione (o al primo turno), popolare il dict con tutti i partecipanti dalla sessione DB con valore 0. Così le soglie e il Gini lavorano sempre sul numero reale di partecipanti. Verificare che non crei side-effect nei prompt e nei filtri esistenti (es. il prompt oggi vede solo chi ha parlato — con questa modifica vedrebbe anche chi ha 0 turni, il che è un vantaggio per la detection di exclusion).

2. **Ipotesi futura: usare speaking time invece dei conteggi turni.**
   Attualmente `turns_per_participant` conta il numero di turni, non la durata. Ma un turno di 5 secondi e uno di 60 secondi pesano uguale, il che non riflette la reale distribuzione della partecipazione. Il paper "Observe, Ask, Intervene" (CHI 2025) usa proprio lo speaking time come metrica base.

   **Possibile evoluzione:** tracciare `speaking_time_per_participant` (in secondi) accanto a `turns_per_participant`. Il dato è già disponibile nel backend: il push-to-talk ha timestamp di inizio e fine turno (`TurnManager.start_speak` / `end_speak`). Basta calcolare la differenza e accumularla in `ModerationState`.

   Il Gini e le soglie over/under-participator verrebbero calcolati sullo speaking time anziché sui turni, dando una misura più fedele. I turni resterebbero come metrica complementare (un partecipante con pochi turni ma lunghi vs uno con molti turni ma brevissimi sono pattern diversi).

   **Stato:** ipotesi da valutare. Se i test con i conteggi turni danno risultati soddisfacenti, non è necessario. Da implementare solo se si osserva che il conteggio turni non cattura bene gli squilibri reali.

**Valore per la tesi:**

1. **Contributo minor:** *metric-informed moderation* — il moderatore AI non opera solo su intuizione linguistica ma su dati quantitativi pre-calcolati. Separazione tra rilevamento quantitativo (deterministico, riproducibile) e formulazione qualitativa (delegata all'LLM). Non isolabile sperimentalmente, ma buona teoria dietro il meccanismo.

2. **Valutazione descrittiva:** il Gini index a fine sessione è una metrica oggettiva riportata nel report. Permette di descrivere l'equità della partecipazione nelle sessioni sperimentali.

3. **Riproducibilità:** soglie trasparenti, documentate e citate, a differenza dell'approccio "black box" dove l'LLM decide tutto da solo.

---

### 2.6 [DA IMPLEMENTARE] Refactoring soglia intervention_score: separare valutazione LLM da filtro backend

**Stato:** da implementare.

**Data proposta:** 2026-04-22

**Problema osservato:** oggi la soglia `intervention_score >= 0.7` è applicata **due volte**, in modo ridondante e controproducente:

1. **Nel prompt LLM** (`_build_normal_mode_prompt`, service.py:815): *"Imposta should_ai_speak: true SOLO se intervention_score >= 0.7"*
2. **Nel filtro backend** (`_decide_ai_intervention`, service.py:401): `if llm_score < 0.7: return False`

Se l'LLM segue le istruzioni, il check backend è ridondante (l'LLM ha già filtrato). Se non le segue (incoerenza interna score/should_speak), il backend fa da safety net — ma è un caso marginale.

**Il vero problema:** chiedere all'LLM di auto-filtrarsi con una soglia **distorce lo score**. L'LLM, dovendo decidere "parlo solo se >= 0.7", tende a gonfiare il punteggio per giustificare interventi che ritiene necessari, o a evitare di proporsi per situazioni borderline (0.5-0.6) dove un intervento leggero sarebbe utile. Il risultato è uno score binario (0.2-0.3 o 0.8-0.9) invece di una distribuzione calibrata.

Questo è confermato dalla letteratura sulla calibrazione degli LLM: quando si chiede a un modello di emettere una confidence verbale, lo score si ammassa nel range 80-100% indipendentemente dall'accuratezza reale (ECE > 0.377 per GPT-3/3.5/Vicuna). Il fenomeno è documentato come *overconfidence* nei self-reported scores.

**Soluzione proposta: separazione valutazione ↔ decisione**

1. **Togliere la soglia dal prompt.** L'LLM valuta liberamente e assegna un `intervention_score` onesto:
   ```
   Assegna un intervention_score da 0 a 1 che rifletta la gravità del problema:
   - 0.0-0.3: Nessun problema rilevante
   - 0.4-0.6: Situazione da monitorare ma non critica
   - 0.7-0.8: Problema evidente che richiede intervento
   - 0.9-1.0: Problema grave (insulti, off-topic totale)

   Imposta should_ai_speak: true se ritieni utile un intervento,
   indipendentemente dallo score.
   ```

2. **Il backend decide** con la soglia 0.7 se effettivamente far parlare il moderatore:
   ```python
   # _decide_ai_intervention() — filtro invariato
   if llm_score is not None and llm_score < 0.7:
       return False, None
   ```

**Vantaggi:**
- **Score più calibrato:** l'LLM non ha incentivo a gonfiare — può dare 0.5 a una situazione borderline senza auto-censura
- **Dato più utile per il report:** lo score riflette la valutazione genuina del modello, non un valore binario forzato
- **Soglia tarabile:** parametro backend che si può cambiare senza toccare il prompt
- **Separation of concerns:** LLM = valutazione qualitativa, backend = policy enforcement

**Giustificazioni e riferimenti:**

| Aspetto | Giustificazione |
|---------|----------------|
| Overconfidence LLM negli score verbali | Xiong et al. (2024), *"Can LLMs Express Their Uncertainty? An Empirical Evaluation of Confidence Elicitation in LLMs"*, ICLR 2024 — ECE > 0.377 per verbalized confidence; score ammassati in 80-100%. Tian et al. (2025), *"Mind the Confidence Gap: Overconfidence, Calibration, and Distractor Effects in LLMs"* — conferma il bias di overconfidence nei self-reported scores |
| Soglia conservativa (precision > recall) | Lee et al. (2023), *"To Err is AI: Imperfect Interventions and Repair in a Conversational Agent Facilitating Group Chat Discussions"*, CSCW 2023 — i false positive (interventi non necessari) in un CA facilitatore danneggiano fiducia e qualità della discussione più dei false negative. Giustifica una soglia backend che favorisce precision (non intervenire per errore) over recall (non perdere un intervento utile) |
| Separazione valutazione/decisione | Pattern generale in AI-assisted decision making: il modello fornisce una valutazione, il sistema applica la policy. Analogo al pattern "model proposes, human disposes" in AI-augmented moderation (Gorwa et al., 2020) |

**Impatto architetturale:**
- **Codice:** modificare `_build_normal_mode_prompt()` (rimuovere istruzione soglia), nessuna modifica a `_decide_ai_intervention()` (il filtro backend resta identico)
- **Latenza:** zero
- **Rischio:** minimo. Nel caso peggiore l'LLM propone più interventi (should_ai_speak=true con score basso), ma il filtro backend li blocca comunque

---

### 2.7 [DA IMPLEMENTARE] Skip chiamata LLM in fase non-ACTIVE

**Stato:** da implementare (quick win).

**Data proposta:** 2026-04-22

**Problema:** quando `session_phase != "ACTIVE"` (es. CONCLUSION), la chiamata LLM avviene comunque ma il filtro backend in `_decide_ai_intervention()` (service.py:413) ritorna sempre `False`. Si paga latenza e token per una risposta che sarà scartata.

**Soluzione:** nell'orchestrator (o all'inizio di `handle_human_turn_ended`), se `session_phase != "ACTIVE"` e `hard_action == NONE`:
- Aggiornare il summary con un append locale (senza LLM): `state.summary += " " + last_turn`
- Salvare lo stato
- Ritornare `ai_should_speak=False`

Il forced_conclusion ha il suo path dedicato (`call_llm_for_conclusion`) e non passa da qui, quindi non è impattato.

**Impatto:** risparmio di ~200-500ms e ~500 token per ogni turno in fase CONCLUSION. Minor ma gratuito.

---

## 3. Punti scartati

- **Race condition su `moderation_in_progress`:** in push-to-talk stretto (un solo utente parla alla volta) non si verifica. Gli unici residui teorici sono double-tap del bottone end_speak o retransmit WS, ma sono problemi lato frontend, non di design backend. Non vale la pena menzionarlo neanche nei limitations della tesi.

---

## 4. Checklist per ripresa lavoro

Quando si torna a questo documento per implementare:

- [x] **2.1 `interventions_log` nel report** → completato 2026-04-24. `state.py`, `service.py`, `sessions/services.py`, prompt report (base + MM + NASA + Lost at Sea), `pdf_service.py`, 10 test.
- [ ] **2.4 Last AI intervention nel payload** → estendere `ModerationState` con `last_ai_message`/`last_ai_reason`, aggiungere al payload in `_call_llm()`, aggiornare prompt in `_build_normal_mode_prompt()`.
- [ ] **2.5 Metric-informed moderation** → modificare `_call_llm()` e `_build_normal_mode_prompt()`. Inizializzare `turns_per_participant` con tutti i partecipanti.
- [ ] **2.6 Refactoring soglia** → modificare `_build_normal_mode_prompt()` (rimuovere istruzione soglia). Filtro backend invariato.
- [ ] **2.7 Skip LLM in fase non-ACTIVE** → modificare orchestrator o `handle_human_turn_ended`. Quick win.
- [ ] **2.3 Eliminazione/task-specific forced_summary** → da decidere con tutor. Se eliminato, valutare collasso di `evaluate_triggers_on_human_turn_end()`.
- [ ] **2.2 Tono per reason** → solo se test utente mostra messaggi troppo omogenei.
