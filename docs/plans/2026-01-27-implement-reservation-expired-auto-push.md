# Implementazione Push Automatico RESERVATION_EXPIRED

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implementare l'invio automatico dell'evento `RESERVATION_EXPIRED` via WebSocket dopo 8 secondi dalla scadenza della finestra di prenotazione, senza dipendere da azioni dei client.

**Architecture:** Quando un utente termina di parlare e c'è una reservation attiva, si avvia un task asyncio che aspetta 8 secondi. Se la reservation non è stata consumata (l'utente prenotato non ha chiamato `request_speak`), il task invia `RESERVATION_EXPIRED` a tutti i client via WebSocket.

**Tech Stack:** Python/Django, asyncio, Django Channels WebSocket, Redis cache

---

## Riferimento

Design document: `docs/plans/2026-01-27-reservation-expiration-push-design.md`

---

### Task 1: Aggiungere metodo `expire_reservation_if_pending` in TurnManager

**Files:**
- Modify: `apps/turns/services.py` (dopo il metodo `_expire_reservation_if_needed`, circa riga 471)

**Step 1: Leggere il file services.py per individuare la posizione corretta**

Verificare la struttura del file e trovare dove inserire il nuovo metodo.

**Step 2: Aggiungere il nuovo metodo**

Inserire dopo `_expire_reservation_if_needed()`:

```python
@classmethod
def expire_reservation_if_pending(
    cls,
    session_id: str,
    expected_user_id: int
) -> Optional[TurnEvent]:
    """
    Chiamato dal timer asincrono dopo 8 secondi.
    Expira la reservation SOLO se è ancora attiva per lo stesso utente.

    Restituisce l'evento RESERVATION_EXPIRED o None se già consumata.
    """
    state = cls._load_state(session_id)

    # Reservation già consumata o assegnata ad altro utente?
    if state.reservation_user_id != expected_user_id:
        return None

    # Expira la reservation
    state.reservation_user_id = None
    state.reservation_expires_at = None
    state.version += 1

    cls._save_state(session_id, state)

    return TurnEvent(
        type="RESERVATION_EXPIRED",
        payload={
            "user_id": expected_user_id,
            "expired_at": timezone.now().isoformat(),
        },
    )
```

**Step 3: Verificare sintassi**

Run: `python -m py_compile apps/turns/services.py`
Expected: Nessun output (compilazione OK)

**Step 4: Commit**

```bash
git add apps/turns/services.py
git commit -m "feat(turns): add expire_reservation_if_pending method

New TurnManager method for async timer to expire reservations after
the 8-second priority window. Only expires if the reservation is still
active for the expected user.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 2: Aggiungere metodo `_schedule_reservation_expiration` nel consumer

**Files:**
- Modify: `apps/turns/ws_consumer.py` (nella sezione UTILITIES, dopo `_broadcast_events`)

**Step 1: Aggiungere import asyncio se non presente**

Verificare che `import asyncio` sia presente (dovrebbe già esserci alla riga 3).

**Step 2: Aggiungere import della costante PRIORITY_WINDOW_SECONDS**

All'inizio del file, dopo gli altri import da apps.turns:

```python
from apps.turns.services import TurnManager, PRIORITY_WINDOW_SECONDS
```

**Step 3: Aggiungere il metodo `_schedule_reservation_expiration`**

Inserire nella sezione UTILITIES (dopo `_broadcast_events`, circa riga 627):

```python
async def _schedule_reservation_expiration(
    self,
    session_id: str,
    user_id: int
):
    """
    Task asincrono che aspetta la scadenza della finestra di priorità
    e invia RESERVATION_EXPIRED se la reservation è ancora attiva.
    """
    await asyncio.sleep(PRIORITY_WINDOW_SECONDS)

    # Verifica e expira (sync method wrapped)
    event = await database_sync_to_async(
        TurnManager.expire_reservation_if_pending
    )(session_id, user_id)

    if event:
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "turns.event",
                "event_type": event.type,
                "payload": event.payload,
            },
        )
```

**Step 4: Verificare sintassi**

Run: `python -m py_compile apps/turns/ws_consumer.py`
Expected: Nessun output (compilazione OK)

**Step 5: Commit**

```bash
git add apps/turns/ws_consumer.py
git commit -m "feat(ws): add _schedule_reservation_expiration async task

Async task that waits for the priority window to expire and broadcasts
RESERVATION_EXPIRED if the reservation wasn't consumed.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 3: Modificare `_handle_end_speak` per avviare il timer

**Files:**
- Modify: `apps/turns/ws_consumer.py:299-300` (dopo il broadcast degli eventi in `_handle_end_speak`)

**Step 1: Individuare la posizione corretta**

Cercare in `_handle_end_speak()` la riga:
```python
# Broadcast degli eventi generati dalla chiusura
await self._broadcast_events(result.events)
```

**Step 2: Aggiungere la logica per avviare il timer**

Subito dopo il broadcast, aggiungere:

```python
# Broadcast degli eventi generati dalla chiusura
await self._broadcast_events(result.events)

# Se c'è una reservation window attiva, schedula il timer per l'expiration
for event in result.events:
    if event.type == "RESERVATION_WINDOW_STARTED":
        asyncio.create_task(
            self._schedule_reservation_expiration(
                session_id=self.session_id,
                user_id=event.payload["user_id"],
            )
        )
```

**Step 3: Verificare sintassi**

Run: `python -m py_compile apps/turns/ws_consumer.py`
Expected: Nessun output (compilazione OK)

**Step 4: Commit**

```bash
git add apps/turns/ws_consumer.py
git commit -m "feat(ws): start expiration timer when reservation window opens

When end_speak triggers RESERVATION_WINDOW_STARTED, an async task is
created to automatically expire the reservation after 8 seconds if
not consumed.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 4: Scrivere test per il push automatico

**Files:**
- Modify: `apps/turns/tests.py`

**Step 1: Leggere i test esistenti**

Verificare la struttura dei test esistenti per capire come sono organizzati.

**Step 2: Aggiungere test per expiration automatica**

```python
def test_reservation_expired_event_sent_after_timeout(self):
    """
    Verifica che expire_reservation_if_pending() generi l'evento
    RESERVATION_EXPIRED se la reservation è ancora attiva.
    """
    from apps.turns.services import TurnManager, TurnState, TURN_STATE_IDLE

    session_id = "test-session-expire"
    user_id = 42

    # Setup: crea stato con reservation attiva
    state = TurnState(
        state=TURN_STATE_IDLE,
        reservation_user_id=user_id,
        reservation_expires_at=None,  # già scaduta concettualmente
    )
    TurnManager._save_state(session_id, state)

    # Act: chiama il metodo di expiration
    event = TurnManager.expire_reservation_if_pending(session_id, user_id)

    # Assert: evento generato
    self.assertIsNotNone(event)
    self.assertEqual(event.type, "RESERVATION_EXPIRED")
    self.assertEqual(event.payload["user_id"], user_id)

    # Assert: stato pulito
    new_state = TurnManager._load_state(session_id)
    self.assertIsNone(new_state.reservation_user_id)


def test_reservation_used_no_expired_event(self):
    """
    Verifica che expire_reservation_if_pending() NON generi evento
    se la reservation è già stata consumata (user_id diverso).
    """
    from apps.turns.services import TurnManager, TurnState, TURN_STATE_IDLE

    session_id = "test-session-no-expire"
    original_user_id = 42
    different_user_id = 99

    # Setup: crea stato con reservation per un utente diverso
    state = TurnState(
        state=TURN_STATE_IDLE,
        reservation_user_id=different_user_id,
    )
    TurnManager._save_state(session_id, state)

    # Act: chiama expiration per l'utente originale
    event = TurnManager.expire_reservation_if_pending(session_id, original_user_id)

    # Assert: nessun evento (reservation non corrisponde)
    self.assertIsNone(event)

    # Assert: stato invariato
    new_state = TurnManager._load_state(session_id)
    self.assertEqual(new_state.reservation_user_id, different_user_id)
```

**Step 3: Eseguire i test**

Run: `docker compose run --rm web python manage.py test apps.turns`
Expected: Tutti i test passano

**Step 4: Commit**

```bash
git add apps/turns/tests.py
git commit -m "test(turns): add tests for automatic reservation expiration

Tests verify that expire_reservation_if_pending correctly generates
RESERVATION_EXPIRED event when reservation is active, and returns None
when reservation was already consumed.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 5: Aggiornare la specifica (opzionale)

**Files:**
- Modify: `docs/specs/turns_v1_spec.md`

**Step 1: Verificare se serve aggiornamento**

Cercare la sezione che descrive `turn.reservation_expired`.

**Step 2: Aggiungere nota sul comportamento automatico**

```markdown
> **Nota:** L'evento `turn.reservation_expired` viene ora inviato automaticamente
> dal server dopo 8 secondi dalla scadenza della finestra di prenotazione,
> senza necessità di azioni da parte dei client.
```

**Step 3: Commit**

```bash
git add docs/specs/turns_v1_spec.md
git commit -m "docs(specs): document automatic reservation_expired push

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Riepilogo Modifiche

| File | Modifica |
|------|----------|
| `apps/turns/services.py` | Nuovo metodo `expire_reservation_if_pending()` |
| `apps/turns/ws_consumer.py` | Import `PRIORITY_WINDOW_SECONDS` |
| `apps/turns/ws_consumer.py` | Nuovo metodo `_schedule_reservation_expiration()` |
| `apps/turns/ws_consumer.py` | Modifica `_handle_end_speak()` per avviare timer |
| `apps/turns/tests.py` | Due nuovi test |
| `docs/specs/turns_v1_spec.md` | Nota sul comportamento automatico |

---

## Flusso Temporale Dopo Implementazione

```
T=0s   Utente A termina di parlare (end_speak)
       ├── Broadcast: RESERVATION_WINDOW_STARTED {user_id: B, expires_at: T+8s}
       └── Avvia task: _schedule_reservation_expiration(session_id, user_B)

T=0-8s Possibili scenari:
       ├── Utente B chiama request_speak → reservation consumata, reservation_user_id = None
       └── Nessuna azione → task continua in background

T=8s   Task si sveglia:
       ├── Chiama TurnManager.expire_reservation_if_pending(session_id, user_B)
       ├── Se reservation_user_id == user_B → Broadcast: RESERVATION_EXPIRED {user_id: B}
       └── Se reservation_user_id != user_B → Niente (già consumata/cambiata)
```

---

## Edge Cases Gestiti

| Scenario | Comportamento |
|----------|---------------|
| Utente usa la reservation entro 8s | `reservation_user_id` diventa `None` alla `request_speak`, timer non fa nulla |
| Utente si disconnette durante la finestra | Task continua, invia `RESERVATION_EXPIRED` agli altri client |
| Server si riavvia durante i 8s | Task perso, check lazy esistente gestisce alla prossima azione |
| Nuova reservation per altro utente | `reservation_user_id` cambiato, timer non fa nulla (user_id non corrisponde) |
