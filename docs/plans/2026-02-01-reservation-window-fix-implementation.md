# Fix Finestra di Prenotazione - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the reservation window timing bug where the window opens prematurely when the moderator has multiple messages to speak, causing early expiration of reservations.

**Architecture:** Remove window-opening logic from `ai_end()` since the window should only be opened once at the very end by `start_reservation_window()` in the `finally` block. Also add checks for active reservation windows in trigger handlers to queue messages instead of executing them during an active window.

**Tech Stack:** Django, Python, Redis cache for turn state

---

## Task 1: Write Test for ai_end Not Opening Window

**Files:**
- Modify: `apps/turns/tests/test_services.py`

**Step 1: Write the failing test**

Add a test that verifies `ai_end()` does not emit `RESERVATION_WINDOW_STARTED`:

```python
def test_ai_end_does_not_open_reservation_window(self):
    """
    Verifica che ai_end() NON apra la finestra di prenotazione.
    La finestra viene aperta solo da start_reservation_window().
    """
    # user1 parla
    result = TurnManager.request_speak(self.session_id, self.user1)
    self.assertTrue(result.success)

    # user2 si prenota
    result = TurnManager.request_reserve(self.session_id, self.user2)
    self.assertTrue(result.success)

    # user1 termina
    result = TurnManager.end_speak(self.session_id, self.user1)
    self.assertTrue(result.success)

    # AI parla
    result = TurnManager.ai_start(self.session_id)
    self.assertTrue(result.success)

    # AI termina - NON deve aprire la finestra
    result = TurnManager.ai_end(self.session_id)
    self.assertTrue(result.success)

    event_types = [e.type for e in result.events]
    self.assertIn("AI_ENDED", event_types)
    # La finestra NON deve essere aperta da ai_end
    self.assertNotIn("RESERVATION_WINDOW_STARTED", event_types)

    # La prenotazione esiste ma non ha ancora una scadenza
    self.assertEqual(result.state.reservation_user_id, self.user2.id)
    self.assertIsNone(result.state.reservation_expires_at)

    # Solo start_reservation_window apre la finestra
    window_event = TurnManager.start_reservation_window(self.session_id)
    self.assertIsNotNone(window_event)
    self.assertEqual(window_event.type, "RESERVATION_WINDOW_STARTED")
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.turns.tests.test_services.TurnPriorityWindowTest.test_ai_end_does_not_open_reservation_window -v 2`

Expected: FAIL - the test should fail because currently `ai_end()` opens the window.

**Step 3: Commit test**

```bash
git add apps/turns/tests/test_services.py
git commit -m "test: add test for ai_end not opening reservation window"
```

---

## Task 2: Remove Window Opening from ai_end()

**Files:**
- Modify: `apps/turns/services.py:437-451`

**Step 1: Remove the window-opening logic from ai_end()**

In `apps/turns/services.py`, remove lines 437-451 (the block that opens the reservation window):

Before (lines 437-451):
```python
        # Se c'era una prenotazione "congelata", ora si apre la finestra di priorità
        if state.reservation_user_id is not None:
            now = timezone.now()
            state.reservation_expires_at = now + timedelta(seconds=PRIORITY_WINDOW_SECONDS)
            state.version += 1

            reservation_started = TurnEvent(
                type="RESERVATION_WINDOW_STARTED",
                payload={
                    "user_id": state.reservation_user_id,
                    "expires_at": state.reservation_expires_at.isoformat(),
                    "window_seconds": PRIORITY_WINDOW_SECONDS,
                },
            )
            events.append(reservation_started)
```

After:
```python
        # NOTA: La finestra di prenotazione NON viene aperta qui.
        # Viene aperta solo da start_reservation_window() nel finally di _handle_end_speak,
        # DOPO che tutti i messaggi del moderatore sono stati pronunciati.
```

**Step 2: Run the test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.turns.tests.test_services.TurnPriorityWindowTest.test_ai_end_does_not_open_reservation_window -v 2`

Expected: PASS

**Step 3: Commit**

```bash
git add apps/turns/services.py
git commit -m "fix(turns): remove reservation window opening from ai_end"
```

---

## Task 3: Update _execute_static_messages to Check Window

**Files:**
- Modify: `apps/turns/ws_consumer.py:1165`

**Step 1: Update the condition to also check reservation_expires_at**

In `apps/turns/ws_consumer.py`, in `_execute_static_messages()`, update line 1165:

Before:
```python
                if state and state.state != "IDLE":
```

After:
```python
                if state and (state.state != "IDLE" or state.reservation_expires_at is not None):
```

**Step 2: Run existing tests to verify no regressions**

Run: `docker compose run --rm web python manage.py test apps.turns.tests -v 2`

Expected: All tests pass

**Step 3: Commit**

```bash
git add apps/turns/ws_consumer.py
git commit -m "fix(turns): queue static messages during active reservation window"
```

---

## Task 4: Update _handle_ping to Check Window

**Files:**
- Modify: `apps/turns/ws_consumer.py:717-720`

**Step 1: Update the TTS execution logic to check for reservation window**

In `apps/turns/ws_consumer.py`, in `_handle_ping()`, update lines 717-720:

Before:
```python
        for msg in trig_result.static_messages_to_speak:
            if msg.use_tts:
                # Messaggio con TTS - esegui come turno AI completo
                await self._execute_tts_message(msg.text)
```

After:
```python
        from apps.turns.services import TurnManager
        from apps.moderation.pending_messages import enqueue_message

        for msg in trig_result.static_messages_to_speak:
            if msg.use_tts:
                # Verifica se c'è qualcuno che parla o una finestra di prenotazione attiva
                state = TurnManager.get_state_only(self.session_id)
                if state and (state.state != "IDLE" or state.reservation_expires_at is not None):
                    # Accoda il messaggio
                    enqueue_message(self.session_id, msg.text, msg.trigger_type or "TRIGGER")
                else:
                    # Messaggio con TTS - esegui come turno AI completo
                    await self._execute_tts_message(msg.text)
```

**Step 2: Run existing tests to verify no regressions**

Run: `docker compose run --rm web python manage.py test apps.turns.tests -v 2`

Expected: All tests pass

**Step 3: Commit**

```bash
git add apps/turns/ws_consumer.py
git commit -m "fix(turns): queue ping TTS messages during active reservation window"
```

---

## Task 5: Update Outdated Comments in services.py

**Files:**
- Modify: `apps/turns/services.py:290`, `apps/turns/services.py:568`

**Step 1: Update comment at line 290**

Before:
```python
        # NOTA: Se c'è una prenotazione, NON apriamo subito la finestra di priorità.
        # La finestra verrà aperta DOPO la fase di moderazione (in ai_end se l'AI parla,
        # oppure manualmente se l'AI non parla). Questo evita che la finestra scada
        # mentre il moderatore sta parlando.
```

After:
```python
        # NOTA: Se c'è una prenotazione, NON apriamo subito la finestra di priorità.
        # La finestra verrà aperta SOLO da start_reservation_window() nel finally di
        # _handle_end_speak, DOPO che tutti i messaggi del moderatore sono stati
        # pronunciati. Questo evita che la finestra scada prematuramente.
```

**Step 2: Update comment at line 568**

Before:
```python
        Da chiamare DOPO la fase di moderazione se l'AI non ha parlato.
        Se l'AI ha parlato, la finestra viene aperta da ai_end().
```

After:
```python
        Da chiamare DOPO la fase di moderazione, nel finally di _handle_end_speak.
        Questa è l'UNICA funzione che apre la finestra di priorità.
```

**Step 3: Commit**

```bash
git add apps/turns/services.py
git commit -m "docs: update comments about reservation window opening"
```

---

## Task 6: Update Outdated Comments in ws_consumer.py

**Files:**
- Modify: `apps/turns/ws_consumer.py:489`, `apps/turns/ws_consumer.py:1258`

**Step 1: Update comment at line 489**

Before:
```python
                    # 6.7 Se ai_end ha aperto una finestra di prenotazione, schedula il timer
```

After:
```python
                    # 6.7 (Legacy) ai_end non apre più la finestra, ma lasciamo il check per sicurezza
```

**Step 2: Update comment at line 1258**

Before:
```python
            # Se ai_end ha aperto una finestra di prenotazione, schedula il timer
```

After:
```python
            # (Legacy) ai_end non apre più la finestra, ma lasciamo il check per sicurezza
```

**Step 3: Commit**

```bash
git add apps/turns/ws_consumer.py
git commit -m "docs: update comments about ai_end and reservation window"
```

---

## Task 7: Run Full Test Suite

**Files:**
- None (verification only)

**Step 1: Run all tests**

Run: `docker compose run --rm web python manage.py test -v 2`

Expected: All tests pass

**Step 2: Document results**

If tests fail, investigate and fix before proceeding.

---

## Task 8: Final Commit and Documentation

**Files:**
- Modify: `docs/documentazione_moderazione.md` (if needed)

**Step 1: Update moderation documentation if applicable**

Check if `docs/documentazione_moderazione.md` mentions the reservation window timing and update if needed.

**Step 2: Final verification**

Run: `docker compose run --rm web python manage.py test apps.turns.tests -v 2`

Expected: All tests pass

---

## Implementation Checklist

- [x] Task 1: Write test for ai_end not opening window
- [x] Task 2: Remove window opening from ai_end()
- [x] Task 3: Update _execute_static_messages to check window
- [x] Task 4: Update _handle_ping to check window
- [x] Task 5: Update outdated comments in services.py
- [x] Task 6: Update outdated comments in ws_consumer.py
- [x] Task 7: Run full test suite
- [x] Task 8: Final commit and documentation
