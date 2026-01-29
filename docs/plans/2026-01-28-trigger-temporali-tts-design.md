# Design: Trigger Temporali con TTS Backend-Driven

**Data:** 2026-01-28
**Stato:** Da implementare

## Obiettivo

Rendere i trigger temporali (NO_PUSH, TIMER_30, ecc.) affidabili e testabili:
1. **Backend-driven**: rilevamento autonomo senza dipendere dal ping frontend
2. **TTS audio**: i messaggi vengono riprodotti vocalmente via WebRTC
3. **Coda messaggi**: nessun messaggio viene perso se qualcuno sta parlando

## Trigger e Comportamento

| Trigger | Condizione | TTS | Messaggio |
|---------|-----------|-----|-----------|
| **NO_PUSH** | 15s di silenzio | ✅ Sì | "Se qualcuno vuole intervenire, può parlare ora o condividere una breve considerazione." |
| **TIMER_25** | 25 min dall'inizio | ❌ No (solo testo) | "Mancano circa cinque minuti alla fine della discussione." |
| **TIMER_30** | 30 min dall'inizio | ✅ Sì | "Il tempo della discussione è terminato. Potete avviarvi verso la conclusione." |
| **UTENTE_INATTIVO** | 10 min senza parlare | ✅ Sì | "{display_name}, se vuoi condividere un'idea, questo è un buon momento per intervenire." |
| **PRENOTAZIONE** | Utente aveva prenotato | ❌ No (solo testo) | "Ora la parola va a {reserved_speaker_name}, che aveva prenotato." |
| **PRONTI_CONCLUDERE** | N utenti pronti | ✅ Sì | "{ready_count} partecipanti su {total_count} sono pronti a concludere." |

## Architettura

### 1. Background Task Asyncio

Loop che gira ogni 5 secondi per valutare i trigger temporali, indipendente dal frontend.

**Lifecycle:**
- **Start**: quando il primo client si connette a una sessione ACTIVE
- **Stop**: quando l'ultimo client si disconnette

```python
class TurnsConsumer(AsyncJsonWebsocketConsumer):
    _trigger_tasks: ClassVar[Dict[str, asyncio.Task]] = {}
    _trigger_tasks_lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    async def _maybe_start_trigger_task(self):
        """Avvia il task se sessione ACTIVE e non già running."""
        async with self._trigger_tasks_lock:
            if self.session_id in self._trigger_tasks:
                return
            if self.session.status != "ACTIVE":
                return
            task = asyncio.create_task(self._trigger_loop(self.session_id))
            self._trigger_tasks[self.session_id] = task

    async def _trigger_loop(self, session_id: str):
        """Loop che ogni 5s valuta trigger temporali."""
        while True:
            await asyncio.sleep(5)
            await self._evaluate_and_execute_triggers(session_id)
```

### 2. Coda Messaggi Pendenti (Redis)

I messaggi TTS che non possono essere eseguiti subito (perché qualcuno sta parlando) vengono accodati e riprodotti appena il turno torna IDLE.

**Chiave Redis:** `moderation:pending_messages:{session_id}`

```python
@dataclass
class PendingMessage:
    text: str
    trigger_type: str
    created_at: datetime
```

**Operazioni:**
- `enqueue_message(session_id, text, trigger_type)` - Aggiunge alla coda
- `dequeue_all_messages(session_id) -> List[PendingMessage]` - Svuota e ritorna tutti
- `has_pending_messages(session_id) -> bool` - Check rapido

**Nota:** Solo i messaggi TTS vanno in coda. I messaggi solo testo vengono inviati immediatamente via WebSocket.

### 3. Esecuzione Messaggi

**Regola fondamentale:**
- Messaggi **solo testo** → invio immediato via WebSocket, nessun turno AI
- Messaggi **TTS** → richiedono turno AI, vanno in coda se stato non IDLE

**Turno unico per più messaggi:**
Se ci sono più messaggi TTS pendenti, vengono eseguiti tutti in un unico turno AI per non incrementare inutilmente il conteggio interventi moderatore.

```
Coda: [msg1, msg2]
IDLE → AI_SPEAKING → (TTS msg1) → (TTS msg2) → IDLE
```

### 4. Punti di Svuotamento Coda

```
┌─────────────────────────────────────────────────────────────┐
│ 1. DOPO human_end_speak                                     │
│    └─ Utente finisce di parlare → IDLE → svuota coda       │
├─────────────────────────────────────────────────────────────┤
│ 2. NEL background task (ogni 5s)                            │
│    └─ Se IDLE e coda non vuota → svuota coda               │
├─────────────────────────────────────────────────────────────┤
│ 3. DOPO ai_end (intervento LLM)                             │
│    └─ AI finisce intervento LLM → IDLE → svuota coda       │
└─────────────────────────────────────────────────────────────┘
```

### 5. Flusso in `_handle_end_speak`

```python
async def _handle_end_speak(self, payload):
    # 1. Termina turno umano
    result = TurnManager.human_end(...)

    # 2. Svuota coda messaggi TTS pendenti
    await self._flush_pending_tts_messages()

    # 3. Valuta trigger post-turno
    decision = await ModerationOrchestrator.handle_human_turn_end(...)

    # 4. Esegui messaggi statici nuovi
    await self._execute_static_messages(decision.static_messages_to_speak)

    # 5. Eventuale intervento LLM con TTS
    if decision.ai_should_speak and decision.ai_message:
        await self._execute_llm_response(decision.ai_message)
```

## File da Modificare

| File | Modifiche |
|------|-----------|
| `apps/moderation/pending_messages.py` | **NUOVO** - Gestione coda messaggi pendenti (Redis) |
| `apps/moderation/triggers.py` | Aggiungere flag `use_tts` per ogni tipo di messaggio statico |
| `apps/turns/ws_consumer.py` | Background task, svuotamento coda, TTS per messaggi statici |

### Dettaglio Modifiche

#### `apps/moderation/pending_messages.py` (nuovo)
- Dataclass `PendingMessage`
- `enqueue_message(session_id, text, trigger_type)`
- `dequeue_all_messages(session_id) -> List[PendingMessage]`
- `has_pending_messages(session_id) -> bool`

#### `apps/moderation/triggers.py`
- Creare dataclass `StaticMessage(text: str, use_tts: bool)`
- Modificare `TriggerResult.static_messages_to_speak` da `List[str]` a `List[StaticMessage]`
- Assegnare `use_tts=False` a TIMER_25 e PRENOTAZIONE
- Assegnare `use_tts=True` a NO_PUSH, TIMER_30, UTENTE_INATTIVO, PRONTI_CONCLUDERE

#### `apps/turns/ws_consumer.py`
- `_trigger_tasks: ClassVar[Dict[str, asyncio.Task]]` - dizionario task per sessione
- `_trigger_tasks_lock: ClassVar[asyncio.Lock]` - lock per accesso concorrente
- `_maybe_start_trigger_task()` - avvia task se necessario
- `_maybe_stop_trigger_task()` - ferma task se necessario
- `_trigger_loop(session_id)` - loop ogni 5s
- `_evaluate_and_execute_triggers(session_id)` - valuta e esegue/accoda
- `_flush_pending_tts_messages()` - svuota coda ed esegue
- `_execute_tts_messages(messages)` - esegue messaggi con TTS in unico turno AI
- Modificare `_handle_end_speak()` per integrare svuotamento coda
- Rimuovere logica ping-based per trigger temporali (opzionale, può rimanere come fallback)

## Flusso Completo

```
┌─────────────────────────────────────────────────────────────────┐
│                     BACKGROUND TASK (ogni 5s)                   │
├─────────────────────────────────────────────────────────────────┤
│ 1. evaluate_time_based_triggers()                               │
│    ├─ NO_PUSH scatta? → StaticMessage(text, use_tts=True)      │
│    ├─ TIMER_25 scatta? → StaticMessage(text, use_tts=False)    │
│    └─ ...                                                       │
│                                                                 │
│ 2. Per ogni messaggio:                                          │
│    ├─ use_tts=False → send_json() immediato                    │
│    └─ use_tts=True:                                            │
│        ├─ Stato IDLE? → _execute_tts_messages()                │
│        └─ Stato non IDLE? → enqueue_message()                  │
│                                                                 │
│ 3. Se IDLE e coda non vuota → _flush_pending_tts_messages()    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     _execute_tts_messages()                     │
├─────────────────────────────────────────────────────────────────┤
│ 1. TurnManager.ai_start() → AI_SPEAKING                         │
│ 2. Per ogni messaggio:                                          │
│    ├─ send_json(turns.ai_message) per UI/sottotitoli           │
│    └─ TTSService.synthesize_stream() → audio WebRTC            │
│ 3. TurnManager.ai_end() → IDLE                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Note di Testing

Per testare rapidamente il TTS con trigger temporali:
1. Avvia una sessione e portala in stato ACTIVE
2. Non premere "parla" per 15 secondi
3. Il trigger NO_PUSH dovrebbe scattare
4. Dovresti sentire l'audio del moderatore via WebRTC

Se vuoi testare più velocemente, puoi temporaneamente abbassare `NO_PUSH_THRESHOLD` in `apps/moderation/timers_state.py`.
