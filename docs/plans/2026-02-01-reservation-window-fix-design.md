# Fix Finestra di Prenotazione - Design

**Data**: 2026-02-01
**Stato**: In implementazione

## Problema

Quando il moderatore ha più messaggi da dire (es. messaggio LLM + trigger statici), la finestra di prenotazione si apre dopo il primo messaggio invece che dopo l'ultimo. Questo causa:

1. Il primo timer scade mentre il moderatore sta ancora parlando
2. L'utente prenotato perde la prenotazione prematuramente

### Timeline del bug

```
T0: Fine turno umano, User B è prenotato
T1: Primo ai_end (messaggio LLM)
    → reservation_expires_at = T1 + 8s
    → Schedula timer #1 (scade a T1+8s)
T2: Secondo ai_end (messaggio in coda)
    → reservation_expires_at = T2 + 8s
    → Schedula timer #2 (scade a T2+8s)

[il moderatore sta ancora parlando...]

T1+8s: Timer #1 scade!
    → expire_reservation_if_pending() controlla solo user_id
    → EXPIRA LA PRENOTAZIONE PREMATURAMENTE
```

## Soluzione

Due modifiche coordinate:

### Fix 1: `ai_end()` non apre più la finestra

Rimuovere da `ai_end()` la logica che apre la finestra di prenotazione. La finestra viene aperta **solo** da `start_reservation_window()` nel finally di `_handle_end_speak`.

**File**: `apps/turns/services.py`
**Righe da rimuovere**: 437-451 (blocco che imposta `reservation_expires_at` e genera `RESERVATION_WINDOW_STARTED`)

### Fix 2: I trigger temporali rispettano la finestra attiva

Aggiungere controllo `reservation_expires_at` per accodare i messaggi invece di eseguirli durante una finestra attiva.

**File**: `apps/turns/ws_consumer.py`
**Modifiche**:
1. `_handle_ping()`: verificare se c'è finestra attiva prima di eseguire TTS
2. `_execute_static_messages_with_tts()`: aggiungere controllo `reservation_expires_at`

## Dettagli Implementativi

### services.py - ai_end()

```python
# PRIMA (da rimuovere)
def ai_end(cls, session_id: str) -> TurnResult:
    ...
    # Se c'era una prenotazione "congelata", ora si apre la finestra di priorità
    if state.reservation_user_id is not None:
        now = timezone.now()
        state.reservation_expires_at = now + timedelta(seconds=PRIORITY_WINDOW_SECONDS)
        state.version += 1
        reservation_started = TurnEvent(
            type="RESERVATION_WINDOW_STARTED",
            ...
        )
        events.append(reservation_started)
    ...

# DOPO
def ai_end(cls, session_id: str) -> TurnResult:
    ...
    # La finestra di prenotazione viene aperta da start_reservation_window()
    # nel finally di _handle_end_speak, non qui.
    ...
```

### ws_consumer.py - _handle_ping()

```python
# PRIMA
for msg in trig_result.static_messages_to_speak:
    if msg.use_tts:
        await self._execute_tts_message(msg.text)

# DOPO
from apps.moderation.pending_messages import enqueue_message

for msg in trig_result.static_messages_to_speak:
    if msg.use_tts:
        state = TurnManager.get_state_only(self.session_id)
        # Accoda se qualcuno sta parlando O se c'è una finestra attiva
        if state and (state.state != "IDLE" or state.reservation_expires_at is not None):
            enqueue_message(self.session_id, msg.text, msg.trigger_type or "TRIGGER")
        else:
            await self._execute_tts_message(msg.text)
```

### ws_consumer.py - _execute_static_messages_with_tts()

```python
# PRIMA
if state and state.state != "IDLE":
    enqueue_message(...)

# DOPO
if state and (state.state != "IDLE" or state.reservation_expires_at is not None):
    enqueue_message(...)
```

## Aggiornamento Commenti

Aggiornare i commenti che dicono "la finestra viene aperta da ai_end":
- `services.py` linea 290, 568
- `ws_consumer.py` linea 354, 489, 536

## Test

1. Test esistenti devono continuare a passare
2. Verificare che con più messaggi TTS la finestra si apra una sola volta
3. Verificare che trigger temporali vengano accodati durante finestra attiva

## Checklist Implementazione

- [ ] Rimuovere apertura finestra da `ai_end()` in services.py
- [ ] Aggiornare `_handle_ping()` per controllare finestra attiva
- [ ] Aggiornare `_execute_static_messages_with_tts()` per controllare finestra attiva
- [ ] Aggiornare commenti obsoleti
- [ ] Eseguire test esistenti
- [ ] Test manuale del flusso completo
