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

### 2.1 [DA IMPLEMENTARE] Registrare `reason` nel report finale

**Stato:** deciso, da implementare quando si passa alla fase operativa.

**Motivazione:** oggi `reason` è solo log, sparisce alla fine della sessione. Per la valutazione empirica della tesi (NASA Moon Survival) serve sapere quanti interventi AI ci sono stati e di che tipo. Questo dato è anche utile nel PDF di session report consegnato agli utenti.

**Implementazione proposta:**

1. Estendere `ModerationState` (`apps/moderation/state.py`) con due campi:
   ```python
   interventions_log: list[dict] = field(default_factory=list)
   # Ogni entry: {ts, reason, score, speaker, message}
   forced_events_log: list[dict] = field(default_factory=list)
   # Ogni entry: {ts, type: "forced_summary"|"forced_conclusion", correction_reason}
   ```

2. In `ModerationService.handle_human_turn_ended` (`service.py:76`), dopo il filtro backend:
   - se `ai_should_speak=True` e `mode=="normal"`: append a `interventions_log`
   - se `mode` è forced: append a `forced_events_log`

3. In `apps/reports/` (report PDF): leggere i log da Redis (prima che la sessione venga chiusa) o persisterli su PostgreSQL alla transizione CLOSED.

4. Nel PDF produrre sezione "Statistiche di moderazione":
   - Totale interventi AI
   - Breakdown per reason (es: 3 off_topic, 2 user_request, 1 monopolization)
   - Eventi forced (N forced_summary, 1 forced_conclusion)

**Considerazione tesi:** questo dato è cruciale per dimostrare empiricamente il comportamento del moderatore nella valutazione NASA Moon. Senza queste statistiche, il capitolo di valutazione manca di metriche oggettive sul moderatore stesso.

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

---

### 2.4 [IN DISCUSSIONE] Due chiamate LLM separate: Decision + Generation

**Stato:** in discussione. Punto più interessante architetturalmente, merita approfondimento.

**Problema osservato:** l'utente ha notato che, nonostante il prompt dica esplicitamente "NON usare il summary per valutare problemi puntuali" (`service.py:792`), l'LLM continua a richiamare utenti per comportamenti già risolti in turni precedenti. Questa è **contaminazione del summary**: il modello non riesce a "spegnere" un pezzo di contesto solo perché glielo chiediamo nel prompt.

**Caso concreto di fallimento:**
- T-4: Marco alza la voce → AI interviene, calma, risolto
- T-3, T-2, T-1: discussione civile
- T: Marco fa un intervento neutro → l'LLM legge il summary, "sente" ancora la tensione storica, imposta `score=0.75 reason=conflict` → interviene **di nuovo** su un problema già chiuso.

**Pattern proposto: due call sequenziali**

**Call 1 — DECISION (senza summary)**
```
Input: {last_turn, participants.turns, session.total_turns, scenario}
Output: {should_speak: bool, reason: str, score: float}
Scopo: decidere SE intervenire
Summary NON viene mai mostrato → impossibile contaminazione storica
```

**Call 2 — GENERATION (con summary, solo se should_speak=true)**
```
Input: {reason, summary, last_turn, participants.turns, scenario}
Output: {message_to_say, updated_summary}
Scopo: generare il messaggio e aggiornare il summary
Qui il summary è legittimo (coerenza linguistica + aggiornamento)
La decisione è già presa, il summary non può più influenzarla
```

**Trade-off:**
- **Latenza:** Call 2 scatta solo quando `should_speak=true`, tipicamente <20% dei turni. Overhead medio stimato: +100-200ms per turno.
- **Costo token:** Call 1 è corta (no summary → prompt e input molto più piccoli). Aumento totale stimato ~1.3-1.5× rispetto a una call singola, non 2×.
- **Complessità:** due prompt da mantenere invece di uno, ma con separation of concerns più pulita.

**Rischio da valutare:** Call 1 senza summary ha abbastanza contesto per distinguere "conflict vero" vs "disaccordo civile"? Dipende da quanto bene calibriamo il prompt di Call 1 con esempi one-shot espliciti.

**Valore per la tesi:**
Questa è una **novità architetturale** che la letteratura multiparty+AI moderation non copre. Si può formulare come contributo esplicito:

> *We propose a two-stage moderation pipeline: a decision stage that evaluates intervention need on immediate turn data only (avoiding historical context bias), and a generation stage that produces contextually-coherent messages using the accumulated summary. This separation addresses a common failure mode where moderators re-address already-resolved issues due to context contamination.*

Valutazione empirica fattibile: baseline (single call) vs treatment (two-stage), metrica = tasso di falsi positivi (interventi su problemi già risolti). Con 10-20 sessioni NASA Moon è un esperimento realistico.

**Punti ancora da chiarire nella discussione:**
- L'utente ha dubbi concreti, da approfondire in conversazione prima di definire l'implementazione.
- Decidere se la soglia `0.7` e il cooldown `60s` vanno ricalibrati nel nuovo regime.

---

## 3. Punti scartati

- **Race condition su `moderation_in_progress`:** in push-to-talk stretto (un solo utente parla alla volta) non si verifica. Gli unici residui teorici sono double-tap del bottone end_speak o retransmit WS, ma sono problemi lato frontend, non di design backend. Non vale la pena menzionarlo neanche nei limitations della tesi.

---

## 4. Checklist per ripresa lavoro

Quando si torna a questo documento per implementare:

- [ ] **2.1 Reason nel report** → stato attuale del codice: da modificare `state.py`, `service.py:76`, `apps/reports/`. Nessun blocker.
- [ ] **2.4 Double-call** → prima decidere definitivamente col tutor, poi progettare prompt Call 1 + Call 2.
- [ ] **2.3 Task-specific forced_summary** → dopo prima round di test NASA Moon, decidere tra eliminazione totale o capability.
- [ ] **2.2 Tono per reason** → solo se test utente mostra messaggi troppo omogenei.
