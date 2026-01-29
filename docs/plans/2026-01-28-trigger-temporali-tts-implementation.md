# Trigger Temporali con TTS Backend-Driven - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rendere i trigger temporali (NO_PUSH, TIMER_30, ecc.) affidabili tramite background task backend-driven con TTS audio via WebRTC e coda messaggi pendenti.

**Architecture:** Background asyncio task nel TurnsConsumer che valuta trigger ogni 5s. I messaggi TTS vengono accodati in Redis se qualcuno sta parlando e riprodotti appena il turno torna IDLE. I messaggi solo testo vengono inviati immediatamente via WebSocket.

**Tech Stack:** Django/Daphne, asyncio, Redis (Django cache), Azure TTS, WebRTC audio hub

---

## Task 1: StaticMessage Dataclass

**Files:**
- Modify: `apps/moderation/triggers.py:1-36`
- Test: `apps/moderation/tests.py`

**Step 1: Write the failing test**

In `apps/moderation/tests.py`, aggiungere dopo la riga 21 (dopo gli import esistenti):

```python
from apps.moderation.triggers import StaticMessage
```

E aggiungere un nuovo test case alla fine del file:

```python
class StaticMessageTests(TestCase):
    def test_static_message_with_tts(self):
        """StaticMessage with use_tts=True."""
        msg = StaticMessage(text="Test message", use_tts=True)
        self.assertEqual(msg.text, "Test message")
        self.assertTrue(msg.use_tts)

    def test_static_message_without_tts(self):
        """StaticMessage with use_tts=False (text only)."""
        msg = StaticMessage(text="Timer warning", use_tts=False)
        self.assertEqual(msg.text, "Timer warning")
        self.assertFalse(msg.use_tts)
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.StaticMessageTests -v 2`
Expected: FAIL with "cannot import name 'StaticMessage'"

**Step 3: Write minimal implementation**

In `apps/moderation/triggers.py`, dopo la riga 3 (`from typing import List, Optional`), aggiungere:

```python
@dataclass
class StaticMessage:
    """Messaggio statico da pronunciare/mostrare."""
    text: str
    use_tts: bool = True  # True = TTS audio, False = solo testo WebSocket
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.StaticMessageTests -v 2`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add apps/moderation/triggers.py apps/moderation/tests.py
git commit -m "$(cat <<'EOF'
feat(moderation): add StaticMessage dataclass with use_tts flag

Introduces StaticMessage to distinguish between TTS messages
(audio via WebRTC) and text-only messages (WebSocket only).

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Update TriggerEvaluationResult to use List[StaticMessage]

**Files:**
- Modify: `apps/moderation/triggers.py:28-36`
- Test: `apps/moderation/tests.py`

**Step 1: Write the failing test**

In `apps/moderation/tests.py`, modificare `TriggerEvaluationResultTests` esistente:

```python
class TriggerEvaluationResultTests(TestCase):
    def test_trigger_result_has_should_transition_to_conclusion(self):
        """TriggerEvaluationResult should have should_transition_to_conclusion field."""
        result = TriggerEvaluationResult(
            hard_action=HardModerationAction.NONE,
            static_messages_to_speak=[],
            should_transition_to_conclusion=True,
        )
        self.assertTrue(result.should_transition_to_conclusion)

    def test_trigger_result_default_false(self):
        """should_transition_to_conclusion should default to False."""
        result = TriggerEvaluationResult(
            hard_action=HardModerationAction.NONE,
            static_messages_to_speak=[],
        )
        self.assertFalse(result.should_transition_to_conclusion)

    def test_trigger_result_static_messages_are_static_message_objects(self):
        """static_messages_to_speak should contain StaticMessage objects."""
        msg = StaticMessage(text="Test", use_tts=True)
        result = TriggerEvaluationResult(
            hard_action=HardModerationAction.NONE,
            static_messages_to_speak=[msg],
        )
        self.assertEqual(len(result.static_messages_to_speak), 1)
        self.assertIsInstance(result.static_messages_to_speak[0], StaticMessage)
        self.assertEqual(result.static_messages_to_speak[0].text, "Test")
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.TriggerEvaluationResultTests.test_trigger_result_static_messages_are_static_message_objects -v 2`
Expected: Test may pass with strings but type check will reveal issue

**Step 3: Write minimal implementation**

In `apps/moderation/triggers.py`, modificare la dataclass `TriggerEvaluationResult` (riga 28-36):

```python
@dataclass
class TriggerEvaluationResult:
    """
    Risultato della valutazione dei trigger di moderazione
    per una determinata sessione in una determinata finestra.
    """
    hard_action: HardModerationAction
    static_messages_to_speak: List[StaticMessage]
    should_transition_to_conclusion: bool = False  # segnala cambio fase a CONCLUSION
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.TriggerEvaluationResultTests -v 2`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add apps/moderation/triggers.py apps/moderation/tests.py
git commit -m "$(cat <<'EOF'
refactor(moderation): change static_messages_to_speak to List[StaticMessage]

Updates TriggerEvaluationResult to use typed StaticMessage objects
instead of plain strings, enabling TTS vs text-only distinction.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Update evaluate_triggers_on_human_turn_end to return StaticMessage objects

**Files:**
- Modify: `apps/moderation/triggers.py:39-103` e `177-202`
- Test: `apps/moderation/tests.py`

**Step 1: Write the failing test**

In `apps/moderation/tests.py`, aggiungere:

```python
class TriggerMessagesUseTTSTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('apps.moderation.triggers._get_next_reserved_speaker_name', return_value="Mario")
    @patch('apps.moderation.triggers._get_ready_to_conclude_status', return_value=(0, 3))
    def test_prenotazione_message_has_use_tts_false(self, mock_ready, mock_reserved):
        """PRENOTAZIONE message should have use_tts=False (text only)."""
        session_id = "test-session-tts-1"
        mod_state = ModerationState.initial()
        save_moderation_state(session_id, mod_state)

        result = evaluate_triggers_on_human_turn_end(
            session_id=session_id,
            user_id=1,
            session_phase="ACTIVE",
            moderation_state=mod_state,
        )

        prenotazione_msgs = [m for m in result.static_messages_to_speak
                            if "prenotato" in m.text]
        self.assertEqual(len(prenotazione_msgs), 1)
        self.assertFalse(prenotazione_msgs[0].use_tts)

    @patch('apps.moderation.triggers._get_next_reserved_speaker_name', return_value=None)
    @patch('apps.moderation.triggers._get_ready_to_conclude_status', return_value=(2, 3))
    def test_pronti_concludere_message_has_use_tts_true(self, mock_ready, mock_reserved):
        """PRONTI_CONCLUDERE message should have use_tts=True."""
        session_id = "test-session-tts-2"
        mod_state = ModerationState.initial()
        save_moderation_state(session_id, mod_state)

        result = evaluate_triggers_on_human_turn_end(
            session_id=session_id,
            user_id=1,
            session_phase="ACTIVE",
            moderation_state=mod_state,
        )

        pronti_msgs = [m for m in result.static_messages_to_speak
                      if "pronti a concludere" in m.text]
        self.assertEqual(len(pronti_msgs), 1)
        self.assertTrue(pronti_msgs[0].use_tts)
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.TriggerMessagesUseTTSTests -v 2`
Expected: FAIL - AttributeError: 'str' object has no attribute 'text'

**Step 3: Write minimal implementation**

Modificare `_collect_static_messages_for_current_state` in `apps/moderation/triggers.py` (riga 177-202):

```python
def _collect_static_messages_for_current_state(
    *,
    session_id: int | str,
    user_id: int | str,
    session_phase: str,
) -> list[StaticMessage]:
    """
    Raccoglie i messaggi fissi da pronunciare nella finestra post-turno.
    """
    messages: list[StaticMessage] = []

    # 1) Prenotazione intervento: annunciare chi ha la priorità di parola (SOLO TESTO)
    reserved_speaker_name = _get_next_reserved_speaker_name(session_id=session_id)
    if reserved_speaker_name is not None:
        messages.append(StaticMessage(
            text=f"Ora la parola va a {reserved_speaker_name}, che aveva prenotato.",
            use_tts=False,  # Solo testo, no TTS
        ))

    # 2) Pronti alla conclusione: annunciare quanti sono pronti (TTS)
    ready_count, total_count = _get_ready_to_conclude_status(session_id=session_id)
    if session_phase == "ACTIVE" and total_count > 0 and 0 < ready_count < total_count:
        messages.append(StaticMessage(
            text=f"{ready_count} partecipanti su {total_count} sono pronti a concludere.",
            use_tts=True,
        ))

    return messages
```

Modificare anche il blocco timer 30 in `evaluate_triggers_on_human_turn_end` (riga 81-97):

```python
    # 4) Controllo timer 30 min (solo in fase ACTIVE)
    if session_phase == "ACTIVE":
        timers_state = load_timers_state(session_id)
        if timers_state.session_started_at is not None:
            elapsed = datetime.utcnow() - timers_state.session_started_at
            if elapsed >= TIMER_30_THRESHOLD:
                # Aggiungi messaggio solo se non già notificato (TTS)
                if not timers_state.timer_30_notified:
                    static_messages.append(StaticMessage(
                        text="Il tempo della discussione è terminato. "
                             "Potete avviarvi verso la conclusione.",
                        use_tts=True,
                    ))
                    timers_state.timer_30_notified = True
                    save_timers_state(session_id, timers_state)

                # Segnala il cambio di fase (sempre, anche se già notificato)
                should_transition_to_conclusion = True
```

E aggiornare il tipo di ritorno della funzione e la variabile `static_messages`:

```python
def evaluate_triggers_on_human_turn_end(
    # ... parametri invariati ...
) -> TriggerEvaluationResult:
    # ...
    hard_action = HardModerationAction.NONE
    static_messages: list[StaticMessage] = []  # Cambiato da list[str]
    # ... resto invariato, ma _collect_static_messages_for_current_state ora ritorna List[StaticMessage]
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.TriggerMessagesUseTTSTests -v 2`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add apps/moderation/triggers.py apps/moderation/tests.py
git commit -m "$(cat <<'EOF'
feat(moderation): assign use_tts flags to post-turn static messages

PRENOTAZIONE: use_tts=False (text only, not interrupting)
PRONTI_CONCLUDERE: use_tts=True (spoken announcement)
TIMER_30: use_tts=True (spoken end-of-session)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Update evaluate_time_based_triggers to return StaticMessage objects

**Files:**
- Modify: `apps/moderation/triggers.py:106-138` e `267-333`
- Test: `apps/moderation/tests.py`

**Step 1: Write the failing test**

In `apps/moderation/tests.py`, aggiungere:

```python
class TimeBasedTriggersTTSTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('apps.moderation.triggers._someone_is_currently_speaking', return_value=False)
    def test_no_push_message_has_use_tts_true(self, mock_speaking):
        """NO_PUSH message should have use_tts=True."""
        session_id = "test-session-time-1"

        # Setup: last activity was 20 seconds ago (> 15s threshold)
        timers_state = ModerationTimersState.initial()
        timers_state.session_started_at = datetime.utcnow() - timedelta(minutes=5)
        timers_state.last_any_activity_at = datetime.utcnow() - timedelta(seconds=20)
        timers_state.no_push_notified = False
        save_timers_state(session_id, timers_state)

        result = evaluate_time_based_triggers(
            session_id=session_id,
            session_phase="ACTIVE",
        )

        no_push_msgs = [m for m in result.static_messages_to_speak
                       if "vuole intervenire" in m.text]
        self.assertEqual(len(no_push_msgs), 1)
        self.assertTrue(no_push_msgs[0].use_tts)

    @patch('apps.moderation.triggers._someone_is_currently_speaking', return_value=False)
    def test_timer_25_message_has_use_tts_false(self, mock_speaking):
        """TIMER_25 message should have use_tts=False (text only warning)."""
        session_id = "test-session-time-2"

        # Setup: session started 26 minutes ago
        timers_state = ModerationTimersState.initial()
        timers_state.session_started_at = datetime.utcnow() - timedelta(minutes=26)
        timers_state.last_any_activity_at = datetime.utcnow()  # recent activity
        timers_state.timer_25_notified = False
        save_timers_state(session_id, timers_state)

        result = evaluate_time_based_triggers(
            session_id=session_id,
            session_phase="ACTIVE",
        )

        timer_25_msgs = [m for m in result.static_messages_to_speak
                        if "cinque minuti" in m.text]
        self.assertEqual(len(timer_25_msgs), 1)
        self.assertFalse(timer_25_msgs[0].use_tts)

    @patch('apps.moderation.triggers._someone_is_currently_speaking', return_value=False)
    @patch('apps.moderation.triggers.SessionParticipant')
    def test_utente_inattivo_message_has_use_tts_true(self, mock_participant, mock_speaking):
        """UTENTE_INATTIVO message should have use_tts=True."""
        session_id = "test-session-time-3"

        # Setup: session with one user who never spoke
        timers_state = ModerationTimersState.initial()
        timers_state.session_started_at = datetime.utcnow() - timedelta(minutes=15)
        timers_state.last_any_activity_at = datetime.utcnow()
        timers_state.last_user_speak_at = {}  # No one spoke
        timers_state.inactive_notified_user_ids = []
        save_timers_state(session_id, timers_state)

        # Mock participant
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.display_name = "TestUser"
        mock_user.get_username.return_value = "testuser"

        mock_participant_obj = MagicMock()
        mock_participant_obj.user_id = 1
        mock_participant_obj.user = mock_user

        mock_participant.objects.filter.return_value.select_related.return_value = [mock_participant_obj]

        result = evaluate_time_based_triggers(
            session_id=session_id,
            session_phase="ACTIVE",
        )

        inactive_msgs = [m for m in result.static_messages_to_speak
                        if "buon momento per intervenire" in m.text]
        self.assertEqual(len(inactive_msgs), 1)
        self.assertTrue(inactive_msgs[0].use_tts)
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.TimeBasedTriggersTTSTests -v 2`
Expected: FAIL - AttributeError: 'str' object has no attribute 'text'

**Step 3: Write minimal implementation**

Modificare `_collect_time_based_static_messages` in `apps/moderation/triggers.py` (riga 267-333):

```python
def _collect_time_based_static_messages(
    *,
    session_id: int | str,
    session_phase: str,
) -> list[StaticMessage]:
    """
    Raccoglie i messaggi fissi da generare in base ai soli controlli a tempo,
    nel caso in cui la sessione sia libera (nessuno sta parlando).
    """
    # Import locali per evitare problemi in fase di bootstrap
    from apps.sessions.models import SessionParticipant, SessionState as SessionStateEnum

    messages: list[StaticMessage] = []
    state = load_timers_state(session_id)
    now = datetime.utcnow()

    # 1) NO PUSH (silenzio prolungato nella sessione) - TTS
    if state.last_any_activity_at is not None and not state.no_push_notified:
        if now - state.last_any_activity_at >= NO_PUSH_THRESHOLD:
            messages.append(StaticMessage(
                text="Se qualcuno vuole intervenire, può parlare ora o condividere una breve considerazione.",
                use_tts=True,
            ))
            state.no_push_notified = True

    # 2) TIMER 25'/30' – solo in fase ACTIVE
    if session_phase == SessionStateEnum.ACTIVE and state.session_started_at is not None:
        elapsed = now - state.session_started_at

        # TIMER 25 - Solo testo (non interrompente)
        if (not state.timer_25_notified) and elapsed >= TIMER_25_THRESHOLD:
            messages.append(StaticMessage(
                text="Mancano circa cinque minuti alla fine della discussione.",
                use_tts=False,  # Solo testo
            ))
            state.timer_25_notified = True

        # TIMER 30 - TTS (annuncio importante)
        if (not state.timer_30_notified) and elapsed >= TIMER_30_THRESHOLD:
            messages.append(StaticMessage(
                text="Il tempo della discussione è terminato. Potete avviarvi verso la conclusione.",
                use_tts=True,
            ))
            state.timer_30_notified = True

    # 3) UTENTE INATTIVO - TTS
    if session_phase == SessionStateEnum.ACTIVE:
        participants = (
            SessionParticipant.objects
            .filter(session_id=session_id)
            .select_related("user")
        )

        for p in participants:
            user_id_str = str(p.user_id)

            if user_id_str in state.inactive_notified_user_ids:
                continue

            last_spoke = state.last_user_speak_at.get(user_id_str)

            # Mai parlato, oppure troppo tempo senza parlare
            if last_spoke is None or (now - last_spoke) >= INACTIVE_USER_THRESHOLD:
                display_name = getattr(p.user, "display_name", None) or p.user.get_username()
                messages.append(StaticMessage(
                    text=f"{display_name}, se vuoi condividere un'idea, questo è un buon momento per intervenire.",
                    use_tts=True,
                ))
                state.inactive_notified_user_ids.append(user_id_str)
                # Per l'MVP si notifica al massimo un utente per ping
                break

    # Salvataggio stato timer aggiornato
    save_timers_state(session_id, state)

    return messages
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.TimeBasedTriggersTTSTests -v 2`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add apps/moderation/triggers.py apps/moderation/tests.py
git commit -m "$(cat <<'EOF'
feat(moderation): assign use_tts flags to time-based triggers

NO_PUSH: use_tts=True (spoken prompt for silence)
TIMER_25: use_tts=False (text-only 5min warning)
TIMER_30: use_tts=True (spoken end announcement)
UTENTE_INATTIVO: use_tts=True (spoken prompt for inactive user)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Create PendingMessagesManager for Redis queue

**Files:**
- Create: `apps/moderation/pending_messages.py`
- Test: `apps/moderation/tests.py`

**Step 1: Write the failing test**

In `apps/moderation/tests.py`, aggiungere all'inizio (dopo gli import esistenti):

```python
from apps.moderation.pending_messages import (
    PendingMessage,
    enqueue_message,
    dequeue_all_messages,
    has_pending_messages,
)
```

E aggiungere alla fine:

```python
class PendingMessagesTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_enqueue_and_dequeue_single_message(self):
        """Enqueue a message and dequeue it."""
        session_id = "test-pending-1"

        enqueue_message(session_id, "Test message", "NO_PUSH")

        self.assertTrue(has_pending_messages(session_id))

        messages = dequeue_all_messages(session_id)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].text, "Test message")
        self.assertEqual(messages[0].trigger_type, "NO_PUSH")
        self.assertIsInstance(messages[0].created_at, datetime)

        # After dequeue, queue should be empty
        self.assertFalse(has_pending_messages(session_id))

    def test_enqueue_multiple_messages_fifo_order(self):
        """Multiple messages should be dequeued in FIFO order."""
        session_id = "test-pending-2"

        enqueue_message(session_id, "First", "NO_PUSH")
        enqueue_message(session_id, "Second", "TIMER_30")
        enqueue_message(session_id, "Third", "UTENTE_INATTIVO")

        messages = dequeue_all_messages(session_id)

        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[0].text, "First")
        self.assertEqual(messages[1].text, "Second")
        self.assertEqual(messages[2].text, "Third")

    def test_dequeue_empty_queue_returns_empty_list(self):
        """Dequeuing an empty queue returns empty list."""
        session_id = "test-pending-3"

        messages = dequeue_all_messages(session_id)

        self.assertEqual(messages, [])

    def test_has_pending_messages_false_when_empty(self):
        """has_pending_messages returns False for empty/nonexistent queue."""
        session_id = "test-pending-4"

        self.assertFalse(has_pending_messages(session_id))
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.PendingMessagesTests -v 2`
Expected: FAIL with "No module named 'apps.moderation.pending_messages'"

**Step 3: Write minimal implementation**

Create `apps/moderation/pending_messages.py`:

```python
"""
Gestione coda messaggi TTS pendenti per sessione.

I messaggi che non possono essere riprodotti immediatamente (perché qualcuno
sta parlando) vengono accodati in Redis e riprodotti appena il turno torna IDLE.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List
import json

from django.core.cache import cache


# Chiave Redis: moderation:pending_messages:{session_id}
PENDING_MESSAGES_KEY_PREFIX = "moderation:pending_messages"
PENDING_MESSAGES_TTL = 60 * 60  # 1 hour


@dataclass
class PendingMessage:
    """Messaggio TTS in attesa di essere riprodotto."""
    text: str
    trigger_type: str
    created_at: datetime


def enqueue_message(session_id: int | str, text: str, trigger_type: str) -> None:
    """
    Aggiunge un messaggio TTS alla coda dei messaggi pendenti per la sessione.

    Args:
        session_id: ID della sessione
        text: Testo del messaggio da pronunciare
        trigger_type: Tipo di trigger che ha generato il messaggio (es. NO_PUSH, TIMER_30)
    """
    key = f"{PENDING_MESSAGES_KEY_PREFIX}:{session_id}"

    message_data = {
        "text": text,
        "trigger_type": trigger_type,
        "created_at": datetime.utcnow().isoformat(),
    }

    # Django cache non ha rpush nativo, usiamo get/set
    existing = cache.get(key) or []
    existing.append(json.dumps(message_data))
    cache.set(key, existing, timeout=PENDING_MESSAGES_TTL)


def dequeue_all_messages(session_id: int | str) -> List[PendingMessage]:
    """
    Svuota la coda e ritorna tutti i messaggi pendenti per la sessione.

    Args:
        session_id: ID della sessione

    Returns:
        Lista di PendingMessage in ordine FIFO (primo inserito, primo estratto)
    """
    key = f"{PENDING_MESSAGES_KEY_PREFIX}:{session_id}"

    raw_messages = cache.get(key) or []
    cache.delete(key)

    messages = []
    for raw in raw_messages:
        try:
            data = json.loads(raw)
            messages.append(PendingMessage(
                text=data["text"],
                trigger_type=data["trigger_type"],
                created_at=datetime.fromisoformat(data["created_at"]),
            ))
        except (json.JSONDecodeError, KeyError):
            continue

    return messages


def has_pending_messages(session_id: int | str) -> bool:
    """
    Verifica se ci sono messaggi TTS pendenti per la sessione.

    Args:
        session_id: ID della sessione

    Returns:
        True se ci sono messaggi in coda, False altrimenti
    """
    key = f"{PENDING_MESSAGES_KEY_PREFIX}:{session_id}"
    existing = cache.get(key)
    return bool(existing)
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.PendingMessagesTests -v 2`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add apps/moderation/pending_messages.py apps/moderation/tests.py
git commit -m "$(cat <<'EOF'
feat(moderation): add PendingMessagesManager for TTS queue

Implements Redis-backed FIFO queue for TTS messages that cannot be
played immediately (when someone is speaking). Messages are dequeued
and played when turn returns to IDLE.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Update ModerationOrchestrator to propagate StaticMessage

**Files:**
- Modify: `apps/moderation/orchestrator.py`
- Test: `apps/moderation/tests.py`

**Step 1: Write the failing test**

In `apps/moderation/tests.py`, modificare `FullModerationDecisionTests`:

```python
class FullModerationDecisionTests(TestCase):
    def test_full_decision_has_should_transition_to_conclusion(self):
        """FullModerationDecision should have should_transition_to_conclusion field."""
        decision = FullModerationDecision(
            static_messages_to_speak=[],
            ai_should_speak=False,
            ai_message=None,
            hard_action=HardModerationAction.NONE,
            should_transition_to_conclusion=True,
        )
        self.assertTrue(decision.should_transition_to_conclusion)

    def test_full_decision_default_false(self):
        """should_transition_to_conclusion should default to False."""
        decision = FullModerationDecision(
            static_messages_to_speak=[],
            ai_should_speak=False,
            ai_message=None,
            hard_action=HardModerationAction.NONE,
        )
        self.assertFalse(decision.should_transition_to_conclusion)

    def test_full_decision_static_messages_are_static_message_objects(self):
        """static_messages_to_speak should contain StaticMessage objects."""
        msg = StaticMessage(text="Test", use_tts=True)
        decision = FullModerationDecision(
            static_messages_to_speak=[msg],
            ai_should_speak=False,
            ai_message=None,
            hard_action=HardModerationAction.NONE,
        )
        self.assertEqual(len(decision.static_messages_to_speak), 1)
        self.assertIsInstance(decision.static_messages_to_speak[0], StaticMessage)
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.FullModerationDecisionTests.test_full_decision_static_messages_are_static_message_objects -v 2`
Expected: May pass (type annotation only) but need to verify integration

**Step 3: Write minimal implementation**

In `apps/moderation/orchestrator.py`, aggiornare gli import e la dataclass:

```python
from dataclasses import dataclass
from typing import List, Optional

from apps.moderation.state import ModerationState, load_moderation_state
from apps.moderation.service import ModerationService, HardModerationAction
from apps.moderation.triggers import (
    evaluate_triggers_on_human_turn_end,
    StaticMessage,
)


@dataclass
class FullModerationDecision:
    """
    Decisione completa di moderazione, comprensiva di:
    - messaggi statici (trigger meccanici)
    - eventuale messaggio AI (LLM)
    - azione hard (riassunto/conclusione)
    - segnale di transizione a CONCLUSION
    """
    static_messages_to_speak: List[StaticMessage]
    ai_should_speak: bool
    ai_message: Optional[str]
    hard_action: HardModerationAction
    should_transition_to_conclusion: bool = False
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.FullModerationDecisionTests -v 2`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add apps/moderation/orchestrator.py apps/moderation/tests.py
git commit -m "$(cat <<'EOF'
refactor(moderation): update FullModerationDecision to use List[StaticMessage]

Aligns orchestrator output with trigger system changes,
enabling TTS vs text-only distinction in consumer.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Add background trigger task infrastructure to TurnsConsumer

**Files:**
- Modify: `apps/turns/ws_consumer.py`
- Test: `apps/turns/tests_consumer.py` (new test file)

**Step 1: Write the failing test**

Create `apps/turns/tests_consumer.py`:

```python
from django.test import TestCase
from django.core.cache import cache
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio

from apps.turns.ws_consumer import TurnsConsumer


class TriggerTaskInfrastructureTests(TestCase):
    def setUp(self):
        cache.clear()
        # Clear any existing trigger tasks
        TurnsConsumer._trigger_tasks.clear()

    def tearDown(self):
        cache.clear()
        TurnsConsumer._trigger_tasks.clear()

    def test_trigger_tasks_dict_exists(self):
        """TurnsConsumer should have class-level _trigger_tasks dict."""
        self.assertIsInstance(TurnsConsumer._trigger_tasks, dict)

    def test_trigger_tasks_lock_exists(self):
        """TurnsConsumer should have class-level _trigger_tasks_lock."""
        self.assertIsInstance(TurnsConsumer._trigger_tasks_lock, asyncio.Lock)
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.turns.tests_consumer.TriggerTaskInfrastructureTests -v 2`
Expected: FAIL with "AttributeError: type object 'TurnsConsumer' has no attribute '_trigger_tasks'"

**Step 3: Write minimal implementation**

In `apps/turns/ws_consumer.py`, aggiungere dopo la riga 9 (`from channels.generic.websocket import AsyncJsonWebsocketConsumer`):

```python
from typing import ClassVar, Dict
```

E all'interno della classe `TurnsConsumer`, dopo la docstring (riga 52), aggiungere:

```python
    # -------------------------------------------------------------------------
    # Background trigger task management (class-level, shared across instances)
    # -------------------------------------------------------------------------
    _trigger_tasks: ClassVar[Dict[str, asyncio.Task]] = {}
    _trigger_tasks_lock: ClassVar[asyncio.Lock] = asyncio.Lock()
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.turns.tests_consumer.TriggerTaskInfrastructureTests -v 2`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add apps/turns/ws_consumer.py apps/turns/tests_consumer.py
git commit -m "$(cat <<'EOF'
feat(turns): add background trigger task infrastructure

Adds class-level _trigger_tasks dict and lock for managing
per-session background tasks that evaluate time-based triggers.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Implement _maybe_start_trigger_task and _maybe_stop_trigger_task

**Files:**
- Modify: `apps/turns/ws_consumer.py`
- Test: `apps/turns/tests_consumer.py`

**Step 1: Write the failing test**

In `apps/turns/tests_consumer.py`, aggiungere:

```python
class TriggerTaskLifecycleTests(TestCase):
    def setUp(self):
        cache.clear()
        TurnsConsumer._trigger_tasks.clear()

    def tearDown(self):
        cache.clear()
        # Cancel any running tasks
        for task in TurnsConsumer._trigger_tasks.values():
            task.cancel()
        TurnsConsumer._trigger_tasks.clear()

    @patch.object(TurnsConsumer, '_trigger_loop', new_callable=AsyncMock)
    @patch.object(TurnsConsumer, '_get_session_state', new_callable=AsyncMock)
    async def test_maybe_start_creates_task_for_active_session(self, mock_get_state, mock_loop):
        """_maybe_start_trigger_task creates task for ACTIVE session."""
        mock_get_state.return_value = "ACTIVE"
        mock_loop.return_value = None

        consumer = TurnsConsumer()
        consumer.session_id = "test-session-1"

        await consumer._maybe_start_trigger_task()

        self.assertIn("test-session-1", TurnsConsumer._trigger_tasks)

    @patch.object(TurnsConsumer, '_get_session_state', new_callable=AsyncMock)
    async def test_maybe_start_skips_non_active_session(self, mock_get_state):
        """_maybe_start_trigger_task does nothing for non-ACTIVE session."""
        mock_get_state.return_value = "LOBBY"

        consumer = TurnsConsumer()
        consumer.session_id = "test-session-2"

        await consumer._maybe_start_trigger_task()

        self.assertNotIn("test-session-2", TurnsConsumer._trigger_tasks)

    async def test_maybe_stop_cancels_existing_task(self):
        """_maybe_stop_trigger_task cancels and removes task."""
        # Create a dummy task
        async def dummy_loop():
            while True:
                await asyncio.sleep(1)

        task = asyncio.create_task(dummy_loop())
        TurnsConsumer._trigger_tasks["test-session-3"] = task

        consumer = TurnsConsumer()
        consumer.session_id = "test-session-3"

        await consumer._maybe_stop_trigger_task()

        self.assertNotIn("test-session-3", TurnsConsumer._trigger_tasks)
        self.assertTrue(task.cancelled())
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.turns.tests_consumer.TriggerTaskLifecycleTests -v 2`
Expected: FAIL with "AttributeError: 'TurnsConsumer' object has no attribute '_maybe_start_trigger_task'"

**Step 3: Write minimal implementation**

In `apps/turns/ws_consumer.py`, aggiungere i metodi alla classe TurnsConsumer:

```python
    # -------------------------------------------------------------------------
    # Background trigger task lifecycle
    # -------------------------------------------------------------------------

    async def _maybe_start_trigger_task(self) -> None:
        """
        Avvia il background task per i trigger temporali se:
        - La sessione è in stato ACTIVE
        - Non esiste già un task per questa sessione
        """
        async with self._trigger_tasks_lock:
            if self.session_id in self._trigger_tasks:
                return

            try:
                session_state = await self._get_session_state(self.session_id)
            except Exception:
                return

            if session_state != "ACTIVE":
                return

            task = asyncio.create_task(self._trigger_loop(self.session_id))
            self._trigger_tasks[self.session_id] = task
            logger.info(
                "[TRIGGER_TASK][START] session=%s",
                self.session_id,
            )

    async def _maybe_stop_trigger_task(self) -> None:
        """
        Ferma il background task per i trigger temporali se esiste.
        Chiamato quando l'ultimo client si disconnette.
        """
        async with self._trigger_tasks_lock:
            task = self._trigger_tasks.pop(self.session_id, None)
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                logger.info(
                    "[TRIGGER_TASK][STOP] session=%s",
                    self.session_id,
                )

    async def _trigger_loop(self, session_id: str) -> None:
        """
        Loop che ogni 5s valuta i trigger temporali.
        Placeholder - implementazione completa nel prossimo task.
        """
        pass
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.turns.tests_consumer.TriggerTaskLifecycleTests -v 2`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add apps/turns/ws_consumer.py apps/turns/tests_consumer.py
git commit -m "$(cat <<'EOF'
feat(turns): add trigger task lifecycle methods

_maybe_start_trigger_task: starts background task for ACTIVE sessions
_maybe_stop_trigger_task: cancels task on disconnect

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Implement _trigger_loop with trigger evaluation

**Files:**
- Modify: `apps/turns/ws_consumer.py`
- Test: `apps/turns/tests_consumer.py`

**Step 1: Write the failing test**

In `apps/turns/tests_consumer.py`, aggiungere:

```python
from apps.moderation.triggers import StaticMessage, TriggerEvaluationResult
from apps.moderation.service import HardModerationAction


class TriggerLoopTests(TestCase):
    def setUp(self):
        cache.clear()
        TurnsConsumer._trigger_tasks.clear()

    def tearDown(self):
        cache.clear()
        for task in TurnsConsumer._trigger_tasks.values():
            task.cancel()
        TurnsConsumer._trigger_tasks.clear()

    @patch('apps.turns.ws_consumer.evaluate_time_based_triggers')
    @patch.object(TurnsConsumer, '_get_session_state', new_callable=AsyncMock)
    @patch.object(TurnsConsumer, '_execute_static_messages', new_callable=AsyncMock)
    @patch.object(TurnsConsumer, '_flush_pending_tts_messages', new_callable=AsyncMock)
    async def test_trigger_loop_evaluates_triggers(
        self, mock_flush, mock_execute, mock_get_state, mock_evaluate
    ):
        """_trigger_loop evaluates triggers and executes messages."""
        mock_get_state.return_value = "ACTIVE"
        mock_evaluate.return_value = TriggerEvaluationResult(
            hard_action=HardModerationAction.NONE,
            static_messages_to_speak=[
                StaticMessage(text="Test message", use_tts=True),
            ],
        )

        consumer = TurnsConsumer()
        consumer.session_id = "test-loop-1"
        consumer.channel_layer = MagicMock()
        consumer.group_name = "turns_test-loop-1"

        # Run one iteration (mock sleep to return immediately then raise to exit loop)
        with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            mock_sleep.side_effect = [None, asyncio.CancelledError()]

            try:
                await consumer._trigger_loop("test-loop-1")
            except asyncio.CancelledError:
                pass

        mock_evaluate.assert_called_once()
        mock_execute.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.turns.tests_consumer.TriggerLoopTests -v 2`
Expected: FAIL - methods not implemented

**Step 3: Write minimal implementation**

In `apps/turns/ws_consumer.py`, aggiornare `_trigger_loop`:

```python
    async def _trigger_loop(self, session_id: str) -> None:
        """
        Loop che ogni 5s valuta i trigger temporali.

        - Se nessuno sta parlando e ci sono messaggi, li esegue
        - Se qualcuno sta parlando e ci sono messaggi TTS, li accoda
        - Svuota la coda se IDLE e ci sono messaggi pendenti
        """
        while True:
            await asyncio.sleep(5)

            try:
                session_phase = await self._get_session_state(session_id)
            except Exception:
                continue

            # Valuta trigger temporali
            trig_result = evaluate_time_based_triggers(
                session_id=session_id,
                session_phase=session_phase,
            )

            # Esegui/accoda i messaggi
            if trig_result.static_messages_to_speak:
                await self._execute_static_messages(trig_result.static_messages_to_speak)

            # Svuota coda messaggi pendenti se IDLE
            await self._flush_pending_tts_messages()
```

E aggiungere i metodi placeholder:

```python
    async def _execute_static_messages(self, messages: list) -> None:
        """Placeholder - implementazione nel prossimo task."""
        pass

    async def _flush_pending_tts_messages(self) -> None:
        """Placeholder - implementazione nel prossimo task."""
        pass
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.turns.tests_consumer.TriggerLoopTests -v 2`
Expected: PASS (1 test)

**Step 5: Commit**

```bash
git add apps/turns/ws_consumer.py apps/turns/tests_consumer.py
git commit -m "$(cat <<'EOF'
feat(turns): implement _trigger_loop with 5s evaluation cycle

Background loop that evaluates time-based triggers every 5 seconds,
executes static messages, and flushes pending TTS queue when IDLE.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10-18: Remaining Implementation

I task rimanenti seguono lo stesso pattern TDD:

- **Task 10**: `_execute_static_messages` - routing TTS vs text-only
- **Task 11**: `_execute_tts_messages` - audio streaming via WebRTC
- **Task 12**: `_flush_pending_tts_messages` - svuotamento coda
- **Task 13**: Integrazione con `connect()`/`disconnect()`
- **Task 14**: Integrazione flush in `_handle_end_speak`
- **Task 15**: Aggiornamento `_handle_end_speak` per StaticMessage
- **Task 16**: Test suite completa
- **Task 17**: Aggiornamento `_handle_ping` per StaticMessage
- **Task 18**: Test finale e cleanup

Ogni task include:
1. Test che fallisce
2. Implementazione minima
3. Test che passa
4. Commit atomico

---

## Summary

Questo piano implementa:

1. **StaticMessage dataclass** con flag `use_tts`
2. **PendingMessagesManager** per coda Redis
3. **Background asyncio task** (5s cycle)
4. **Handler unificato** `_execute_static_messages`
5. **Flush della coda** ai punti strategici
6. **Integrazione** con flussi esistenti

**Trigger TTS assignments:**
- NO_PUSH: `use_tts=True` (spoken)
- TIMER_25: `use_tts=False` (text only)
- TIMER_30: `use_tts=True` (spoken)
- UTENTE_INATTIVO: `use_tts=True` (spoken)
- PRENOTAZIONE: `use_tts=False` (text only)
- PRONTI_CONCLUDERE: `use_tts=True` (spoken)
