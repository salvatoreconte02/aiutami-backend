# Intro Message Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** When a session transitions from LOBBY to ACTIVE, the AI moderator speaks an introduction message explaining how to use the app while all user interactions are blocked.

**Architecture:** New turn state `AI_INTRODUCING` that blocks all user interactions. A Redis flag marks intro as pending. The trigger loop in `ws_consumer.py` detects the flag and executes TTS intro. After intro, state transitions to `IDLE`.

**Tech Stack:** Django, Redis (django.core.cache), Channels WebSocket, Azure TTS

---

## Task 1: Create intro.py Module

**Files:**
- Create: `apps/moderation/intro.py`
- Test: `apps/moderation/tests_intro.py`

**Step 1: Write the failing test for intro message generation**

Create file `apps/moderation/tests_intro.py`:

```python
from django.test import TestCase
from django.core.cache import cache


class IntroMessageGenerationTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_format_participant_names_three_names(self):
        """format_participant_names should format 3 names as 'A, B e C'."""
        from apps.moderation.intro import format_participant_names

        result = format_participant_names(["Marco", "Giulia", "Luca"])
        self.assertEqual(result, "Marco, Giulia e Luca")

    def test_format_participant_names_two_names(self):
        """format_participant_names should handle 2 names as fallback."""
        from apps.moderation.intro import format_participant_names

        result = format_participant_names(["Marco", "Giulia"])
        self.assertEqual(result, "Marco, Giulia")

    def test_intro_message_template_exists(self):
        """INTRO_MESSAGE_TEMPLATE should be defined."""
        from apps.moderation.intro import INTRO_MESSAGE_TEMPLATE

        self.assertIn("Benvenuti", INTRO_MESSAGE_TEMPLATE)
        self.assertIn("{nomi}", INTRO_MESSAGE_TEMPLATE)
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests_intro.IntroMessageGenerationTests -v 2`
Expected: FAIL with "No module named 'apps.moderation.intro'" or similar

**Step 3: Write the intro.py module (template + format function)**

Create file `apps/moderation/intro.py`:

```python
"""
Intro message module for AI moderator introduction at session start.
"""
from django.core.cache import cache


INTRO_MESSAGE_TEMPLATE = (
    "Benvenuti {nomi}. Sono il moderatore e vi guiderò nella discussione. "
    "Per parlare, premete il pulsante microfono. Se qualcuno sta già parlando, potete prenotarvi. "
    "Ascoltate gli altri e argomentate le vostre ipotesi. Avrete a disposizione trenta minuti per confrontarvi. "
    "Quando avrete capito chi è il colpevole, premete 'Pronto alla conclusione'. "
    "Buona discussione!"
)


def format_participant_names(names: list[str]) -> str:
    """
    Format participant names for intro message.
    For 3 names: "Marco, Giulia e Luca"
    For other counts: comma-separated fallback
    """
    if len(names) == 3:
        return f"{names[0]}, {names[1]} e {names[2]}"
    return ", ".join(names)
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests_intro.IntroMessageGenerationTests -v 2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/moderation/intro.py apps/moderation/tests_intro.py
git commit -m "feat(intro): add intro message template and name formatting"
```

---

## Task 2: Add Redis Flag Functions to intro.py

**Files:**
- Modify: `apps/moderation/intro.py`
- Modify: `apps/moderation/tests_intro.py`

**Step 1: Write the failing test for Redis flag functions**

Add to `apps/moderation/tests_intro.py`:

```python
class IntroPendingFlagTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_set_intro_pending(self):
        """set_intro_pending should set flag in Redis."""
        from apps.moderation.intro import set_intro_pending, has_intro_pending

        set_intro_pending("session-123")
        self.assertTrue(has_intro_pending("session-123"))

    def test_clear_intro_pending(self):
        """clear_intro_pending should remove flag from Redis."""
        from apps.moderation.intro import set_intro_pending, clear_intro_pending, has_intro_pending

        set_intro_pending("session-123")
        clear_intro_pending("session-123")
        self.assertFalse(has_intro_pending("session-123"))

    def test_has_intro_pending_false_when_not_set(self):
        """has_intro_pending should return False when flag not set."""
        from apps.moderation.intro import has_intro_pending

        self.assertFalse(has_intro_pending("session-456"))
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests_intro.IntroPendingFlagTests -v 2`
Expected: FAIL with "cannot import name 'set_intro_pending'"

**Step 3: Add Redis flag functions to intro.py**

Add to `apps/moderation/intro.py`:

```python
def set_intro_pending(session_id: str) -> None:
    """Mark that a session has a pending intro message."""
    cache.set(f"session:intro_pending:{session_id}", True, timeout=300)


def clear_intro_pending(session_id: str) -> None:
    """Remove the pending intro flag."""
    cache.delete(f"session:intro_pending:{session_id}")


def has_intro_pending(session_id: str) -> bool:
    """Check if a session has a pending intro message."""
    return cache.get(f"session:intro_pending:{session_id}") is True
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests_intro.IntroPendingFlagTests -v 2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/moderation/intro.py apps/moderation/tests_intro.py
git commit -m "feat(intro): add Redis flag functions for pending intro"
```

---

## Task 3: Add generate_intro_message Function

**Files:**
- Modify: `apps/moderation/intro.py`
- Modify: `apps/moderation/tests_intro.py`

**Step 1: Write the failing test for generate_intro_message**

Add to `apps/moderation/tests_intro.py`:

```python
from django.contrib.auth import get_user_model
from apps.sessions.models import Session, SessionParticipant


class GenerateIntroMessageTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user1 = User.objects.create_user(username="user1", password="test123")
        self.user2 = User.objects.create_user(username="user2", password="test123")
        self.user3 = User.objects.create_user(username="user3", password="test123")
        # Set display names
        self.user1.display_name = "Marco"
        self.user1.save()
        self.user2.display_name = "Giulia"
        self.user2.save()
        self.user3.display_name = "Luca"
        self.user3.save()

        self.session = Session.objects.create(host=self.user1)
        SessionParticipant.objects.create(session=self.session, user=self.user1)
        SessionParticipant.objects.create(session=self.session, user=self.user2)
        SessionParticipant.objects.create(session=self.session, user=self.user3)

    def tearDown(self):
        cache.clear()
        SessionParticipant.objects.all().delete()
        Session.objects.all().delete()
        get_user_model().objects.all().delete()

    def test_generate_intro_message_includes_names(self):
        """generate_intro_message should include participant names."""
        from apps.moderation.intro import generate_intro_message

        result = generate_intro_message(str(self.session.id))
        self.assertIn("Marco", result)
        self.assertIn("Giulia", result)
        self.assertIn("Luca", result)

    def test_generate_intro_message_includes_template_text(self):
        """generate_intro_message should include template instructions."""
        from apps.moderation.intro import generate_intro_message

        result = generate_intro_message(str(self.session.id))
        self.assertIn("Benvenuti", result)
        self.assertIn("pulsante microfono", result)
        self.assertIn("Buona discussione", result)
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests_intro.GenerateIntroMessageTests -v 2`
Expected: FAIL with "cannot import name 'generate_intro_message'"

**Step 3: Add generate_intro_message function to intro.py**

Add to `apps/moderation/intro.py`:

```python
def generate_intro_message(session_id: str) -> str:
    """
    Generate the intro message with participant names.

    Args:
        session_id: The session ID (UUID string)

    Returns:
        The formatted intro message with participant names
    """
    from apps.sessions.models import SessionParticipant

    participants = SessionParticipant.objects.filter(
        session_id=session_id
    ).select_related("user")

    names = [
        getattr(p.user, "display_name", None) or p.user.get_username()
        for p in participants
    ]

    return INTRO_MESSAGE_TEMPLATE.format(nomi=format_participant_names(names))
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests_intro.GenerateIntroMessageTests -v 2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/moderation/intro.py apps/moderation/tests_intro.py
git commit -m "feat(intro): add generate_intro_message with participant names"
```

---

## Task 4: Add AI_INTRODUCING State and set_introducing Method to TurnManager

**Files:**
- Modify: `apps/turns/services.py:15-18` (add new constant)
- Modify: `apps/turns/services.py` (add set_introducing method after line 548)
- Test: `apps/turns/tests_services.py` (create new file)

**Step 1: Write the failing test for AI_INTRODUCING state**

Create file `apps/turns/tests_services.py`:

```python
from django.test import TestCase
from django.core.cache import cache


class TurnStateAIIntroducingTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_turn_state_ai_introducing_exists(self):
        """TURN_STATE_AI_INTRODUCING constant should exist."""
        from apps.turns.services import TURN_STATE_AI_INTRODUCING

        self.assertEqual(TURN_STATE_AI_INTRODUCING, "AI_INTRODUCING")

    def test_set_introducing_changes_state(self):
        """set_introducing should change turn state to AI_INTRODUCING."""
        from apps.turns.services import TurnManager, TURN_STATE_AI_INTRODUCING

        session_id = "test-session-intro"
        state = TurnManager.set_introducing(session_id)

        self.assertEqual(state.state, TURN_STATE_AI_INTRODUCING)

    def test_set_introducing_increments_version(self):
        """set_introducing should increment version."""
        from apps.turns.services import TurnManager

        session_id = "test-session-intro"
        # Initial state has version=1
        initial = TurnManager.get_state_only(session_id)
        initial_version = initial.version if initial else 1

        state = TurnManager.set_introducing(session_id)

        self.assertGreater(state.version, initial_version)
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.turns.tests_services.TurnStateAIIntroducingTests -v 2`
Expected: FAIL with "cannot import name 'TURN_STATE_AI_INTRODUCING'"

**Step 3: Add AI_INTRODUCING constant and set_introducing method**

In `apps/turns/services.py`, after line 17 (after `TURN_STATE_AI_SPEAKING = "AI_SPEAKING"`), add:

```python
TURN_STATE_AI_INTRODUCING = "AI_INTRODUCING"
```

In `apps/turns/services.py`, after line 548 (after `set_moderation_in_progress` method), add:

```python
    @classmethod
    def set_introducing(cls, session_id: str) -> TurnState:
        """
        Set turn state to AI_INTRODUCING for session intro.

        Called when session transitions from LOBBY to ACTIVE to block
        all user interactions while the AI moderator speaks the introduction.
        """
        state = cls._load_state(session_id)
        state.state = TURN_STATE_AI_INTRODUCING
        state.version += 1
        cls._save_state(session_id, state)
        return state
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.turns.tests_services.TurnStateAIIntroducingTests -v 2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/turns/services.py apps/turns/tests_services.py
git commit -m "feat(turns): add AI_INTRODUCING state and set_introducing method"
```

---

## Task 5: Add end_introducing Method to TurnManager

**Files:**
- Modify: `apps/turns/services.py` (add method after set_introducing)
- Modify: `apps/turns/tests_services.py`

**Step 1: Write the failing test for end_introducing**

Add to `apps/turns/tests_services.py`:

```python
class TurnStateEndIntroducingTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_end_introducing_transitions_to_idle(self):
        """end_introducing should change state from AI_INTRODUCING to IDLE."""
        from apps.turns.services import TurnManager, TURN_STATE_AI_INTRODUCING, TURN_STATE_IDLE

        session_id = "test-session-intro"
        TurnManager.set_introducing(session_id)

        state = TurnManager.end_introducing(session_id)

        self.assertEqual(state.state, TURN_STATE_IDLE)

    def test_end_introducing_increments_version(self):
        """end_introducing should increment version."""
        from apps.turns.services import TurnManager

        session_id = "test-session-intro"
        TurnManager.set_introducing(session_id)
        state_before = TurnManager.get_state_only(session_id)

        state = TurnManager.end_introducing(session_id)

        self.assertGreater(state.version, state_before.version)
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.turns.tests_services.TurnStateEndIntroducingTests -v 2`
Expected: FAIL with "'TurnManager' object has no attribute 'end_introducing'"

**Step 3: Add end_introducing method**

In `apps/turns/services.py`, after `set_introducing` method, add:

```python
    @classmethod
    def end_introducing(cls, session_id: str) -> TurnState:
        """
        End the intro phase and transition to IDLE.

        Called after the AI moderator finishes speaking the introduction.
        """
        state = cls._load_state(session_id)
        state.state = TURN_STATE_IDLE
        state.version += 1
        cls._save_state(session_id, state)
        return state
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.turns.tests_services.TurnStateEndIntroducingTests -v 2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/turns/services.py apps/turns/tests_services.py
git commit -m "feat(turns): add end_introducing method"
```

---

## Task 6: Block request_speak During AI_INTRODUCING

**Files:**
- Modify: `apps/turns/services.py:149-165` (add check after moderation_in_progress check)
- Modify: `apps/turns/tests_services.py`

**Step 1: Write the failing test for request_speak block**

Add to `apps/turns/tests_services.py`:

```python
from django.contrib.auth import get_user_model
from apps.sessions.models import Session, SessionParticipant


class RequestSpeakBlockedDuringIntroTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user(username="testuser", password="test123")
        self.session = Session.objects.create(host=self.user)
        SessionParticipant.objects.create(session=self.session, user=self.user)

    def tearDown(self):
        cache.clear()
        SessionParticipant.objects.all().delete()
        Session.objects.all().delete()
        get_user_model().objects.all().delete()

    def test_request_speak_blocked_during_ai_introducing(self):
        """request_speak should return error during AI_INTRODUCING."""
        from apps.turns.services import TurnManager

        session_id = str(self.session.id)
        TurnManager.set_introducing(session_id)

        result = TurnManager.request_speak(session_id, self.user)

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "INTRO_IN_PROGRESS")
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.turns.tests_services.RequestSpeakBlockedDuringIntroTests -v 2`
Expected: FAIL (currently request_speak will return different error or succeed)

**Step 3: Add AI_INTRODUCING check to request_speak**

In `apps/turns/services.py`, in `request_speak` method after line 165 (after the CONCLUSION check), add:

```python
        # Block turns during AI_INTRODUCING (intro in progress)
        if state.state == TURN_STATE_AI_INTRODUCING:
            return TurnResult(
                success=False,
                state=state,
                events=events,
                error_code="INTRO_IN_PROGRESS",
                error_detail="Il moderatore sta introducendo la sessione.",
            )
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.turns.tests_services.RequestSpeakBlockedDuringIntroTests -v 2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/turns/services.py apps/turns/tests_services.py
git commit -m "feat(turns): block request_speak during AI_INTRODUCING"
```

---

## Task 7: Block request_reserve During AI_INTRODUCING

**Files:**
- Modify: `apps/turns/services.py:298-329` (add check after moderation_in_progress check)
- Modify: `apps/turns/tests_services.py`

**Step 1: Write the failing test for request_reserve block**

Add to `apps/turns/tests_services.py`:

```python
class RequestReserveBlockedDuringIntroTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user(username="testuser2", password="test123")
        self.session = Session.objects.create(host=self.user)
        SessionParticipant.objects.create(session=self.session, user=self.user)

    def tearDown(self):
        cache.clear()
        SessionParticipant.objects.all().delete()
        Session.objects.all().delete()
        get_user_model().objects.all().delete()

    def test_request_reserve_blocked_during_ai_introducing(self):
        """request_reserve should return error during AI_INTRODUCING."""
        from apps.turns.services import TurnManager

        session_id = str(self.session.id)
        TurnManager.set_introducing(session_id)

        result = TurnManager.request_reserve(session_id, self.user)

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "INTRO_IN_PROGRESS")
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.turns.tests_services.RequestReserveBlockedDuringIntroTests -v 2`
Expected: FAIL (currently request_reserve will return different error)

**Step 3: Add AI_INTRODUCING check to request_reserve**

In `apps/turns/services.py`, in `request_reserve` method after line 328 (after the moderation_in_progress check), add:

```python
        # Block reservations during AI_INTRODUCING (intro in progress)
        if state.state == TURN_STATE_AI_INTRODUCING:
            return TurnResult(
                success=False,
                state=state,
                events=events,
                error_code="INTRO_IN_PROGRESS",
                error_detail="Il moderatore sta introducendo la sessione.",
            )
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.turns.tests_services.RequestReserveBlockedDuringIntroTests -v 2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/turns/services.py apps/turns/tests_services.py
git commit -m "feat(turns): block request_reserve during AI_INTRODUCING"
```

---

## Task 8: Add AI_INTRODUCING to _someone_is_currently_speaking in triggers.py

**Files:**
- Modify: `apps/moderation/triggers.py:351-362`
- Modify: `apps/moderation/tests.py`

**Step 1: Write the failing test for _someone_is_currently_speaking**

Add to `apps/moderation/tests.py` (find appropriate location):

```python
class SomeoneIsSpeakingDuringIntroTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_someone_speaking_true_during_ai_introducing(self):
        """_someone_is_currently_speaking should return True during AI_INTRODUCING."""
        from apps.moderation.triggers import _someone_is_currently_speaking
        from apps.turns.services import TurnManager

        session_id = "test-session-intro"
        TurnManager.set_introducing(session_id)

        result = _someone_is_currently_speaking(session_id)

        self.assertTrue(result)
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.SomeoneIsSpeakingDuringIntroTests -v 2`
Expected: FAIL (returns False)

**Step 3: Add AI_INTRODUCING to _someone_is_currently_speaking**

In `apps/moderation/triggers.py`, modify the import at line 107-111 to include `TURN_STATE_AI_INTRODUCING`:

```python
from apps.turns.services import (
    TurnState,
    TURN_STATE_HUMAN_SPEAKING,
    TURN_STATE_AI_SPEAKING,
    TURN_STATE_AI_INTRODUCING,
)
```

Then modify `_someone_is_currently_speaking` (around line 361) to include AI_INTRODUCING:

```python
def _someone_is_currently_speaking(session_id: int | str) -> bool:
    """
    Verifica, tramite lo stato dei turni, se c'è un HUMAN_SPEAKING, AI_SPEAKING o AI_INTRODUCING attivo.
    """
    key = f"turns:{session_id}"
    stored = cache.get(key)

    if not isinstance(stored, TurnState):
        return False

    return stored.state in (TURN_STATE_HUMAN_SPEAKING, TURN_STATE_AI_SPEAKING, TURN_STATE_AI_INTRODUCING)
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.SomeoneIsSpeakingDuringIntroTests -v 2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/moderation/triggers.py apps/moderation/tests.py
git commit -m "feat(moderation): add AI_INTRODUCING to _someone_is_currently_speaking"
```

---

## Task 9: Modify SessionStartView to Initialize AI_INTRODUCING

**Files:**
- Modify: `apps/sessions/views.py:97-131` (SessionStartView.post method)
- Test: Manual test (view test requires complex setup)

**Step 1: Add imports to views.py**

At the top of `apps/sessions/views.py`, after line 33 (after pending_messages import), add:

```python
from apps.turns.services import TurnManager
from apps.moderation.intro import set_intro_pending
```

**Step 2: Modify SessionStartView.post to initialize AI_INTRODUCING**

In `apps/sessions/views.py`, in `SessionStartView.post` method, after line 112 (`session = serializer.save()`), add:

```python
        # Initialize turn state to AI_INTRODUCING (blocks all interactions)
        TurnManager.set_introducing(session_id=str(session.id))

        # Mark intro as pending (will be executed by trigger loop)
        set_intro_pending(session_id=str(session.id))
```

The updated method should look like:

```python
    def post(self, request, session_id: str):
        session = get_object_or_404(Session, pk=session_id)
        serializer = SessionStartSerializer(
            instance=session,
            data={},
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        session = serializer.save()

        # Initialize turn state to AI_INTRODUCING (blocks all interactions)
        TurnManager.set_introducing(session_id=str(session.id))

        # Mark intro as pending (will be executed by trigger loop)
        set_intro_pending(session_id=str(session.id))

        # 🔹 La sessione è appena entrata in ACTIVE:
        #    si inizializzano i timer di moderazione (NO PUSH, TIMER 25'/30').
        mark_session_started(session_id=session.id)

        # Payload completo della sessione dopo la transizione
        detail_data = SessionDetailSerializer(
            session,
            context={"request": request},
        ).data

        # Broadcast WS: la sessione ha cambiato stato (es. LOBBY -> ACTIVE)
        _broadcast_session_event(
            session_id=str(session.id),
            event_type="STATE_CHANGED",
            payload=detail_data,
        )

        return Response(detail_data, status=status.HTTP_200_OK)
```

**Step 3: Run existing tests to verify no regression**

Run: `docker compose run --rm web python manage.py test apps.sessions -v 2`
Expected: PASS (no regressions)

**Step 4: Commit**

```bash
git add apps/sessions/views.py
git commit -m "feat(sessions): initialize AI_INTRODUCING and intro flag on session start"
```

---

## Task 10: Add _execute_intro_message Method to TurnsConsumer

**Files:**
- Modify: `apps/turns/ws_consumer.py` (add new method)

**Step 1: Add imports to ws_consumer.py**

At the top of `apps/turns/ws_consumer.py`, after line 22 (after existing imports), add:

```python
from apps.moderation.intro import (
    has_intro_pending,
    clear_intro_pending,
    generate_intro_message,
)
```

**Step 2: Add _execute_intro_message method**

In `apps/turns/ws_consumer.py`, add the following method after `_execute_tts_message` (around line 1288):

```python
    async def _execute_intro_message(self, session_id: str) -> None:
        """
        Execute the AI moderator introduction message.

        Called when a session starts with intro pending.
        """
        from apps.turns.services import TurnManager

        logger.info("[INTRO_MESSAGE][START] session=%s", session_id)

        # 1. Brief delay for clients to settle
        await asyncio.sleep(2.5)

        # 2. Generate message with participant names
        intro_text = await database_sync_to_async(generate_intro_message)(session_id)

        # 3. Execute TTS (state is already AI_INTRODUCING, no need to change to AI_SPEAKING)
        hub = get_hub(session_id)
        hub.init_ai_track()
        hub.set_speaker(AI_MODERATOR_ID)

        try:
            tts = TTSService()
            tts_result = await tts.synthesize_stream(
                text=intro_text,
                on_audio_chunk=lambda pcm, samples, sr: self._inject_ai_audio(hub, pcm, samples, sr)
            )
            logger.info("[INTRO_MESSAGE][TTS_DONE] session=%s success=%s", session_id, tts_result.success)

            if not tts_result.success:
                logger.warning("[INTRO_MESSAGE][TTS_FAILED] session=%s error=%s", session_id, tts_result.error)
                # Fallback to text message
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        "type": "turns.event",
                        "event_type": "STATIC_MESSAGE",
                        "payload": {"text": intro_text, "use_tts": False},
                    },
                )

            # Append to transcript
            _append_to_session_transcript(session_id, {
                "type": "ai",
                "text": intro_text,
                "trigger": "intro",
                "timestamp": datetime.utcnow().isoformat()
            })

        except Exception as e:
            logger.error("[INTRO_MESSAGE][ERROR] session=%s error=%s", session_id, e, exc_info=True)

        finally:
            hub.set_speaker(None)

            # 4. Transition to IDLE
            TurnManager.end_introducing(session_id)

            # 5. Reset NO_PUSH timer (activity just happened)
            await self._mark_any_activity()

            # 6. Broadcast AI_ENDED event
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "turns.event",
                    "event_type": "AI_ENDED",
                    "payload": {},
                },
            )

            # 7. Broadcast state change to IDLE
            state = TurnManager.get_state_only(session_id)
            if state:
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        "type": "turns.event",
                        "event_type": "STATE_CHANGED",
                        "payload": state.to_dict(),
                    },
                )

            # 8. Remove pending flag
            clear_intro_pending(session_id)

            logger.info("[INTRO_MESSAGE][END] session=%s", session_id)
```

**Step 3: Commit**

```bash
git add apps/turns/ws_consumer.py
git commit -m "feat(turns): add _execute_intro_message method"
```

---

## Task 11: Add Intro Check to Trigger Loop

**Files:**
- Modify: `apps/turns/ws_consumer.py:1069-1143` (_trigger_loop method)

**Step 1: Modify _trigger_loop to check for pending intro**

In `apps/turns/ws_consumer.py`, in `_trigger_loop` method, after line 1082 (inside the while loop, before `session_phase = await...`), add:

```python
                # CHECK INTRO PENDING (before everything else)
                if has_intro_pending(session_id):
                    state = TurnManager.get_state_only(session_id)
                    if state and state.state == "AI_INTRODUCING":
                        await self._execute_intro_message(session_id)
                        continue  # Skip rest of loop iteration
```

The updated section should look like:

```python
        while True:
            try:
                await asyncio.sleep(5)

                logger.debug("[TRIGGER_LOOP][TICK] session=%s", session_id)

                # CHECK INTRO PENDING (before everything else)
                if has_intro_pending(session_id):
                    state = TurnManager.get_state_only(session_id)
                    if state and state.state == "AI_INTRODUCING":
                        await self._execute_intro_message(session_id)
                        continue  # Skip rest of loop iteration

                try:
                    session_phase = await self._get_session_state(session_id)
                except Exception as e:
                    # ... rest of existing code
```

**Step 2: Run existing tests to verify no regression**

Run: `docker compose run --rm web python manage.py test apps.turns -v 2`
Expected: PASS

**Step 3: Commit**

```bash
git add apps/turns/ws_consumer.py
git commit -m "feat(turns): add intro check to trigger loop"
```

---

## Task 12: Add Export to turns/services.py __all__

**Files:**
- Modify: `apps/turns/services.py` (add TURN_STATE_AI_INTRODUCING to exports if needed)

**Step 1: Verify exports work correctly**

Run: `docker compose run --rm web python -c "from apps.turns.services import TURN_STATE_AI_INTRODUCING; print(TURN_STATE_AI_INTRODUCING)"`
Expected: Output "AI_INTRODUCING"

**Step 2: Commit (if changes needed)**

```bash
git add apps/turns/services.py
git commit -m "chore(turns): ensure AI_INTRODUCING is exported"
```

---

## Task 13: Run All Tests

**Files:** None (verification only)

**Step 1: Run all tests**

Run: `docker compose run --rm web python manage.py test apps.moderation apps.turns apps.sessions -v 2`
Expected: All tests PASS

**Step 2: Verify test count**

Ensure new tests are included in the test run.

---

## Task 14: Update Moderation Documentation

**Files:**
- Modify: `docs/documentazione_moderazione.md`

**Step 1: Add intro message section to documentation**

Add a new section documenting the intro message feature:

```markdown
## Messaggio Introduttivo del Moderatore

Quando una sessione passa da LOBBY ad ACTIVE, il moderatore AI pronuncia automaticamente un messaggio di benvenuto che spiega come usare l'applicativo.

### Stato AI_INTRODUCING

Durante l'introduzione, lo stato dei turni è `AI_INTRODUCING`:
- Blocca `request_speak` (ritorna errore `INTRO_IN_PROGRESS`)
- Blocca `request_reserve` (ritorna errore `INTRO_IN_PROGRESS`)
- Considerato "qualcuno sta parlando" per i trigger temporali
- Transiziona a `IDLE` solo quando il TTS finisce

### Flusso

1. `SessionStartView.post()` imposta lo stato turni a `AI_INTRODUCING` e marca l'intro come pendente
2. Il trigger loop (ogni 5s) rileva l'intro pendente
3. Dopo un delay di ~2.5s, viene generato e pronunciato il messaggio intro via TTS
4. Al termine del TTS, lo stato transiziona a `IDLE` e i partecipanti possono interagire

### Messaggio Template

Il messaggio include i nomi dei partecipanti e le istruzioni per:
- Usare il pulsante microfono per parlare
- Prenotarsi se qualcuno sta già parlando
- Usare "Pronto alla conclusione" quando pronti

### Gestione Errori

- Se il TTS fallisce, il messaggio viene inviato come testo via WebSocket
- Il flag `intro_pending` ha un TTL di 300 secondi come sicurezza
```

**Step 2: Commit**

```bash
git add docs/documentazione_moderazione.md
git commit -m "docs(moderation): add intro message documentation"
```

---

## Task 15: Manual End-to-End Test

**Files:** None (manual verification)

**Step 1: Start the server**

Run: `make up-detached`

**Step 2: Create a test session with 3 participants**

Use the frontend or API to:
1. Create a new session
2. Have 3 users join
3. Start the session

**Step 3: Verify intro behavior**

1. Verify that the intro starts after ~2.5 seconds
2. Verify that buttons are blocked during intro (frontend shows disabled)
3. Verify that participant names are pronounced correctly
4. Verify that after intro ends, users can interact normally

**Step 4: Check logs**

Run: `make logs | grep INTRO`

Look for:
- `[INTRO_MESSAGE][START]`
- `[INTRO_MESSAGE][TTS_DONE]`
- `[INTRO_MESSAGE][END]`

---

## Checklist

- [x] Task 1: Create intro.py with template and format_participant_names
- [x] Task 2: Add Redis flag functions (set/clear/has_intro_pending)
- [x] Task 3: Add generate_intro_message function
- [x] Task 4: Add TURN_STATE_AI_INTRODUCING constant and set_introducing method
- [x] Task 5: Add end_introducing method
- [x] Task 6: Block request_speak during AI_INTRODUCING
- [x] Task 7: Block request_reserve during AI_INTRODUCING
- [x] Task 8: Add AI_INTRODUCING to _someone_is_currently_speaking
- [x] Task 9: Modify SessionStartView to initialize AI_INTRODUCING
- [x] Task 10: Add _execute_intro_message method to TurnsConsumer
- [x] Task 11: Add intro check to trigger loop
- [x] Task 12: Verify exports
- [x] Task 13: Run all tests
- [x] Task 14: Update moderation documentation
- [ ] Task 15: Manual end-to-end test
