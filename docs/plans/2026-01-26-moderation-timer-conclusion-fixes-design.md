# Design Document: Fix Moderation Timer e FORCED_CONCLUSION

**Data**: 2026-01-26
**Stato**: In revisione
**Autore**: Claude + Salvatore

---

## 1. Contesto

Durante l'analisi di coerenza tra il documento tecnico di moderazione (`docs/documentazione_moderazione.docx`) e l'implementazione in `apps/moderation/`, sono emerse due discrepanze:

1. **FORCED_CONCLUSION ripetuto**: Il trigger scatta ad ogni turno umano durante la fase CONCLUSION, invece che una sola volta.
2. **Timer 30 min non cambia fase**: Quando scade il timer, viene emesso solo un messaggio ma la sessione non passa in CONCLUSION.

---

## 2. Problema 1: FORCED_CONCLUSION scatta più volte

### Comportamento attuale

```python
# triggers.py:127-143
def _should_force_conclusion(...) -> bool:
    if session_phase != "CONCLUSION":
        return False
    return True  # Sempre True se in CONCLUSION
```

Ogni turno umano in fase CONCLUSION ri-triggera `FORCED_CONCLUSION`, causando potenzialmente più chiamate LLM per la conclusione.

### Comportamento desiderato

`FORCED_CONCLUSION` deve scattare **una sola volta**, al primo turno umano dopo l'ingresso in fase CONCLUSION.

### Soluzione

Aggiungere un flag `forced_conclusion_done: bool` a `ModerationState` che viene settato a `True` dopo il primo intervento di conclusione.

---

## 3. Problema 2: Timer 30 min non cambia la fase della sessione

### Comportamento attuale

```python
# triggers.py:268-272
if (not state.timer_30_notified) and elapsed >= TIMER_30_THRESHOLD:
    messages.append("Il tempo della discussione è terminato...")
    state.timer_30_notified = True
```

Il messaggio viene emesso ma la fase della sessione resta ACTIVE.

### Comportamento desiderato

Quando il timer 30 min scade:
1. Se qualcuno sta parlando → aspetta che finisca il turno
2. Appena il turno finisce → emetti messaggio + cambia fase a CONCLUSION

### Soluzione

1. Nel trigger post-turno (`evaluate_triggers_on_human_turn_end`), controllare se il timer 30 min è scaduto
2. Se scaduto, aggiungere il messaggio ai `static_messages_to_speak` e segnalare il cambio fase
3. Il segnale viene propagato tramite un nuovo campo `should_transition_to_conclusion` in `FullModerationDecision`
4. Il consumer WebSocket (o chi chiama l'orchestrator) effettua il cambio di stato nel DB

---

## 4. Modifiche per file

### 4.1 `apps/moderation/state.py`

**Aggiungere campo a `ModerationState`:**

```python
@dataclass
class ModerationState:
    summary: str
    human_turns_since_last_summary: int
    ai_interventions_count: int
    last_ai_intervention_at: Optional[datetime]
    forced_conclusion_done: bool  # NUOVO

    @classmethod
    def initial(cls) -> "ModerationState":
        return cls(
            summary=DEFAULT_SUMMARY,
            human_turns_since_last_summary=0,
            ai_interventions_count=0,
            last_ai_intervention_at=None,
            forced_conclusion_done=False,  # NUOVO
        )
```

**Aggiornare `load_moderation_state` e `save_moderation_state`** per includere il nuovo campo.

---

### 4.2 `apps/moderation/triggers.py`

**Modificare `_should_force_conclusion`:**

```python
def _should_force_conclusion(
    *,
    session_id: int | str,
    session_phase: str,
    moderation_state: ModerationState,  # NUOVO parametro
) -> bool:
    if session_phase != "CONCLUSION":
        return False

    # Scatta solo se non è già stata fatta
    if moderation_state.forced_conclusion_done:
        return False

    return True
```

**Aggiornare la chiamata in `evaluate_triggers_on_human_turn_end`:**

```python
if _should_force_conclusion(
    session_id=session_id,
    session_phase=session_phase,
    moderation_state=moderation_state,  # NUOVO
):
    hard_action = HardModerationAction.FORCED_CONCLUSION
```

**Aggiungere campo a `TriggerEvaluationResult`:**

```python
@dataclass
class TriggerEvaluationResult:
    hard_action: HardModerationAction
    static_messages_to_speak: List[str]
    should_transition_to_conclusion: bool  # NUOVO
```

**Aggiungere controllo timer 30 min in `evaluate_triggers_on_human_turn_end`:**

```python
def evaluate_triggers_on_human_turn_end(...) -> TriggerEvaluationResult:
    hard_action = HardModerationAction.NONE
    static_messages: list[str] = []
    should_transition_to_conclusion = False  # NUOVO

    # ... trigger esistenti ...

    # NUOVO: Controllo timer 30 min (solo in fase ACTIVE)
    if session_phase == "ACTIVE":
        timers_state = load_timers_state(session_id)
        if timers_state.session_started_at is not None:
            elapsed = datetime.utcnow() - timers_state.session_started_at
            if elapsed >= TIMER_30_THRESHOLD:
                if not timers_state.timer_30_notified:
                    static_messages.append(
                        "Il tempo della discussione è terminato. "
                        "Potete avviarvi verso la conclusione."
                    )
                    timers_state.timer_30_notified = True
                    save_timers_state(session_id, timers_state)

                # Segnala il cambio di fase
                should_transition_to_conclusion = True

    return TriggerEvaluationResult(
        hard_action=hard_action,
        static_messages_to_speak=static_messages,
        should_transition_to_conclusion=should_transition_to_conclusion,  # NUOVO
    )
```

---

### 4.3 `apps/moderation/service.py`

**Settare il flag `forced_conclusion_done` dopo l'intervento:**

```python
# In handle_human_turn_ended, dopo che ai_should_speak è True per forced_conclusion:
if mode == "forced_conclusion" and ai_should_speak:
    state.forced_conclusion_done = True
```

---

### 4.4 `apps/moderation/orchestrator.py`

**Aggiornare `FullModerationDecision`:**

```python
@dataclass
class FullModerationDecision:
    static_messages_to_speak: List[str]
    ai_should_speak: bool
    ai_message: Optional[str]
    hard_action: HardModerationAction
    should_transition_to_conclusion: bool  # NUOVO
```

**Propagare il campo in `handle_human_turn_end`:**

```python
return FullModerationDecision(
    static_messages_to_speak=trigger_result.static_messages_to_speak,
    ai_should_speak=moderation_result.ai_should_speak,
    ai_message=moderation_result.ai_message,
    hard_action=trigger_result.hard_action,
    should_transition_to_conclusion=trigger_result.should_transition_to_conclusion,  # NUOVO
)
```

---

### 4.5 `apps/turns/ws_consumer.py`

**Gestire il cambio fase nel consumer:**

Nel metodo che chiama `ModerationOrchestrator.handle_human_turn_end()`, dopo aver ricevuto la `FullModerationDecision`:

```python
if decision.should_transition_to_conclusion:
    await self._transition_session_to_conclusion(session_id)

# ...

async def _transition_session_to_conclusion(self, session_id: str) -> None:
    """
    Cambia la fase della sessione da ACTIVE a CONCLUSION.
    """
    from apps.sessions.models import Session, SessionState
    from django.utils import timezone
    from asgiref.sync import sync_to_async

    @sync_to_async
    def do_transition():
        try:
            session = Session.objects.get(pk=session_id)
            if session.state == SessionState.ACTIVE:
                session.state = SessionState.CONCLUSION
                session.conclusion_at = timezone.now()
                session.save(update_fields=["state", "conclusion_at"])
                return True
        except Session.DoesNotExist:
            pass
        return False

    changed = await do_transition()

    if changed:
        # Broadcast del cambio di stato
        await self._broadcast_session_state_changed(session_id)
```

---

## 5. Flusso aggiornato

### 5.1 Timer 30 min scade durante un turno umano

```
1. Timer 30 min scade
2. Ping arriva → qualcuno sta parlando → niente (come prima)
3. Utente finisce di parlare
4. evaluate_triggers_on_human_turn_end() viene chiamato:
   - Rileva che timer 30 min è scaduto
   - Aggiunge messaggio "Il tempo della discussione è terminato..."
   - Setta should_transition_to_conclusion = True
5. Orchestrator restituisce FullModerationDecision con should_transition_to_conclusion=True
6. Consumer:
   - Pronuncia i messaggi statici (incluso quello del timer)
   - Chiama _transition_session_to_conclusion()
   - Broadcast del nuovo stato sessione
```

### 5.2 FORCED_CONCLUSION (primo turno in CONCLUSION)

```
1. Sessione entra in CONCLUSION (via ready_to_conclude o timer 30 min)
2. Primo turno umano termina
3. evaluate_triggers_on_human_turn_end():
   - session_phase == "CONCLUSION"
   - moderation_state.forced_conclusion_done == False
   - → hard_action = FORCED_CONCLUSION
4. ModerationService chiama LLM in modalità forced_conclusion
5. LLM genera riassunto finale
6. state.forced_conclusion_done = True (salvato)
7. Turni successivi: forced_conclusion_done == True → niente FORCED_CONCLUSION
```

---

## 6. Test da aggiungere

### 6.1 Test per FORCED_CONCLUSION una sola volta

```python
def test_forced_conclusion_fires_only_once():
    # Setup: sessione in CONCLUSION, stato iniziale
    # Primo turno → FORCED_CONCLUSION scatta
    # Secondo turno → FORCED_CONCLUSION NON scatta
```

### 6.2 Test per timer 30 min → CONCLUSION

```python
def test_timer_30_triggers_conclusion_transition():
    # Setup: sessione ACTIVE, timer_started_at = 31 minuti fa
    # Fine turno umano → should_transition_to_conclusion == True
    # Verifica messaggio presente
```

### 6.3 Test per timer 30 min durante turno

```python
def test_timer_30_waits_for_turn_end():
    # Setup: sessione ACTIVE, qualcuno sta parlando, timer scaduto
    # Ping → nessun cambio
    # Fine turno → cambio a CONCLUSION
```

---

## 7. Considerazioni

### 7.1 Backward compatibility

- Il nuovo campo `forced_conclusion_done` ha default `False`, quindi le sessioni esistenti continueranno a funzionare
- Il campo `should_transition_to_conclusion` ha default `False`, quindi i consumer non aggiornati non avranno problemi

### 7.2 Edge cases

- **Sessione già in CONCLUSION quando timer scade**: `should_transition_to_conclusion` non dovrebbe attivarsi (controllo `session_phase == "ACTIVE"`)
- **Timer 30 min + tutti pronti simultaneamente**: La transizione avviene una sola volta (il primo che scatta vince)

---

## 8. Checklist implementazione

- [ ] Aggiungere `forced_conclusion_done` a `ModerationState` in `state.py`
- [ ] Aggiornare `load_moderation_state` e `save_moderation_state`
- [ ] Modificare `_should_force_conclusion` per controllare il flag
- [ ] Aggiungere `should_transition_to_conclusion` a `TriggerEvaluationResult`
- [ ] Aggiungere controllo timer 30 min in `evaluate_triggers_on_human_turn_end`
- [ ] Settare `forced_conclusion_done = True` in `ModerationService` dopo forced_conclusion
- [ ] Aggiungere `should_transition_to_conclusion` a `FullModerationDecision`
- [ ] Propagare il campo in `ModerationOrchestrator.handle_human_turn_end`
- [ ] Implementare `_transition_session_to_conclusion` nel consumer
- [ ] Gestire il cambio fase nel flusso post-turno del consumer
- [ ] Scrivere test unitari
- [ ] Test end-to-end manuale
