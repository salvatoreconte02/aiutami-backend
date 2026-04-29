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

### 2.3 [COMPLETATO] Rimozione completa di `forced_summary`

**Stato:** implementato (2026-04-24). Rimosso completamente il meccanismo di ricapitolazione periodica ogni 6 turni.

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

### 2.4 [COMPLETATO] Memoria interventi recenti per-reason + cooldown differenziato

**Stato:** implementato (2026-04-27).

**Data proposta:** 2026-04-24
**Data implementazione:** 2026-04-27

**Problema originale:** l'LLM non sa cosa ha detto nel suo ultimo intervento → ripetizione inutile e mancato riconoscimento della risoluzione.

**Evoluzione del design** (discutendo con il tutor sul rischio di "moderator nags every 60s" con metriche cumulative): la versione iniziale prevedeva un singolo `last_ai_message` + `last_ai_reason`. Ma se l'ultimo intervento è di tipo X (es. off_topic) e la situazione su Y (es. monopolization) persiste, la memoria globale **perde il contesto del reason precedente**. Per i reason cumulativi (mono/excl), il cumulativo decade lentamente → il sistema riprodurrebbe lo stesso intervento ogni 60s.

**Soluzione adottata: memoria per-reason via `interventions_log` + cooldown differenziato.**

Insight chiave: `interventions_log` (Feature 2.1) **già contiene** tutti gli interventi con `{ts, reason, message, score, speaker}`. Non serve una nuova struttura, basta interrogarla per `reason`.

**Cosa è stato fatto:**

1. **`apps/moderation/state.py`** — nuovo helper puro `last_intervention_for_reason(state, reason) -> dict | None`. Scan reverse del log, ritorna la entry più recente con il reason richiesto.

2. **`apps/moderation/service.py`** — costanti per cooldown per-reason:
   ```python
   COOLDOWN_OVERRIDES = {
       "monopolization": timedelta(minutes=3),  # cumulative, slow to resolve
       "exclusion": timedelta(minutes=2),       # dai tempo all'invitato
   }
   AI_INTERVENTION_COOLDOWN = timedelta(seconds=60)  # default off_topic/altri
   COOLDOWN_BYPASS_REASONS = {"conflict", "user_request"}  # invariato
   ```
   Giustificazione: Heron (1999), minimum intervention principle. Reason puntuali (off_topic) restano a 60s.

3. **`_decide_ai_intervention()`** — riscritto: il cooldown ora confronta col l'ultimo intervento dello **STESSO reason** (via helper), non più globalmente. Backend filter come rete di sicurezza: anche se l'LLM ignora le istruzioni, il cooldown per-reason blocca la ripetizione.

4. **`_call_llm()`** — accetta `interventions_log` come kwarg. Nuovo metodo `_extract_last_interventions_by_reason()` produce per il payload solo le voci sui reason **cumulativi** (monopolization, exclusion). Off_topic/conflict/user_request sono puntuali e non hanno bisogno di memoria storica.

   Payload nuovo campo:
   ```json
   "last_interventions_by_reason": {
       "monopolization": {
           "message": "Sentiamo gli altri.",
           "minutes_ago": 1.5
       }
   }
   ```

5. **Prompt normal mode** — nuova sezione "Memoria interventi recenti (cumulative reasons)" che istruisce l'LLM:
   - monopolization entro 3 min → NON ri-flaggare a meno che la situazione sia drasticamente peggiorata
   - exclusion entro 2 min → NON ri-flaggare sulla stessa persona, dai tempo al gruppo

6. **`last_ai_intervention_at`** — campo lasciato in `ModerationState` ma non più usato per le decisioni di cooldown. Ancora settato a ogni intervento per backward compat e telemetria. Cleanup in futuro.

7. **Test (13 nuovi):**
   - `LastInterventionForReasonTests` (5): empty log, log con reason, multipli reason, senza reason, duplicati.
   - `PerReasonCooldownTests` (8): mono blocked sotto 3min / speak dopo, excl blocked sotto 2min / speak dopo, off_topic blocked sotto 60s / speak dopo, cooldown indipendente tra reason diversi, no-prior-intervention parla.
   - `CooldownBypassTests` aggiornato (setup ora usa `interventions_log` invece di `last_ai_intervention_at`).
   - `CallLLMStructuredInputTests` esteso (3 nuovi): empty log → `{}`, mono recente → entry in payload, reason puntuali esclusi.

**Runtime flow:**
```
AI interviene su monopolization → entry in interventions_log (Redis)
Turno successivo:
  _call_llm payload include last_interventions_by_reason.monopolization
  LLM legge "minutes_ago: 0.5" e l'istruzione → non ri-flagga
  Se LLM ignorasse → backend filter blocca (cooldown 3min per reason)
Off_topic concorrente → cooldown indipendente (default 60s), orologio separato
```

**266/266 test verdi** dopo l'implementazione.

**Impatto architetturale:** zero overhead latency (~30-50 token in più nel payload solo se ci sono interventi cumulative recenti). Nessuna nuova migration DB, nessuna struttura Redis aggiuntiva.

---

### 2.5 [COMPLETATO] Metric-informed moderation per monopolization/exclusion

**Stato:** implementato (2026-04-24). Feedback tutor ricevuto (2026-04-21): contributo minor (non isolabile sperimentalmente con solo 2 condizioni), ma valido come buona teoria dietro il meccanismo di intervento. Tutti i parametri devono essere giustificati con citazione o motivazione solida.

**Data proposta:** 2026-04-21
**Data implementazione:** 2026-04-24

**Cosa è stato fatto:**

1. **`apps/moderation/metrics.py`** (nuovo) — helper puro `compute_participation_metrics(turns_per_participant, *, over_threshold=2.0, under_threshold=0.5, min_turns_factor=2)` che ritorna `{over_participators, under_participators, avg_turns, min_turns_reached}`. Nessuno state, nessun I/O. Liste ordinate deterministicamente (under: turn count ascendente = più escluso per primo; over: turn count discendente = più dominante per primo), tiebreak alfabetico.

2. **`apps/moderation/state.py`** — `ModerationState.initial(participants=...)` accetta lista opzionale e popola `turns_per_participant` con tutti i nomi a 0. Nuovo helper privato `_fetch_participant_names(session_id)` fa lookup DB (`SessionParticipant.select_related("user")`) con stessa logica del turn consumer (`display_name or get_username()`). `load_moderation_state(session_id)` chiama il lookup quando crea state fresco, fallback graceful a lista vuota su errore DB.

3. **`apps/moderation/service.py`** — in `_call_llm()`: import del helper, calcolo metrics prima della costruzione payload. Nuovo payload: `participants.names` (lista, non più dict), `participation_metrics` come top-level key con le 4 chiavi del helper. Rimosso `participants.turns` per evitare che l'LLM rifaccia il calcolo.

4. **Prompt normal mode** (`_build_normal_mode_prompt`) riscritto:
   - Sezione "### Problemi CUMULATIVI → guarda `participation_metrics`" sostituisce il vecchio blocco che chiedeva all'LLM di valutare i contatori grezzi. Istruzioni esplicite su `min_turns_reached` e "fidati delle liste, non rifare tu il calcolo".
   - Nuova sezione "## Come intervenire su monopolization / exclusion" con due principi chiave: **invitare > correggere** (target dell'intervento è il sotto-partecipatore, non il dominante — rif. Hall & Watson, Heron, Srinivasan et al.) e **invito contestuale non banale** (usa summary/last_turn per agganciarsi a un punto specifico). Include esempi ✅/❌ per exclusion, monopolization, e caso misto.
   - Lunghezza intervento alzata da 20-30 a 30-40 parole per ospitare l'aggancio contestuale.

5. **Soglia `min_turns_reached` ora dinamica:** `total_turns >= 2 × N` (dove N è il numero di partecipanti) invece del vecchio hardcoded `>= 6`. Con N=3 (setup sperimentale) coincide col valore precedente, ma scala per N=2 (task generic) e N>3.

6. **Test (17 nuovi, tutti verdi):**
   - `apps/moderation/tests_metrics.py` (nuovo) — 12 test unit secchi per il helper: empty dict, all-zero, equal distribution, exclusion classica (5,1,0), mono+exclusion (9,2,1), min_turns sotto/al/sopra threshold, scaling N, ordering under ascendente/over descendente, custom thresholds, strict inequality alla soglia.
   - `apps/moderation/tests.py` — nuovi test in `ModerationStateTests` (initial con/senza participants) e nuova classe `LoadModerationStateInitializesFromDBTests` (3 test: state nuovo popolato da DB, idempotenza su state esistente, fallback su session inesistente). 2 test esistenti aggiornati alla nuova forma payload.

**Runtime flow:**
```
Prima chiamata load_moderation_state(session_id) → lookup DB partecipanti →
ModerationState.initial(participants=[marco,lucia,anna]) → Redis
Ogni turno → speaker++ in turns_per_participant
Ogni _call_llm → compute_participation_metrics(turns) → payload enriched →
                 LLM usa `participation_metrics` e `names` (non più `turns`)
```

**253/253 test verdi** dopo l'implementazione.

**Filtro backend invariato:** `_decide_ai_intervention()` non toccato. Cooldown 60s, soglia score 0.7, bypass conflict/user_request restano identici. La feature opera a monte (input LLM), non a valle (decisione).

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

2. **Speaking time invece dei conteggi turni — IMPLEMENTATO 2026-04-27 (vedi 2.8).**
   Switch completo da turn count a speaking time cumulativo (secondi PTT-held per partecipante). Vedi sezione 2.8 per dettagli implementativi e giustificazioni.

**Valore per la tesi:**

1. **Contributo minor:** *metric-informed moderation* — il moderatore AI non opera solo su intuizione linguistica ma su dati quantitativi pre-calcolati. Separazione tra rilevamento quantitativo (deterministico, riproducibile) e formulazione qualitativa (delegata all'LLM). Non isolabile sperimentalmente, ma buona teoria dietro il meccanismo.

2. **Valutazione descrittiva:** il Gini index a fine sessione è una metrica oggettiva riportata nel report. Permette di descrivere l'equità della partecipazione nelle sessioni sperimentali.

3. **Riproducibilità:** soglie trasparenti, documentate e citate, a differenza dell'approccio "black box" dove l'LLM decide tutto da solo.

---

### 2.6 [COMPLETATO] Refactoring soglia intervention_score + modulazione tono via score

**Stato:** completato 2026-04-29.

**Data proposta:** 2026-04-22

**Data implementazione:** 2026-04-29

#### Cosa e' stato fatto

Tre modifiche compatte che si rinforzano a vicenda:

1. **Rimozione di `should_ai_speak` dall'output LLM.** Il campo non e' piu' richiesto nel prompt; in `_call_llm` viene derivato da `bool(message_to_say) and reason != "all_ok"`. Il backend continua a riceverlo come prima (zero impatto a valle), ma il modello non e' piu' costretto a dichiararlo.

2. **Soglia score abbassata e differenziata.**
   - Nuova costante `MIN_INTERVENTION_SCORE = 0.4` (allineata alla scala "0.4-0.6 = situazione da monitorare" del prompt).
   - Nuova costante `SCORE_BYPASS_REASONS = {"conflict", "user_request"}` simmetrica a `COOLDOWN_BYPASS_REASONS`: i reason responsivi bypassano il filtro score.
   - `_decide_ai_intervention` filtra `score < 0.4` solo per i reason discrezionali (off_topic, monopolization, exclusion, ground_rule_violation).

3. **Modulazione del tono via score.** La sezione "Stile" del prompt e' diventata "Stile e modulazione del tono": lo score guida il *registro* del messaggio (0.4-0.5 soft suggestivo, 0.6-0.7 diretto cortese, 0.8-0.9 fermo esplicito, 0.9-1.0 reset netto). Lo score smette di essere un gate ridondante e diventa un parametro causalmente connesso al messaggio.

#### Risultati misurati con `scripts/probe_moderation.py`

Probe con 21 casi × 3 run = 63 chiamate LLM su `gpt-4o-mini` (temperature 0.4), prima e dopo le modifiche:

| Caso | Prima (reason+speak) | Dopo (reason+speak) |
|---|---|---|
| `rule4_real_log_quote` (caso reale dei log) | 0/3 + 0/3 (cieco) | **3/3 + 3/3** |
| `rule4_paraphrase_alzata` | 1/3 + 0/3 (instabile) | **3/3 + 3/3** |
| `rule5_frustration` | 1/3 + 1/3 (instabile) | **3/3 + 3/3** |
| `user_request_help` | 1/3 + 0/3 | **3/3 + 3/3** |
| `off_topic_clear` | 3/3 + 1/3 | **3/3 + 3/3** |
| Tutti gli altri casi base | gia' OK | gia' OK |

PASS aggregato: **8/13 → 12/13** (l'unico residuo `monopolization_late` era un errore nei dati di test, fixato successivamente).

**Effetto inatteso e rilevante per la tesi:** la rimozione della soglia dal prompt ha sbloccato anche la **detection delle ground rules su parafrasi**, che era stabilmente cieca (0/3). Interpretazione: il modello, davanti a `"intervieni solo se score >= 0.7"` su un caso ambiguo (parafrasi di rule violation, non match letterale dei marker), preferiva il path conservativo `all_ok 0.0` invece di classificare correttamente. Tolta la pressione decisionale, lo score smette di essere proxy della decisione e il modello classifica per quello che e'. Confermato dalla zero-varianza post-fix: tutti i casi che prima oscillavano (es. `rule5_frustration` 0.00/0.80/0.00) ora producono lo stesso valore stabilmente.

**Casi adversarial (8 nuovi)**: il moderatore ricusa correttamente in 3/3 prompt injection, richieste di info esterne, richieste di rivelare il system prompt, richieste di partecipare/giudicare. Tono modulato in maniera coerente con lo score.

#### Caveat osservato

La modulazione tono ha *gonfiato leggermente* gli score nei casi base (off_topic da 0.6→0.8, ground rules da 0.7→0.8): il modello associa "tono piu' esplicito = score piu' alto" e tende a classificare piu' interventi nella fascia 0.8. Lo score perde un po' di calibrazione "gravita' oggettiva pura" guadagnando "intensita' del registro che voglio usare". Per la tesi e' ancora difendibile come graduated intervention (Heron 1999), e operativamente non causa problemi: tutti i casi "veri positivi" hanno score >> 0.4.

#### Codice toccato

- `apps/moderation/service.py`:
  - costanti `SCORE_BYPASS_REASONS`, `MIN_INTERVENTION_SCORE` (riga ~50)
  - `_build_normal_mode_prompt`: rimosso "Off-topic parziali", riscritta sezione "Stile e modulazione del tono", riscritta sezione "Punteggio" come puramente descrittiva, rimosso `should_ai_speak` dallo schema JSON
  - `_call_llm`: parsing aggiornato (derivazione `should_ai_speak`)
  - `_decide_ai_intervention`: bypass score per reason responsivi, soglia 0.4
- `apps/moderation/tests.py`:
  - `test_build_normal_mode_prompt_contains_json_output_spec`: aggiornato (assertNotIn `should_ai_speak`)
  - nuova classe `ScoreBypassTests` (4 test)
- `scripts/probe_moderation.py`:
  - 21 casi (13 base + 8 adversarial), parametro `--runs N`, simulazione filtro backend (`backend_speaks`), output JSON+MD in `scripts/probe_results/`

#### Test suite

`265 → 269 test, tutti verdi`.

#### Riferimenti aggiornati

| Aspetto | Riferimento |
|---|---|
| Overconfidence verbale LLM (giustifica rimozione soglia dal prompt) | Xiong et al. 2024 ICLR; Tian et al. 2025 |
| Soglia precision-over-recall (filtro 0.4 backend) | Lee et al. 2023 CSCW |
| Modulazione intensita' intervento (tono via score) | Heron 1999 *minimum intervention principle*; Lee et al. 2023 |
| Separation valutazione/decisione | Gorwa et al. 2020 |

---

### 2.6 [originale, kept for traceability] Refactoring soglia intervention_score: separare valutazione LLM da filtro backend

**Stato:** sostituito dal blocco completato qui sopra (2026-04-29).

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

### 2.8 [COMPLETATO] Speaking time come metrica di partecipazione

**Stato:** implementato (2026-04-27).

**Data implementazione:** 2026-04-27

**Motivazione:** il paper di riferimento Srinivasan et al. (CHI 2025, arXiv:2501.10553) usa `cumulative speaking time at 1-second intervals` (§4.1), non turn count. La nostra implementazione iniziale (Feature 2.5) usava turn count come approssimazione. Problema osservato: un turno di 60s e uno di 5s pesano uguale → un partecipante che fa pochi turni ma lunghi non viene flaggato come monopolizzatore, e uno che fa molti turni brevissimi sembra ben rappresentato anche se è marginale. Lo speaking time cattura la dinamica reale.

**Decisioni di scope (concordate con utente):**

1. **Sostituzione totale di turn count con speaking time** (no doppio binario). Codice più pulito, una sola sorgente di verità.
2. **Min threshold elapsed clock time, allineato al paper:** `session_elapsed_seconds >= 480` (8 min). Le nostre sessioni sono ~30 min come quelle del paper, quindi 8/30 ≈ 27% del meeting. Argomentazione tesi diretta: "stesso setup, stessa soglia".
3. **Soglia under conservativa:** mantenuto `< 0.5 × media` invece di allineare al paper (`< media`). Argomentazione: il paper fa intervento one-shot, noi moderazione continua → precision over recall, evitiamo false positive su persone marginalmente sotto media. Documentato come deviazione motivata.

**Cosa è stato fatto:**

1. **`apps/moderation/metrics.py`** — `compute_participation_metrics()` riscritto:
   - Input: dict `{nome: secondi_cumulativi}` e `elapsed_seconds`
   - Output: chiavi rinominate `avg_speaking_time_s`, `min_time_reached`
   - Default `min_elapsed_seconds=480.0` (8 min, paper)
   - Soglie `over=2×`, `under=0.5×` invariate
   - Helper agnostic ai numeri (accetta int o float)

2. **`apps/moderation/state.py`**:
   - `turns_per_participant: dict[str,int]` → `speaking_time_per_participant: dict[str,float]`
   - Nuovi campi `session_started_at: Optional[datetime]` (per elapsed) e `current_turn_started_at: Optional[datetime]` (timer del turno corrente)
   - `_fetch_participant_names` → `_fetch_session_meta(session_id) -> (names, started_at)` con un solo lookup DB
   - Save/load Redis aggiornati

3. **`apps/moderation/service.py`**:
   - Nuovo classmethod `record_human_turn_start(session_id, speaker_name)`: stamping `current_turn_started_at = utcnow()`
   - `handle_human_turn_ended()`: legge `current_turn_started_at`, calcola `delta = now - start`, accumula in `speaking_time_per_participant[speaker]`, clear timer
   - Calcolo `elapsed_seconds = now - session_started_at` passato a `_call_llm`
   - Payload arricchito: `session.elapsed_seconds`, `session.total_speaking_time_s`, `participation_metrics` su speaking time
   - Prompt aggiornato: "speaking time" e "secondi" invece di "turni", `min_time_reached` invece di `min_turns_reached`

4. **`apps/turns/ws_consumer.py`**:
   - In `_handle_request_speak`, dopo success, chiama `ModerationService.record_human_turn_start()`
   - Nessuna modifica a `TurnManager` (timing tracciato interamente dal modulo moderation)

5. **Test (14 nuovi/aggiornati, tutti verdi):**
   - `tests_metrics.py`: 10 test riscritti per `elapsed_seconds`, nuove key, test 8-min threshold default, test backward compat con int input
   - Nuova classe `SpeakingTimeAccumulationTests` (6 test): accumulo singolo turno, accumulo cross-turno, no-speaker-name, no-timer (reconnection edge case), `record_human_turn_start` setta timer, skip se no speaker
   - Aggiornati i test che assumevano `turns_per_participant` o `min_turns_reached`

**Limiti dichiarati onestamente:**

Misuriamo speaking time come **PTT-held duration** (mic-open time), non come reale voice activity (VAD). In un sistema PTT disciplinato il bias è ~10-20% per turno (lag press/release) e approssimativamente uniforme tra utenti, quindi per soglie threshold-based (over/under rispetto alla media) l'errore raramente flippa la decisione. L'approccio comparable nel paper (DOM-based VAD da Zoom) è anch'esso un proxy con bias propri. VAD events da OpenAI Realtime resta come future work.

**Impatto runtime:**
- Nessun overhead: latency invariata, payload ~30 token in più (elapsed + speaking_time fields)
- Nessuna migration DB
- Backwards compat: state Redis esistenti pre-deploy si caricano graceful (campo nuovo default `{}`/`None`); le sessioni in corso al momento del deploy partono da speaking_time vuoto fino al prossimo turno

**267/267 test verdi** dopo l'implementazione.

---

### 2.9 [COMPLETATO] Ground rule violation enforcement (runtime)

**Stato:** implementato (2026-04-27).

**Data implementazione:** 2026-04-27

**Motivazione (parte della RQ tesi):** confronto sessioni con moderatore vs sessioni senza moderatore. Questa feature aggiunge al moderatore "acceso" il compito di **far rispettare a runtime** le 6 ground rules di Hall & Watson (1970), oltre alle reasons già coperte. Prima: le 6 rules erano comunicate ai partecipanti nell'intro TTS e iniettate nel system prompt LLM come testo informativo, ma il moderatore non agiva su di esse.

**Decisione cruciale: enforcement parziale per onestà metodologica.** Delle 6 rules originali, **enforciamo a runtime solo le 3 con marker linguistici puntuali** rilevabili da `last_turn`:
- ✅ **Rule 2** — "io vinco/tu perdi" (impasse): ultimatum espliciti
- ✅ **Rule 4** — voto/media/compromesso: keyword chiari ("votiamo", "media", "spacchiamo")
- ✅ **Rule 5** — frustrazione su discussione (differenze come ostacolo)
- ❌ **Rules 1, 3, 6** — richiedono storico turni (ripetizione, transizione di posizione, esplorazione precedente). Il `summary` è una sintesi narrativa compressa del *contenuto*, non un log *comportamentale*. Forzare detection produrrebbe falsi positivi.

Le rules 1/3/6 **restano nell'intro TTS ai partecipanti** (informazione completa, niente cambia) **e nel system prompt LLM** come parte di SCENARIO_BLOCK, ma non vengono enforced a runtime.

**Decisioni di design (concordate con utente):**
1. Reason singolo `ground_rule_violation` (copre tutte e 3 le rules enforced)
2. Tasks scope: **NASA Moon + Lost at Sea** (entrambe usano Hall & Watson, identicamente). Murder Mystery e Generic non toccati.
3. Memoria payload: **puntuale**, niente entry in `last_interventions_by_reason`. Cooldown standard 60s (default).
4. Priorità reason in caso di overlap: `conflict > user_request > ground_rule_violation > off_topic > monopolization/exclusion > all_ok`.
5. Stile intervento: cita la rule **per concetto** (non per numero), 1-2 frasi, 30-40 parole, gentile reminder.

**Cosa è stato fatto:**

1. **`apps/tasks/base.py`** — nuovo metodo `enforces_ground_rules() -> bool` (default `False`).

2. **`apps/tasks/nasa_moon/task.py` e `apps/tasks/lost_at_sea/task.py`** — override a `True`.

3. **`apps/moderation/service.py::_build_normal_mode_prompt(task)`** — usa `task.enforces_ground_rules()` per riempire 5 placeholder condizionali:
   - `__GR_QUANDO_BULLET__`: bullet 6 in "## Quando intervenire"
   - `__GR_VALUTAZIONE_SECTION__`: subsection con detection per rules 2/4/5 + marker linguistici + esempi ✅/❌
   - `__GR_INTERVENTO_SECTION__`: subsection con esempi di intervento contestuali (cita la rule per concetto)
   - `__GR_PRIORITY_LINE__`: ground_rule_violation in priorità tra reason
   - `__REASON_ENUM__`: enum dinamico (con o senza `ground_rule_violation`)
   
   Sezione "## Priorità tra reason" sempre presente (anche per task senza enforcement, ma senza la riga ground_rule_violation).

4. **Filtro backend `_decide_ai_intervention`** — invariato. `ground_rule_violation` non in `COOLDOWN_BYPASS_REASONS` né in `COOLDOWN_OVERRIDES`, quindi cooldown default 60s. `_extract_last_interventions_by_reason` invariato (resta solo mono/excl).

5. **`apps/moderation/intro.py`, `nasa_moon/prompts.py`, `lost_at_sea/prompts.py`** — invariati. I partecipanti continuano a sentire tutte e 6 le rules nell'intro TTS.

6. **Test (13 nuovi):**
   - `EnforcesGroundRulesTests` (4): nasa_moon True, lost_at_sea True, murder_mystery False, generic False
   - `GroundRuleViolationPromptTests` (6): presenza/assenza condizionale di sezione e reason nell'enum, marker linguistici espliciti per rules 2/4/5, "Priorità tra reason" presente per tutti i task
   - `GroundRuleViolationCooldownTests` (3): blocked sotto 60s, speak dopo 60s, NON in cumulative payload

**Argomentazione tesi:**
> *"We operationalize runtime enforcement on rules 2, 4, 5 — those whose violations have unambiguous linguistic markers in the current turn. Rules 1, 3, 6 require multi-turn conversational history that the running summary representation does not preserve, and are therefore left to future work with extended context. Notably, rule 4 (avoidance of majority voting / averaging / compromise) is the most diagnostic of the Hall & Watson framework — Hall & Watson designed the original 1970 NASA task explicitly to test resistance to majority voting as the central failure mode."*

**Impatto runtime:**
- Zero overhead per task senza ground rules (Murder Mystery, Generic): prompt invariato
- Token aggiuntivi solo per NASA Moon e Lost at Sea (~250 token in più nel system prompt per le sezioni condizionali)
- Nessuna migration DB, nessuna struttura Redis nuova

**280/280 test verdi** dopo l'implementazione.

---

## 3. Punti scartati

- **Race condition su `moderation_in_progress`:** in push-to-talk stretto (un solo utente parla alla volta) non si verifica. Gli unici residui teorici sono double-tap del bottone end_speak o retransmit WS, ma sono problemi lato frontend, non di design backend. Non vale la pena menzionarlo neanche nei limitations della tesi.

---

## 4. Checklist per ripresa lavoro

Quando si torna a questo documento per implementare:

- [x] **2.1 `interventions_log` nel report** → completato 2026-04-24. `state.py`, `service.py`, `sessions/services.py`, prompt report (base + MM + NASA + Lost at Sea), `pdf_service.py`, 10 test.
- [x] **2.4 Memoria per-reason + cooldown differenziato** → completato 2026-04-27. Helper `last_intervention_for_reason` su `interventions_log` (no nuova struttura), cooldown per-reason (mono 3min, excl 2min, default 60s), payload `last_interventions_by_reason` solo per reason cumulativi, sezione prompt "Memoria interventi recenti". 13 nuovi test.
- [x] **2.5 Metric-informed moderation** → completato 2026-04-24. Helper puro `metrics.py`, `ModerationState.initial(participants=...)` con lookup DB in `load_moderation_state`, payload con `participation_metrics` + `participants.names` (no più `turns` raw), prompt con nuovo blocco "CUMULATIVI" + sezione "Come intervenire" (invitare > correggere, invito contestuale, 30-40 parole). Min turns dinamico `2×N`. 17 nuovi test.
- [x] **2.6 Refactoring soglia + modulazione tono** → completato 2026-04-29. Rimosso `should_ai_speak` dall'output LLM (derivato in `_call_llm`), soglia score abbassata a 0.4 con `SCORE_BYPASS_REASONS={conflict, user_request}`, modulazione tono via score (4 fasce con esempi). Side-effect: detection ground rules su parafrasi e' passata da 0/3 a 3/3 sui casi che prima erano ciechi (rule4 reale dai log). Tool: `scripts/probe_moderation.py` con 21 casi (incl. adversarial) e simulazione backend filter. 4 nuovi test, 269 totali verdi.
- [ ] **2.7 Skip LLM in fase non-ACTIVE** → modificare orchestrator o `handle_human_turn_ended`. Quick win.
- [x] **2.3 Rimozione forced_summary** → completato 2026-04-24. Rimosso completamente: costante, enum, metodi LLM dedicati, trigger, orchestrator handler, stato Redis, prompt task-specifici, ~17 test.
- [x] **2.8 Speaking time** → completato 2026-04-27. Switch da turn count a speaking time (secondi PTT-held). Min threshold dinamico → fisso 8 min (paper). State con `speaking_time_per_participant`, `session_started_at`, `current_turn_started_at`. Nuovo `record_human_turn_start` chiamato dal consumer in request_speak. Soglie 2× / 0.5× invariate (deviazione motivata vs paper). 14 test, 267 totali.
- [x] **2.9 Ground rule violation enforcement** → completato 2026-04-27. Nuovo reason `ground_rule_violation` per i task con `enforces_ground_rules()=True` (NASA Moon + Lost at Sea). Enforcement runtime solo di rules 2/4/5 (puntuali, marker linguistici robusti); rules 1/3/6 lasciate come informazione (richiedono storico). Cooldown default 60s. Sezione prompt condizionale + sezione "Priorità tra reason". 13 test, 280 totali.
- [ ] **2.2 Tono per reason** → solo se test utente mostra messaggi troppo omogenei.
