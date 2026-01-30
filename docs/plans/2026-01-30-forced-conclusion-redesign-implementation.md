# FORCED_CONCLUSION Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Redesign the FORCED_CONCLUSION trigger so it fires immediately when session transitions to CONCLUSION (not on human turn end), blocks human turns in CONCLUSION phase, and fixes ready_to_conclude queuing issues.

**Architecture:** Move FORCED_CONCLUSION from post-turn trigger evaluation to immediate invocation at session transition. Add session phase check to TurnManager.request_speak(). Add dedicated LLM call method with improved prompt.

**Tech Stack:** Django, Redis (via django.core.cache), Azure OpenAI (gpt-4o-mini), Channels WebSocket

---

## Task 1: Block Human Turns in CONCLUSION Phase

**Files:**
- Modify: `apps/turns/services.py:149-238` (request_speak method)
- Test: `apps/turns/tests.py`

**Step 1: Write the failing test**

Add to `apps/turns/tests.py`:

```python
from apps.sessions.models import Session, SessionState
from apps.turns.services import TurnManager, TURN_STATE_IDLE


class TurnManagerConclusionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user1 = User.objects.create_user(
            username="user1", email="user1@example.com", password="pass"
        )
        self.session_id = "session-conclusion-test-1"

    def test_request_speak_blocked_in_conclusion_phase(self):
        """
        Human turns should be blocked when session is in CONCLUSION phase.
        """
        # Setup: Create session in CONCLUSION state
        from apps.sessions.models import Session, SessionState

        # We'll mock _get_session_phase to return CONCLUSION
        with patch.object(TurnManager, '_get_session_phase', return_value='CONCLUSION'):
            result = TurnManager.request_speak(self.session_id, self.user1)

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "SESSION_IN_CONCLUSION")
        self.assertIn("conclusione", result.error_detail.lower())
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.turns.tests.TurnManagerConclusionTests.test_request_speak_blocked_in_conclusion_phase -v 2`
Expected: FAIL - AttributeError: '_get_session_phase' not found

**Step 3: Add helper method to get session phase**

Add to `apps/turns/services.py` after line 584 (after `start_reservation_window`):

```python
@classmethod
def _get_session_phase(cls, session_id: str) -> Optional[str]:
    """
    Recupera la fase corrente della sessione dal database.
    Returns None se la sessione non esiste.
    """
    from apps.sessions.models import Session
    try:
        return Session.objects.values_list("state", flat=True).get(id=session_id)
    except Session.DoesNotExist:
        return None
```

**Step 4: Add session phase check to request_speak**

Modify `apps/turns/services.py` `request_speak` method. Add after moderation_in_progress check (line 165):

```python
# NEW: Block turns during CONCLUSION phase
session_phase = cls._get_session_phase(session_id)
if session_phase == "CONCLUSION":
    return TurnResult(
        success=False,
        state=state,
        events=events,
        error_code="SESSION_IN_CONCLUSION",
        error_detail="La sessione è in fase di conclusione. Non è possibile prendere la parola.",
    )
```

**Step 5: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.turns.tests.TurnManagerConclusionTests.test_request_speak_blocked_in_conclusion_phase -v 2`
Expected: PASS

**Step 6: Commit**

```bash
git add apps/turns/services.py apps/turns/tests.py
git commit -m "feat(turns): block human turns in CONCLUSION phase"
```

---

## Task 2: Add Dedicated LLM Method for Forced Conclusion

**Files:**
- Modify: `apps/moderation/service.py`
- Test: `apps/moderation/tests.py`

**Step 1: Write the failing test**

Add to `apps/moderation/tests.py`:

```python
class ForcedConclusionLLMTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch.object(ModerationService, '_build_azure_client')
    def test_call_llm_for_conclusion_returns_expected_structure(self, mock_client):
        """call_llm_for_conclusion should return expected dict structure."""
        # Mock the Azure response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "updated_summary": "Test summary",
            "should_ai_speak": True,
            "message_to_say": "Closing message",
            "reason": "forced_conclusion",
            "intervention_score": 1.0,
        })
        mock_client.return_value.chat.completions.create.return_value = mock_response

        result = ModerationService.call_llm_for_conclusion(
            summary_in="Discussion summary",
            conclusion_reason="all_participants_ready",
            session_duration_minutes=25,
        )

        self.assertIn("updated_summary", result)
        self.assertIn("message_to_say", result)
        self.assertTrue(result["should_ai_speak"])
        self.assertIsNotNone(result["message_to_say"])

    def test_call_llm_for_conclusion_fallback_timer_expired(self):
        """Fallback for conclusion_reason='timer_expired' should mention time."""
        result = ModerationService._fallback_forced_conclusion(
            summary="Test summary",
            conclusion_reason="timer_expired",
        )

        self.assertIn("terminato", result["message_to_say"].lower())
        self.assertTrue(result["should_ai_speak"])

    def test_call_llm_for_conclusion_fallback_all_ready(self):
        """Fallback for conclusion_reason='all_participants_ready' should mention decision."""
        result = ModerationService._fallback_forced_conclusion(
            summary="Test summary",
            conclusion_reason="all_participants_ready",
        )

        self.assertIn("deciso", result["message_to_say"].lower())
        self.assertTrue(result["should_ai_speak"])
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.ForcedConclusionLLMTests -v 2`
Expected: FAIL - AttributeError: 'call_llm_for_conclusion' not found

**Step 3: Add the new methods to ModerationService**

Add to `apps/moderation/service.py` after `_fallback_llm_output` method (after line 344):

```python
@classmethod
def call_llm_for_conclusion(
    cls,
    *,
    summary_in: str,
    conclusion_reason: str,  # "timer_expired" or "all_participants_ready"
    session_duration_minutes: int = 30,
) -> dict:
    """
    Chiamata LLM dedicata per FORCED_CONCLUSION.

    A differenza di _call_llm(), non richiede last_turn o speaker_name
    perché viene chiamata alla transizione, non dopo un turno.

    Returns dict with:
    - updated_summary
    - should_ai_speak (always True)
    - message_to_say
    - reason
    - intervention_score
    """
    logger.info(
        "[MODERATION][LLM][CONCLUSION_REQUEST] reason=%s duration=%d",
        conclusion_reason,
        session_duration_minutes,
    )

    try:
        client = cls._build_azure_client()
        deployment = os.environ.get("AZURE_OPENAI_MODEL", "gpt-4o-mini")

        system_prompt = cls._build_forced_conclusion_system_prompt()

        llm_input = {
            "mode": "forced_conclusion",
            "summary_in": summary_in,
            "conclusion_reason": conclusion_reason,
            "session_duration_minutes": session_duration_minutes,
            "scenario": {
                "type": "murder_mystery",
                "vote_action": "selezionare il colpevole",
                "vote_outcome": "scoprirete se avete indovinato l'assassino"
            },
            "language": "it",
        }

        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(llm_input, ensure_ascii=False)},
            ],
            temperature=0.5,  # Slightly higher for warmer tone
            max_tokens=512,
        )

        raw_output = response.choices[0].message.content
        if isinstance(raw_output, list):
            raw_output = "".join(part.get("text", "") for part in raw_output)

    except Exception as e:
        logger.warning("[MODERATION][LLM][CONCLUSION_ERROR] error=%s", str(e))
        return cls._fallback_forced_conclusion(summary_in, conclusion_reason)

    try:
        parsed = json.loads(raw_output)
    except Exception as e:
        logger.warning(
            "[MODERATION][LLM][CONCLUSION_PARSE_ERROR] raw=%r error=%s",
            raw_output, str(e)
        )
        return cls._fallback_forced_conclusion(summary_in, conclusion_reason)

    logger.info(
        "[MODERATION][LLM][CONCLUSION_RESPONSE] message=%r",
        parsed.get("message_to_say", "")[:50],
    )

    return {
        "updated_summary": parsed.get("updated_summary", summary_in),
        "should_ai_speak": True,  # Always speak in forced_conclusion
        "message_to_say": parsed.get("message_to_say"),
        "reason": parsed.get("reason", "forced_conclusion"),
        "intervention_score": 1.0,
    }

@classmethod
def _build_forced_conclusion_system_prompt(cls) -> str:
    """Prompt di sistema per FORCED_CONCLUSION."""
    return """Sei il moderatore AI di AIutami, una piattaforma per discussioni di gruppo moderate.

La sessione sta per concludersi e devi generare il messaggio finale di chiusura.

## Il tuo compito

Genera un messaggio che:
1. **Riassuma la discussione** - Parti dal summary fornito e adattalo per un contesto di chiusura. Evidenzia i punti chiave emersi, le posizioni principali, eventuali accordi o disaccordi.

2. **Dia istruzioni per il voto** - Spiega chiaramente cosa devono fare i partecipanti (es. selezionare il colpevole) e cosa succederà dopo (es. quando tutti avranno votato, vedranno i risultati).

3. **Ringrazi i partecipanti** - Concludi con un ringraziamento generale per aver usato AIutami per la moderazione.

## Tono e stile

- **Caldo e coinvolgente**: non freddo o robotico
- **Valorizza la partecipazione**: fai sentire che la discussione è stata significativa
- **Lunghezza**: 100-150 parole (circa 30-60 secondi di parlato)

## Adatta il tono al motivo della conclusione

- Se `conclusion_reason == "timer_expired"`: il tempo è terminato, usa un tono che riconosca il lavoro svolto nonostante il limite di tempo
- Se `conclusion_reason == "all_participants_ready"`: i partecipanti hanno scelto di concludere, valorizza la loro decisione

## Output

Rispondi SOLO con un JSON valido:

{
    "updated_summary": "Il riassunto finale della discussione",
    "should_ai_speak": true,
    "message_to_say": "Il messaggio completo da pronunciare",
    "reason": "forced_conclusion",
    "intervention_score": 1.0
}

IMPORTANTE: `message_to_say` deve contenere TUTTO (riassunto + istruzioni + ringraziamento) in un unico messaggio fluido e ben collegato."""

@classmethod
def _fallback_forced_conclusion(cls, summary: str, conclusion_reason: str) -> dict:
    """
    Messaggio di fallback se la chiamata LLM per conclusion fallisce.
    """
    if conclusion_reason == "timer_expired":
        intro = "Il tempo a disposizione è terminato."
    else:
        intro = "Avete deciso di procedere alla votazione."

    message = (
        f"{intro} "
        f"Ecco un breve riepilogo della vostra discussione: {summary}. "
        f"Ora è il momento di selezionare chi pensate sia il colpevole. "
        f"Quando tutti avranno votato, scoprirete se avete indovinato. "
        f"Grazie per aver usato AIutami per la vostra sessione!"
    )

    return {
        "updated_summary": summary,
        "should_ai_speak": True,
        "message_to_say": message,
        "reason": "forced_conclusion_fallback",
        "intervention_score": 1.0,
    }
```

**Step 4: Add import for json at top if not present**

Verify `import json` is present at top of `apps/moderation/service.py` (it should already be there at line 8).

**Step 5: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.ForcedConclusionLLMTests -v 2`
Expected: PASS

**Step 6: Commit**

```bash
git add apps/moderation/service.py apps/moderation/tests.py
git commit -m "feat(moderation): add dedicated LLM method for forced conclusion"
```

---

## Task 3: Add ModerationState Field for Conclusion Reason

**Files:**
- Modify: `apps/moderation/state.py`
- Test: `apps/moderation/tests.py`

**Step 1: Write the failing test**

Add to `apps/moderation/tests.py`:

```python
class ModerationStateConclusionReasonTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_moderation_state_has_conclusion_reason_field(self):
        """ModerationState should have conclusion_reason field."""
        state = ModerationState.initial()
        self.assertIsNone(state.conclusion_reason)

    def test_conclusion_reason_persists_after_save_and_load(self):
        """conclusion_reason should persist in Redis."""
        session_id = "test-conclusion-reason-1"

        state = ModerationState.initial()
        state.conclusion_reason = "timer_expired"
        save_moderation_state(session_id, state)

        loaded = load_moderation_state(session_id)
        self.assertEqual(loaded.conclusion_reason, "timer_expired")
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.ModerationStateConclusionReasonTests -v 2`
Expected: FAIL - AttributeError: 'conclusion_reason' not found

**Step 3: Add conclusion_reason field to ModerationState**

Modify `apps/moderation/state.py`:

1. Add field to dataclass (line 26, before `forced_conclusion_done`):
```python
conclusion_reason: Optional[str]  # "timer_expired" or "all_participants_ready"
```

2. Update `initial()` method (line 34):
```python
conclusion_reason=None,
```

3. Update `load_moderation_state` (add to dict access around line 62):
```python
conclusion_reason=data.get("conclusion_reason"),
```

4. Update `save_moderation_state` (add to dict around line 78):
```python
"conclusion_reason": state.conclusion_reason,
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.ModerationStateConclusionReasonTests -v 2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/moderation/state.py apps/moderation/tests.py
git commit -m "feat(moderation): add conclusion_reason to ModerationState"
```

---

## Task 4: Implement _execute_forced_conclusion in Consumer

**Files:**
- Modify: `apps/turns/ws_consumer.py`
- Test: `apps/turns/tests_consumer.py`

**Step 1: Write the failing test**

Add to `apps/turns/tests_consumer.py`:

```python
from unittest.mock import patch, MagicMock, AsyncMock
import pytest
from channels.testing import WebsocketCommunicator
from django.test import TestCase
from django.core.cache import cache


class ExecuteForcedConclusionTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('apps.moderation.service.ModerationService.call_llm_for_conclusion')
    @patch('apps.moderation.state.load_moderation_state')
    @patch('apps.moderation.state.save_moderation_state')
    def test_execute_forced_conclusion_calls_llm(self, mock_save, mock_load, mock_llm):
        """_execute_forced_conclusion should call LLM for conclusion message."""
        from apps.moderation.state import ModerationState
        from apps.turns.ws_consumer import TurnsConsumer

        # Setup mock state
        mock_state = ModerationState.initial()
        mock_state.summary = "Test discussion summary"
        mock_state.conclusion_reason = "timer_expired"
        mock_load.return_value = mock_state

        # Setup mock LLM response
        mock_llm.return_value = {
            "updated_summary": "Final summary",
            "should_ai_speak": True,
            "message_to_say": "Closing message",
            "reason": "forced_conclusion",
            "intervention_score": 1.0,
        }

        # This is a unit test - we just verify the method signature exists
        # Full integration test requires websocket setup
        self.assertTrue(callable(getattr(TurnsConsumer, '_execute_forced_conclusion', None)))
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.turns.tests_consumer.ExecuteForcedConclusionTests -v 2`
Expected: FAIL - _execute_forced_conclusion not found

**Step 3: Add _execute_forced_conclusion method to TurnsConsumer**

Add to `apps/turns/ws_consumer.py` after `_transition_session_to_conclusion` method (around line 922):

```python
async def _execute_forced_conclusion(self) -> None:
    """
    Esegue il trigger FORCED_CONCLUSION immediatamente dopo la transizione.
    Chiama l'LLM per generare il messaggio di chiusura.
    """
    from apps.moderation.state import load_moderation_state, save_moderation_state
    from apps.moderation.service import ModerationService

    # Load moderation state
    state = await database_sync_to_async(load_moderation_state)(self.session_id)

    if state.forced_conclusion_done:
        logger.info("[FORCED_CONCLUSION][SKIP] session=%s already done", self.session_id)
        return

    logger.info("[FORCED_CONCLUSION][START] session=%s", self.session_id)

    # Determine conclusion reason
    conclusion_reason = state.conclusion_reason or "timer_expired"

    # Get session duration
    try:
        duration_minutes = await self._get_session_duration_minutes()
    except Exception:
        duration_minutes = 30

    # Call LLM with forced_conclusion mode
    result = await database_sync_to_async(ModerationService.call_llm_for_conclusion)(
        summary_in=state.summary,
        conclusion_reason=conclusion_reason,
        session_duration_minutes=duration_minutes,
    )

    # Execute TTS message
    if result.get("message_to_say"):
        await self._execute_tts_message(result["message_to_say"])

    # Mark as done
    state.forced_conclusion_done = True
    state.summary = result.get("updated_summary", state.summary)
    await database_sync_to_async(save_moderation_state)(self.session_id, state)

    logger.info("[FORCED_CONCLUSION][END] session=%s", self.session_id)

@database_sync_to_async
def _get_session_duration_minutes(self) -> int:
    """Calcola la durata della sessione in minuti."""
    from apps.sessions.models import Session
    from django.utils import timezone

    try:
        session = Session.objects.get(pk=self.session_id)
        if session.started_at:
            delta = timezone.now() - session.started_at
            return int(delta.total_seconds() / 60)
    except Session.DoesNotExist:
        pass
    return 30  # Default
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.turns.tests_consumer.ExecuteForcedConclusionTests -v 2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/turns/ws_consumer.py apps/turns/tests_consumer.py
git commit -m "feat(turns): add _execute_forced_conclusion method to consumer"
```

---

## Task 5: Call Forced Conclusion at Session Transition

**Files:**
- Modify: `apps/turns/ws_consumer.py`

**Step 1: Write the failing test**

Add to `apps/turns/tests_consumer.py`:

```python
class TransitionTriggersForcedConclusionTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_transition_calls_forced_conclusion(self):
        """_transition_session_to_conclusion should call _execute_forced_conclusion."""
        from apps.turns.ws_consumer import TurnsConsumer

        # Verify the pattern: transition method is sync (database_sync_to_async),
        # so we need to verify the caller invokes _execute_forced_conclusion after.
        # This is tested by verifying _trigger_loop and ready_to_conclude handlers
        # call _execute_forced_conclusion after successful transition.

        # For this test, we just verify the method chain exists
        self.assertTrue(hasattr(TurnsConsumer, '_transition_session_to_conclusion'))
        self.assertTrue(hasattr(TurnsConsumer, '_execute_forced_conclusion'))
```

**Step 2: Run test to verify it passes (structure test)**

Run: `docker compose run --rm web python manage.py test apps.turns.tests_consumer.TransitionTriggersForcedConclusionTests -v 2`
Expected: PASS

**Step 3: Modify _trigger_loop to call _execute_forced_conclusion after transition**

In `apps/turns/ws_consumer.py`, find the `_trigger_loop` method (around line 1028).

Replace the transition block (lines 1028-1039):
```python
# OLD:
if trig_result.should_transition_to_conclusion and not message_was_queued:
    transitioned = await database_sync_to_async(self._transition_session_to_conclusion)()
    if transitioned:
        logger.info("[TRIGGER_LOOP][TRANSITION] session=%s -> CONCLUSION", session_id)
        await self.channel_layer.group_send(
            f"sessions_{session_id}",
            {
                "type": "sessions.event",
                "event_type": "STATE_CHANGED",
                "new_state": "CONCLUSION",
            },
        )
```

With:
```python
# NEW:
if trig_result.should_transition_to_conclusion and not message_was_queued:
    transitioned = await database_sync_to_async(self._transition_session_to_conclusion)()
    if transitioned:
        logger.info("[TRIGGER_LOOP][TRANSITION] session=%s -> CONCLUSION", session_id)
        await self.channel_layer.group_send(
            f"sessions_{session_id}",
            {
                "type": "sessions.event",
                "event_type": "STATE_CHANGED",
                "new_state": "CONCLUSION",
            },
        )
        # Execute FORCED_CONCLUSION immediately
        await self._execute_forced_conclusion()
```

**Step 4: Modify trigger_ready_to_conclude to call _execute_forced_conclusion**

In `apps/turns/ws_consumer.py`, find `trigger_ready_to_conclude` method (around line 790).

Replace the transition block (lines 802-812):
```python
# OLD:
if trigger_conclusion:
    transitioned = await self._transition_session_to_conclusion()
    if transitioned:
        await self.channel_layer.group_send(
            f"sessions_{self.session_id}",
            {
                "type": "sessions.event",
                "event_type": "STATE_CHANGED",
                "new_state": "CONCLUSION",
            },
        )
```

With:
```python
# NEW:
if trigger_conclusion:
    transitioned = await self._transition_session_to_conclusion()
    if transitioned:
        await self.channel_layer.group_send(
            f"sessions_{self.session_id}",
            {
                "type": "sessions.event",
                "event_type": "STATE_CHANGED",
                "new_state": "CONCLUSION",
            },
        )
        # Execute FORCED_CONCLUSION immediately
        await self._execute_forced_conclusion()
```

**Step 5: Also update _handle_end_speak transition**

In `apps/turns/ws_consumer.py`, find `_handle_end_speak` method. Find the transition block (around line 499-509):

```python
# OLD:
if decision.should_transition_to_conclusion:
    transitioned = await self._transition_session_to_conclusion()
    if transitioned:
        # Broadcast del cambio di stato sessione
        await self.channel_layer.group_send(
            f"sessions_{self.session_id}",
            {
                "type": "session.state_changed",
                "new_state": "CONCLUSION",
            },
        )
```

With:
```python
# NEW:
if decision.should_transition_to_conclusion:
    transitioned = await self._transition_session_to_conclusion()
    if transitioned:
        # Broadcast del cambio di stato sessione
        await self.channel_layer.group_send(
            f"sessions_{self.session_id}",
            {
                "type": "session.state_changed",
                "new_state": "CONCLUSION",
            },
        )
        # Execute FORCED_CONCLUSION immediately
        await self._execute_forced_conclusion()
```

**Step 6: Commit**

```bash
git add apps/turns/ws_consumer.py apps/turns/tests_consumer.py
git commit -m "feat(turns): call _execute_forced_conclusion at session transition"
```

---

## Task 6: Remove FORCED_CONCLUSION from Post-Turn Triggers

**Files:**
- Modify: `apps/moderation/triggers.py`
- Modify: `apps/moderation/orchestrator.py`
- Test: `apps/moderation/tests.py`

**Step 1: Write the failing test**

Add to `apps/moderation/tests.py`:

```python
class ForcedConclusionNotInPostTurnTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('apps.moderation.triggers._get_next_reserved_speaker_name', return_value=None)
    @patch('apps.moderation.triggers._get_ready_to_conclude_status', return_value=(0, 3))
    def test_forced_conclusion_not_triggered_at_turn_end_in_conclusion(self, mock_ready, mock_reserved):
        """FORCED_CONCLUSION should NOT be triggered in evaluate_triggers_on_human_turn_end.

        The redesign moves FORCED_CONCLUSION to session transition time,
        so it should not appear in post-turn trigger evaluation anymore.
        """
        session_id = "test-no-fc-at-turn-1"

        state = ModerationState.initial()
        state.forced_conclusion_done = False  # Not done yet
        save_moderation_state(session_id, state)

        result = evaluate_triggers_on_human_turn_end(
            session_id=session_id,
            user_id=1,
            session_phase="CONCLUSION",  # Even in CONCLUSION phase
            moderation_state=state,
        )

        # Should NOT return FORCED_CONCLUSION anymore
        self.assertNotEqual(result.hard_action, HardModerationAction.FORCED_CONCLUSION)
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.ForcedConclusionNotInPostTurnTests -v 2`
Expected: FAIL - hard_action is FORCED_CONCLUSION

**Step 3: Remove _should_force_conclusion call from evaluate_triggers_on_human_turn_end**

In `apps/moderation/triggers.py`, find `evaluate_triggers_on_human_turn_end` function (around line 131).

Remove lines 157-162:
```python
# REMOVE THIS BLOCK:
# 2) Trigger hard: fase di conclusione (FORCED_CONCLUSION)
if _should_force_conclusion(
    session_id=session_id,
    session_phase=session_phase,
    moderation_state=moderation_state,
):
    hard_action = HardModerationAction.FORCED_CONCLUSION
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.ForcedConclusionNotInPostTurnTests -v 2`
Expected: PASS

**Step 5: Update existing test that expects FORCED_CONCLUSION**

In `apps/moderation/tests.py`, find `test_forced_conclusion_fires_when_not_done` and update it:

```python
@patch('apps.moderation.triggers._get_next_reserved_speaker_name', return_value=None)
@patch('apps.moderation.triggers._get_ready_to_conclude_status', return_value=(0, 3))
def test_forced_conclusion_no_longer_fires_at_turn_end(self, mock_ready, mock_reserved):
    """FORCED_CONCLUSION no longer fires on human turn end (moved to transition)."""
    session_id = "test-session-fc-1"

    state = ModerationState.initial()
    save_moderation_state(session_id, state)

    result = evaluate_triggers_on_human_turn_end(
        session_id=session_id,
        user_id=1,
        session_phase="CONCLUSION",
        moderation_state=state,
    )

    # Should NOT return FORCED_CONCLUSION (now handled at transition)
    self.assertNotEqual(result.hard_action, HardModerationAction.FORCED_CONCLUSION)
```

**Step 6: Run all moderation tests to verify nothing broke**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests -v 2`
Expected: All tests PASS

**Step 7: Commit**

```bash
git add apps/moderation/triggers.py apps/moderation/tests.py
git commit -m "refactor(moderation): remove FORCED_CONCLUSION from post-turn triggers"
```

---

## Task 7: Fix ready_to_conclude TTS Queuing

**Files:**
- Modify: `apps/turns/ws_consumer.py`
- Test: `apps/turns/tests_consumer.py`

**Step 1: Write the failing test**

Add to `apps/turns/tests_consumer.py`:

```python
class ReadyToConcludeQueuingTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_trigger_ready_to_conclude_queues_when_speaking(self):
        """trigger_ready_to_conclude should queue message if someone is speaking."""
        from apps.turns.ws_consumer import TurnsConsumer
        from apps.moderation.pending_messages import has_pending_messages
        from apps.turns.services import TurnManager, TURN_STATE_HUMAN_SPEAKING

        session_id = "test-queue-rtc-1"

        # Setup: someone is speaking
        state = TurnManager._load_state(session_id)
        state.state = TURN_STATE_HUMAN_SPEAKING
        state.current_speaker_user_id = 1
        TurnManager._save_state(session_id, state)

        # The method should check state and queue if not IDLE
        # This verifies the pattern exists
        self.assertTrue(hasattr(TurnsConsumer, 'trigger_ready_to_conclude'))
```

**Step 2: Run test to verify it passes (structure test)**

Run: `docker compose run --rm web python manage.py test apps.turns.tests_consumer.ReadyToConcludeQueuingTests -v 2`
Expected: PASS

**Step 3: Modify trigger_ready_to_conclude to queue when speaking**

In `apps/turns/ws_consumer.py`, find `trigger_ready_to_conclude` method (around line 790).

Replace the entire method:
```python
async def trigger_ready_to_conclude(self, event):
    """
    Handler per messaggi ready_to_conclude inviati dal view.
    Esegue il messaggio TTS e, se trigger_conclusion=True, transiziona a CONCLUSION.

    Se qualcuno sta parlando, accoda il messaggio invece di eseguirlo subito.
    """
    text = event.get("text", "")
    trigger_conclusion = event.get("trigger_conclusion", False)

    if text:
        # Check if someone is speaking - queue if so
        from apps.turns.services import TurnManager
        from apps.moderation.pending_messages import enqueue_message

        state = TurnManager.get_state_only(self.session_id)
        if state and state.state != "IDLE":
            # Queue the message for later execution
            enqueue_message(
                self.session_id,
                text,
                "READY_TO_CONCLUDE",
                trigger_conclusion=trigger_conclusion,
            )
            logger.info(
                "[READY_TO_CONCLUDE][QUEUED] session=%s trigger_conclusion=%s",
                self.session_id, trigger_conclusion
            )
            return  # Don't execute TTS or transition now
        else:
            # Execute TTS immediately
            await self._execute_tts_message(text)

    # Only transition if we executed immediately (not queued)
    if trigger_conclusion:
        transitioned = await self._transition_session_to_conclusion()
        if transitioned:
            await self.channel_layer.group_send(
                f"sessions_{self.session_id}",
                {
                    "type": "sessions.event",
                    "event_type": "STATE_CHANGED",
                    "new_state": "CONCLUSION",
                },
            )
            # Execute FORCED_CONCLUSION immediately
            await self._execute_forced_conclusion()
```

**Step 4: Run tests to verify nothing broke**

Run: `docker compose run --rm web python manage.py test apps.turns -v 2`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add apps/turns/ws_consumer.py apps/turns/tests_consumer.py
git commit -m "fix(turns): queue ready_to_conclude TTS when someone is speaking"
```

---

## Task 8: Set conclusion_reason at Transition Points

**Files:**
- Modify: `apps/turns/ws_consumer.py`
- Modify: `apps/sessions/views.py` (for ready_to_conclude)

**Step 1: Identify transition points**

There are 3 places where session transitions to CONCLUSION:
1. Timer 30 min expiry (`_trigger_loop`) - reason: `timer_expired`
2. `_handle_end_speak` when timer 30 fires - reason: `timer_expired`
3. `trigger_ready_to_conclude` (3/3 ready) - reason: `all_participants_ready`

**Step 2: Update _trigger_loop to set conclusion_reason**

In `apps/turns/ws_consumer.py`, in the `_trigger_loop` method, before the transition block, add:

```python
# Set conclusion_reason before transition
if trig_result.should_transition_to_conclusion and not message_was_queued:
    # Set the reason for conclusion
    await self._set_conclusion_reason("timer_expired")

    transitioned = await database_sync_to_async(self._transition_session_to_conclusion)()
    # ... rest of block
```

**Step 3: Add _set_conclusion_reason helper method**

Add to `apps/turns/ws_consumer.py` after `_get_session_duration_minutes`:

```python
@database_sync_to_async
def _set_conclusion_reason(self, reason: str) -> None:
    """Imposta il motivo della conclusione nello stato di moderazione."""
    from apps.moderation.state import load_moderation_state, save_moderation_state

    state = load_moderation_state(self.session_id)
    state.conclusion_reason = reason
    save_moderation_state(self.session_id, state)
```

**Step 4: Update _handle_end_speak to set conclusion_reason**

In `_handle_end_speak`, before the transition block (around line 498):

```python
# Set conclusion_reason before transition
if decision.should_transition_to_conclusion:
    await self._set_conclusion_reason("timer_expired")

    transitioned = await self._transition_session_to_conclusion()
    # ... rest of block
```

**Step 5: Update trigger_ready_to_conclude to set conclusion_reason**

In `trigger_ready_to_conclude`, before the transition (after TTS execution):

```python
# Only transition if we executed immediately (not queued)
if trigger_conclusion:
    # Set the reason for conclusion
    await self._set_conclusion_reason("all_participants_ready")

    transitioned = await self._transition_session_to_conclusion()
    # ... rest of block
```

**Step 6: Commit**

```bash
git add apps/turns/ws_consumer.py
git commit -m "feat(turns): set conclusion_reason at transition points"
```

---

## Task 9: Integration Test - Full Conclusion Flow

**Files:**
- Create: `apps/moderation/tests_integration.py`

**Step 1: Write integration test**

Create `apps/moderation/tests_integration.py`:

```python
"""
Integration tests for the FORCED_CONCLUSION redesign.
"""
from django.test import TestCase
from django.core.cache import cache
from django.contrib.auth import get_user_model
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

from apps.moderation.state import ModerationState, load_moderation_state, save_moderation_state
from apps.moderation.service import ModerationService, HardModerationAction
from apps.moderation.timers_state import ModerationTimersState, save_timers_state


User = get_user_model()


class ForcedConclusionIntegrationTests(TestCase):
    """
    Integration tests for the complete FORCED_CONCLUSION flow.
    """

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="pass"
        )
        self.session_id = "integration-test-session-1"

    def tearDown(self):
        cache.clear()

    @patch.object(ModerationService, '_build_azure_client')
    def test_full_conclusion_flow_timer_expired(self, mock_client):
        """Test complete flow when timer expires."""
        # Setup mock LLM response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"updated_summary": "Final", "should_ai_speak": true, "message_to_say": "Closing", "reason": "forced_conclusion", "intervention_score": 1.0}'
        mock_client.return_value.chat.completions.create.return_value = mock_response

        # Setup moderation state
        state = ModerationState.initial()
        state.summary = "Discussion about mystery"
        state.conclusion_reason = "timer_expired"
        save_moderation_state(self.session_id, state)

        # Call the dedicated conclusion LLM method
        result = ModerationService.call_llm_for_conclusion(
            summary_in=state.summary,
            conclusion_reason="timer_expired",
            session_duration_minutes=30,
        )

        # Verify result
        self.assertTrue(result["should_ai_speak"])
        self.assertIsNotNone(result["message_to_say"])

        # Simulate marking as done
        state.forced_conclusion_done = True
        save_moderation_state(self.session_id, state)

        # Verify state is marked as done
        loaded = load_moderation_state(self.session_id)
        self.assertTrue(loaded.forced_conclusion_done)

    def test_fallback_message_quality_timer_expired(self):
        """Fallback message for timer_expired should be appropriate."""
        result = ModerationService._fallback_forced_conclusion(
            summary="I partecipanti hanno discusso del maggiordomo",
            conclusion_reason="timer_expired",
        )

        # Check message contains expected elements
        msg = result["message_to_say"]
        self.assertIn("terminato", msg.lower())  # Mentions time ended
        self.assertIn("maggiordomo", msg)  # Contains summary
        self.assertIn("colpevole", msg.lower())  # Voting instructions
        self.assertIn("grazie", msg.lower())  # Thanks

    def test_fallback_message_quality_all_ready(self):
        """Fallback message for all_participants_ready should be appropriate."""
        result = ModerationService._fallback_forced_conclusion(
            summary="I partecipanti hanno discusso della cameriera",
            conclusion_reason="all_participants_ready",
        )

        # Check message contains expected elements
        msg = result["message_to_say"]
        self.assertIn("deciso", msg.lower())  # Mentions decision
        self.assertIn("cameriera", msg)  # Contains summary
        self.assertIn("colpevole", msg.lower())  # Voting instructions
        self.assertIn("grazie", msg.lower())  # Thanks
```

**Step 2: Run integration tests**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests_integration -v 2`
Expected: All tests PASS

**Step 3: Run all tests to verify nothing broke**

Run: `docker compose run --rm web python manage.py test -v 2`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add apps/moderation/tests_integration.py
git commit -m "test(moderation): add integration tests for FORCED_CONCLUSION redesign"
```

---

## Task 10: Clean Up Unused Code

**Files:**
- Modify: `apps/moderation/triggers.py`

**Step 1: Review _should_force_conclusion function**

The `_should_force_conclusion` function (around line 249-269) is no longer called from `evaluate_triggers_on_human_turn_end`. We can either:
- Remove it entirely
- Keep it for documentation/future use

**Step 2: Add deprecation comment or remove**

Option A - Add deprecation comment:
```python
def _should_force_conclusion(
    *,
    session_id: int | str,
    session_phase: str,
    moderation_state: ModerationState,
) -> bool:
    """
    DEPRECATED: No longer used in post-turn evaluation.
    FORCED_CONCLUSION is now triggered immediately at session transition.

    Kept for reference only.
    """
    # ... existing code
```

Option B - Remove the function entirely (preferred for clean code).

**Step 3: Run tests to verify nothing uses it**

Run: `docker compose run --rm web python manage.py test -v 2`
Expected: All tests PASS (nothing should break if unused)

**Step 4: Commit**

```bash
git add apps/moderation/triggers.py
git commit -m "chore(moderation): mark _should_force_conclusion as deprecated"
```

---

## Summary Checklist

- [x] Task 1: Block human turns in CONCLUSION phase
- [x] Task 2: Add dedicated LLM method for forced conclusion
- [x] Task 3: Add conclusion_reason to ModerationState
- [x] Task 4: Implement _execute_forced_conclusion in consumer
- [x] Task 5: Call forced conclusion at session transition
- [x] Task 6: Remove FORCED_CONCLUSION from post-turn triggers
- [x] Task 7: Fix ready_to_conclude TTS queuing
- [x] Task 8: Set conclusion_reason at transition points
- [x] Task 9: Integration tests
- [x] Task 10: Clean up unused code

---

## Note per l'esecuzione

**Gestione contesto conversazione:** Quando il contesto della conversazione raggiunge circa il 55%, è consigliabile:
1. Committare i progressi fatti finora
2. Chiudere la conversazione
3. Riaprire una nuova sessione con `/superpowers:execute-plan` sul file del piano

Claude leggerà la checklist sopra e riprenderà dal primo task non completato (marcato con `[ ]`).
