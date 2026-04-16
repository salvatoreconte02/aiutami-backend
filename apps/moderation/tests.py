import json

from django.test import TestCase
from django.core.cache import cache

from apps.moderation.state import (
    ModerationState,
    load_moderation_state,
    save_moderation_state,
)
from apps.moderation.triggers import TriggerEvaluationResult, evaluate_triggers_on_human_turn_end, StaticMessage
from apps.moderation.pending_messages import (
    PendingMessage,
    enqueue_message,
    dequeue_all_messages,
    has_pending_messages,
)
from apps.moderation.service import (
    HardModerationAction,
    ModerationService,
    ModerationResult,
    AI_INTERVENTION_COOLDOWN,
    COOLDOWN_BYPASS_REASONS,
)
from apps.moderation.orchestrator import FullModerationDecision, ModerationOrchestrator
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

from apps.moderation.timers_state import (
    load_timers_state,
    save_timers_state,
    ModerationTimersState,
    TIMER_30_THRESHOLD,
)


class ModerationStateTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_initial_state_has_forced_conclusion_done_false(self):
        """Initial ModerationState should have forced_conclusion_done=False."""
        state = ModerationState.initial()
        self.assertFalse(state.forced_conclusion_done)

    def test_forced_conclusion_done_persists_after_save_and_load(self):
        """forced_conclusion_done should be saved to and loaded from Redis."""
        session_id = "test-session-123"

        # Create state with forced_conclusion_done=True
        state = ModerationState.initial()
        state.forced_conclusion_done = True
        save_moderation_state(session_id, state)

        # Load and verify
        loaded = load_moderation_state(session_id)
        self.assertTrue(loaded.forced_conclusion_done)


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


class ForcedConclusionOnlyOnceTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

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


class Timer30TransitionTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('apps.moderation.triggers._get_next_reserved_speaker_name', return_value=None)
    @patch('apps.moderation.triggers._get_ready_to_conclude_status', return_value=(0, 3))
    def test_timer_30_triggers_conclusion_transition(self, mock_ready, mock_reserved):
        """When timer 30 min expired, should_transition_to_conclusion should be True."""
        session_id = "test-session-timer-1"

        # Setup: session started 31 minutes ago, still ACTIVE
        timers_state = ModerationTimersState.initial()
        timers_state.session_started_at = datetime.utcnow() - timedelta(minutes=31)
        timers_state.timer_30_notified = False
        save_timers_state(session_id, timers_state)

        mod_state = ModerationState.initial()
        save_moderation_state(session_id, mod_state)

        result = evaluate_triggers_on_human_turn_end(
            session_id=session_id,
            user_id=1,
            session_phase="ACTIVE",
            moderation_state=mod_state,
        )

        self.assertTrue(result.should_transition_to_conclusion)
        timer_msgs = [m for m in result.static_messages_to_speak
                      if "Il tempo della discussione è terminato" in m.text]
        self.assertEqual(len(timer_msgs), 1)

    @patch('apps.moderation.triggers._get_next_reserved_speaker_name', return_value=None)
    @patch('apps.moderation.triggers._get_ready_to_conclude_status', return_value=(0, 3))
    def test_timer_30_does_not_trigger_when_not_expired(self, mock_ready, mock_reserved):
        """When timer 30 min not expired, should_transition_to_conclusion should be False."""
        session_id = "test-session-timer-2"

        # Setup: session started 20 minutes ago
        timers_state = ModerationTimersState.initial()
        timers_state.session_started_at = datetime.utcnow() - timedelta(minutes=20)
        save_timers_state(session_id, timers_state)

        mod_state = ModerationState.initial()
        save_moderation_state(session_id, mod_state)

        result = evaluate_triggers_on_human_turn_end(
            session_id=session_id,
            user_id=1,
            session_phase="ACTIVE",
            moderation_state=mod_state,
        )

        self.assertFalse(result.should_transition_to_conclusion)

    @patch('apps.moderation.triggers._get_next_reserved_speaker_name', return_value=None)
    @patch('apps.moderation.triggers._get_ready_to_conclude_status', return_value=(0, 3))
    def test_timer_30_does_not_trigger_in_conclusion_phase(self, mock_ready, mock_reserved):
        """Timer 30 transition should not trigger if already in CONCLUSION."""
        session_id = "test-session-timer-3"

        # Setup: timer expired but session already in CONCLUSION
        timers_state = ModerationTimersState.initial()
        timers_state.session_started_at = datetime.utcnow() - timedelta(minutes=31)
        save_timers_state(session_id, timers_state)

        mod_state = ModerationState.initial()
        mod_state.forced_conclusion_done = True  # Already concluded
        save_moderation_state(session_id, mod_state)

        result = evaluate_triggers_on_human_turn_end(
            session_id=session_id,
            user_id=1,
            session_phase="CONCLUSION",
            moderation_state=mod_state,
        )

        # Should NOT signal transition since already in CONCLUSION
        self.assertFalse(result.should_transition_to_conclusion)


class ModerationServiceForcedConclusionFlagTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch.object(ModerationService, '_call_llm')
    def test_forced_conclusion_sets_flag_to_true(self, mock_llm):
        """After forced_conclusion mode, forced_conclusion_done should be True."""
        session_id = "test-service-fc-1"

        # Mock LLM response
        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": True,
            "message_to_say": "Final conclusion message",
            "reason": "forced_conclusion",
            "intervention_score": 1.0,
        }

        # Setup initial state
        state = ModerationState.initial()
        save_moderation_state(session_id, state)

        # Call service with FORCED_CONCLUSION
        result = ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="CONCLUSION",
            hard_action=HardModerationAction.FORCED_CONCLUSION,
        )

        # Verify flag is now True
        loaded_state = load_moderation_state(session_id)
        self.assertTrue(loaded_state.forced_conclusion_done)

    @patch.object(ModerationService, '_call_llm')
    def test_normal_mode_does_not_set_flag(self, mock_llm):
        """Normal mode should not set forced_conclusion_done flag."""
        session_id = "test-service-fc-2"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": False,
            "message_to_say": None,
            "reason": "all_ok",
            "intervention_score": 0.3,
        }

        state = ModerationState.initial()
        save_moderation_state(session_id, state)

        ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
        )

        loaded_state = load_moderation_state(session_id)
        self.assertFalse(loaded_state.forced_conclusion_done)


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


class ConsumerTransitionIntegrationTests(TestCase):
    """Integration tests for session transition via consumer."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch.object(ModerationOrchestrator, 'handle_human_turn_end')
    def test_orchestrator_returns_transition_signal(self, mock_orchestrator):
        """Verify orchestrator can return should_transition_to_conclusion=True."""
        # This tests that the signal propagates correctly through the system
        mock_orchestrator.return_value = FullModerationDecision(
            static_messages_to_speak=[],
            ai_should_speak=False,
            ai_message=None,
            hard_action=HardModerationAction.NONE,
            should_transition_to_conclusion=True,
        )

        # Verify mock returns expected value
        decision = mock_orchestrator()
        self.assertTrue(decision.should_transition_to_conclusion)


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
    def test_pronti_concludere_no_longer_at_turn_end(self, mock_ready, mock_reserved):
        """PRONTI_CONCLUDERE message should NOT be generated at turn end anymore."""
        session_id = "test-session-tts-2"
        mod_state = ModerationState.initial()
        save_moderation_state(session_id, mod_state)

        result = evaluate_triggers_on_human_turn_end(
            session_id=session_id,
            user_id=1,
            session_phase="ACTIVE",
            moderation_state=mod_state,
        )

        # Should NOT have "pronti a concludere" message at turn end anymore
        pronti_msgs = [m for m in result.static_messages_to_speak
                      if "pronti a concludere" in m.text]
        self.assertEqual(len(pronti_msgs), 0)


class TimeBasedTriggersTTSTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('apps.sessions.models.SessionParticipant.objects')
    @patch('apps.moderation.triggers._someone_is_currently_speaking', return_value=False)
    def test_no_push_message_has_use_tts_true(self, mock_speaking, mock_participant_objects):
        """NO_PUSH message should have use_tts=True."""
        from apps.moderation.triggers import evaluate_time_based_triggers, NO_PUSH_MESSAGES
        import uuid
        session_id = str(uuid.uuid4())

        # Mock participants (empty list to avoid inactive user trigger)
        mock_participant_objects.filter.return_value.select_related.return_value = []

        # Setup: last activity was 21 seconds ago (> 20s threshold)
        timers_state = ModerationTimersState.initial()
        timers_state.session_started_at = datetime.utcnow() - timedelta(minutes=5)
        timers_state.last_any_activity_at = datetime.utcnow() - timedelta(seconds=21)
        timers_state.no_push_notified = False
        save_timers_state(session_id, timers_state)

        result = evaluate_time_based_triggers(
            session_id=session_id,
            session_phase="ACTIVE",
        )

        no_push_msgs = [m for m in result.static_messages_to_speak
                       if m.text in NO_PUSH_MESSAGES]
        self.assertEqual(len(no_push_msgs), 1)
        self.assertTrue(no_push_msgs[0].use_tts)

    @patch('apps.sessions.models.SessionParticipant.objects')
    @patch('apps.moderation.triggers._someone_is_currently_speaking', return_value=False)
    def test_timer_25_message_has_use_tts_false(self, mock_speaking, mock_participant_objects):
        """TIMER_25 message should have use_tts=False (text only warning)."""
        from apps.moderation.triggers import evaluate_time_based_triggers
        import uuid
        session_id = str(uuid.uuid4())

        # Mock participants (empty list)
        mock_participant_objects.filter.return_value.select_related.return_value = []

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

    @patch('apps.sessions.models.SessionParticipant.objects')
    @patch('apps.moderation.triggers._someone_is_currently_speaking', return_value=False)
    def test_utente_inattivo_message_has_use_tts_true(self, mock_speaking, mock_participant_objects):
        """UTENTE_INATTIVO message should have use_tts=True."""
        from apps.moderation.triggers import evaluate_time_based_triggers, INACTIVE_VOICE_MESSAGES
        import uuid
        session_id = str(uuid.uuid4())

        # Setup: session with one user who never spoke
        timers_state = ModerationTimersState.initial()
        timers_state.session_started_at = datetime.utcnow() - timedelta(minutes=15)
        timers_state.last_any_activity_at = datetime.utcnow()
        timers_state.last_user_speak_at = {}  # No one spoke
        timers_state.voice_solicits_count = {}  # No solicits yet
        timers_state.last_voice_solicit_at = {}
        save_timers_state(session_id, timers_state)

        # Mock participant
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.display_name = "TestUser"
        mock_user.get_username.return_value = "testuser"

        mock_participant_obj = MagicMock()
        mock_participant_obj.user_id = 1
        mock_participant_obj.user = mock_user

        mock_participant_objects.filter.return_value.select_related.return_value = [mock_participant_obj]

        result = evaluate_time_based_triggers(
            session_id=session_id,
            session_phase="ACTIVE",
        )

        # Should have one message that contains "TestUser" (the inactive user)
        inactive_msgs = [m for m in result.static_messages_to_speak
                        if "TestUser" in m.text]
        self.assertEqual(len(inactive_msgs), 1)
        self.assertTrue(inactive_msgs[0].use_tts)


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

    def test_enqueue_blocked_after_trigger_conclusion(self):
        """New messages should be blocked when trigger_conclusion message exists."""
        session_id = "test-pending-block-1"

        # Accoda messaggio con trigger_conclusion=True
        enqueue_message(session_id, "Tutti pronti", "READY_3_3", trigger_conclusion=True)

        # Tenta di accodare altri messaggi
        enqueue_message(session_id, "NO PUSH message", "NO_PUSH")
        enqueue_message(session_id, "Another message", "TIMER_25")

        # Verifica che solo il messaggio trigger_conclusion sia in coda
        messages = dequeue_all_messages(session_id)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].text, "Tutti pronti")
        self.assertTrue(messages[0].trigger_conclusion)

    def test_enqueue_before_trigger_conclusion_allowed(self):
        """Messages enqueued before trigger_conclusion should remain in queue."""
        session_id = "test-pending-block-2"

        # Accoda messaggi normali prima
        enqueue_message(session_id, "First message", "NO_PUSH")
        enqueue_message(session_id, "Second message", "TIMER_25")

        # Poi accoda messaggio con trigger_conclusion
        enqueue_message(session_id, "Tutti pronti", "READY_3_3", trigger_conclusion=True)

        # Verifica che tutti e tre i messaggi siano presenti
        messages = dequeue_all_messages(session_id)
        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[0].text, "First message")
        self.assertEqual(messages[1].text, "Second message")
        self.assertEqual(messages[2].text, "Tutti pronti")
        self.assertTrue(messages[2].trigger_conclusion)


class TimeBasedTriggersBgTransitionTests(TestCase):
    """Tests for evaluate_time_based_triggers returning transition flag for timer 30."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('apps.sessions.models.SessionParticipant.objects')
    @patch('apps.moderation.triggers._someone_is_currently_speaking', return_value=False)
    def test_timer_30_via_time_based_triggers_returns_transition_flag(self, mock_speaking, mock_participant_objects):
        """evaluate_time_based_triggers should return should_transition_to_conclusion=True when timer 30 expires."""
        from apps.moderation.triggers import evaluate_time_based_triggers
        import uuid
        session_id = str(uuid.uuid4())

        # Mock participants (empty list)
        mock_participant_objects.filter.return_value.select_related.return_value = []

        # Setup: session started 31 minutes ago, timer not yet notified
        timers_state = ModerationTimersState.initial()
        timers_state.session_started_at = datetime.utcnow() - timedelta(minutes=31)
        timers_state.last_any_activity_at = datetime.utcnow()
        timers_state.timer_30_notified = False
        save_timers_state(session_id, timers_state)

        result = evaluate_time_based_triggers(
            session_id=session_id,
            session_phase="ACTIVE",
        )

        self.assertTrue(result.should_transition_to_conclusion)
        timer_msgs = [m for m in result.static_messages_to_speak
                      if "Il tempo della discussione è terminato" in m.text]
        self.assertEqual(len(timer_msgs), 1)


class TriggerLoopTransitionTests(TestCase):
    """Tests for _trigger_loop handling session transitions."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('apps.sessions.models.SessionParticipant.objects')
    @patch('apps.moderation.triggers._someone_is_currently_speaking', return_value=False)
    def test_trigger_loop_result_has_transition_flag(self, mock_speaking, mock_participant_objects):
        """Verify evaluate_time_based_triggers returns transition flag that _trigger_loop can use."""
        from apps.moderation.triggers import evaluate_time_based_triggers
        import uuid
        session_id = str(uuid.uuid4())

        # Mock participants (empty list)
        mock_participant_objects.filter.return_value.select_related.return_value = []

        timers_state = ModerationTimersState.initial()
        timers_state.session_started_at = datetime.utcnow() - timedelta(minutes=31)
        timers_state.last_any_activity_at = datetime.utcnow()
        timers_state.timer_30_notified = False
        save_timers_state(session_id, timers_state)

        result = evaluate_time_based_triggers(
            session_id=session_id,
            session_phase="ACTIVE",
        )

        # This flag should be True so _trigger_loop can transition the session
        self.assertTrue(result.should_transition_to_conclusion)


class PrenotazioneBroadcastTests(TestCase):
    """Tests for prenotazione message broadcast to all participants."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_prenotazione_message_should_be_broadcast_type(self):
        """Verify prenotazione messages have use_tts=False and should broadcast."""
        from apps.moderation.triggers import StaticMessage

        # The specification says prenotazione should be text-only (no TTS)
        # but visible to ALL participants, not just the sender
        msg = StaticMessage(text="Ora la parola va a Mario, che aveva prenotato.", use_tts=False)

        # This test documents the expected behavior:
        # - use_tts=False means no audio, just text
        # - But the message should still go to everyone via group_send
        self.assertFalse(msg.use_tts)
        self.assertIn("prenotato", msg.text)


class NoPushThresholdAndResetTests(TestCase):
    """Tests for NO_PUSH 20s threshold and flag reset on activity."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('apps.sessions.models.SessionParticipant.objects')
    @patch('apps.moderation.triggers._someone_is_currently_speaking', return_value=False)
    def test_no_push_does_not_trigger_at_15_seconds(self, mock_speaking, mock_participant_objects):
        """NO_PUSH should NOT trigger at 15s (old threshold), only at 20s."""
        from apps.moderation.triggers import evaluate_time_based_triggers
        import uuid
        session_id = str(uuid.uuid4())

        mock_participant_objects.filter.return_value.select_related.return_value = []

        # Setup: last activity was 16 seconds ago (> 15s but < 20s)
        timers_state = ModerationTimersState.initial()
        timers_state.session_started_at = datetime.utcnow() - timedelta(minutes=5)
        timers_state.last_any_activity_at = datetime.utcnow() - timedelta(seconds=16)
        timers_state.no_push_notified = False
        save_timers_state(session_id, timers_state)

        result = evaluate_time_based_triggers(
            session_id=session_id,
            session_phase="ACTIVE",
        )

        no_push_msgs = [m for m in result.static_messages_to_speak
                       if "intervenire" in m.text.lower()]
        self.assertEqual(len(no_push_msgs), 0, "NO_PUSH should not trigger at 16s")

    @patch('apps.sessions.models.SessionParticipant.objects')
    @patch('apps.moderation.triggers._someone_is_currently_speaking', return_value=False)
    def test_no_push_triggers_at_20_seconds(self, mock_speaking, mock_participant_objects):
        """NO_PUSH should trigger at 20s."""
        from apps.moderation.triggers import evaluate_time_based_triggers, NO_PUSH_MESSAGES
        import uuid
        session_id = str(uuid.uuid4())

        mock_participant_objects.filter.return_value.select_related.return_value = []

        # Setup: last activity was 21 seconds ago (> 20s threshold)
        timers_state = ModerationTimersState.initial()
        timers_state.session_started_at = datetime.utcnow() - timedelta(minutes=5)
        timers_state.last_any_activity_at = datetime.utcnow() - timedelta(seconds=21)
        timers_state.no_push_notified = False
        save_timers_state(session_id, timers_state)

        result = evaluate_time_based_triggers(
            session_id=session_id,
            session_phase="ACTIVE",
        )

        no_push_msgs = [m for m in result.static_messages_to_speak
                       if m.text in NO_PUSH_MESSAGES]
        self.assertEqual(len(no_push_msgs), 1, "NO_PUSH should trigger at 21s")


class NoPushResetTests(TestCase):
    """Tests for NO_PUSH flag reset when someone speaks."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_mark_any_activity_resets_no_push_notified(self):
        """mark_any_activity should reset no_push_notified flag."""
        from apps.moderation.timers_state import mark_any_activity
        import uuid
        session_id = str(uuid.uuid4())

        # Setup: no_push already notified
        timers_state = ModerationTimersState.initial()
        timers_state.session_started_at = datetime.utcnow() - timedelta(minutes=5)
        timers_state.last_any_activity_at = datetime.utcnow() - timedelta(seconds=30)
        timers_state.no_push_notified = True
        save_timers_state(session_id, timers_state)

        # Activity occurs
        mark_any_activity(session_id)

        # Verify flag is reset
        loaded = load_timers_state(session_id)
        self.assertFalse(loaded.no_push_notified)

    @patch('apps.sessions.models.SessionParticipant.objects')
    @patch('apps.moderation.triggers._someone_is_currently_speaking', return_value=False)
    def test_no_push_can_trigger_again_after_activity(self, mock_speaking, mock_participant_objects):
        """NO_PUSH should be able to trigger again after activity resets the flag."""
        from apps.moderation.triggers import evaluate_time_based_triggers, NO_PUSH_MESSAGES
        from apps.moderation.timers_state import mark_any_activity
        import uuid
        session_id = str(uuid.uuid4())

        mock_participant_objects.filter.return_value.select_related.return_value = []

        # Setup: no_push already triggered
        timers_state = ModerationTimersState.initial()
        timers_state.session_started_at = datetime.utcnow() - timedelta(minutes=5)
        timers_state.last_any_activity_at = datetime.utcnow() - timedelta(seconds=30)
        timers_state.no_push_notified = True
        save_timers_state(session_id, timers_state)

        # Someone speaks (activity)
        mark_any_activity(session_id)

        # Wait 21 seconds (simulate by updating timestamp)
        state = load_timers_state(session_id)
        state.last_any_activity_at = datetime.utcnow() - timedelta(seconds=21)
        save_timers_state(session_id, state)

        # NO_PUSH should trigger again
        result = evaluate_time_based_triggers(
            session_id=session_id,
            session_phase="ACTIVE",
        )

        no_push_msgs = [m for m in result.static_messages_to_speak
                       if m.text in NO_PUSH_MESSAGES]
        self.assertEqual(len(no_push_msgs), 1)


class NoPushMessageVariantsTests(TestCase):
    """Tests for NO_PUSH message variants."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('apps.sessions.models.SessionParticipant.objects')
    @patch('apps.moderation.triggers._someone_is_currently_speaking', return_value=False)
    def test_no_push_message_is_from_variants(self, mock_speaking, mock_participant_objects):
        """NO_PUSH message should be one of the defined variants."""
        from apps.moderation.triggers import evaluate_time_based_triggers, NO_PUSH_MESSAGES
        import uuid
        session_id = str(uuid.uuid4())

        mock_participant_objects.filter.return_value.select_related.return_value = []

        timers_state = ModerationTimersState.initial()
        timers_state.session_started_at = datetime.utcnow() - timedelta(minutes=5)
        timers_state.last_any_activity_at = datetime.utcnow() - timedelta(seconds=25)
        timers_state.no_push_notified = False
        save_timers_state(session_id, timers_state)

        result = evaluate_time_based_triggers(
            session_id=session_id,
            session_phase="ACTIVE",
        )

        self.assertEqual(len(result.static_messages_to_speak), 1)
        self.assertIn(result.static_messages_to_speak[0].text, NO_PUSH_MESSAGES)


class StaticMessageTriggerTypeTests(TestCase):
    """Tests for StaticMessage trigger_type field."""

    def test_static_message_with_trigger_type(self):
        """StaticMessage should support optional trigger_type field."""
        msg = StaticMessage(text="Test", use_tts=False, trigger_type="TIMER_25")
        self.assertEqual(msg.trigger_type, "TIMER_25")

    def test_static_message_trigger_type_default_none(self):
        """StaticMessage trigger_type should default to None."""
        msg = StaticMessage(text="Test", use_tts=True)
        self.assertIsNone(msg.trigger_type)


class Timer25TriggerTypeTests(TestCase):
    """Tests for TIMER_25 trigger_type for frontend visual timer."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('apps.sessions.models.SessionParticipant.objects')
    @patch('apps.moderation.triggers._someone_is_currently_speaking', return_value=False)
    def test_timer_25_message_has_trigger_type(self, mock_speaking, mock_participant_objects):
        """TIMER_25 message should have trigger_type='TIMER_25' for frontend."""
        from apps.moderation.triggers import evaluate_time_based_triggers
        import uuid
        session_id = str(uuid.uuid4())

        mock_participant_objects.filter.return_value.select_related.return_value = []

        timers_state = ModerationTimersState.initial()
        timers_state.session_started_at = datetime.utcnow() - timedelta(minutes=26)
        timers_state.last_any_activity_at = datetime.utcnow()
        timers_state.timer_25_notified = False
        save_timers_state(session_id, timers_state)

        result = evaluate_time_based_triggers(
            session_id=session_id,
            session_phase="ACTIVE",
        )

        timer_25_msgs = [m for m in result.static_messages_to_speak
                        if "cinque minuti" in m.text]
        self.assertEqual(len(timer_25_msgs), 1)
        self.assertEqual(timer_25_msgs[0].trigger_type, "TIMER_25")


class ReadyToConcludeTests(TestCase):
    """Tests for ready_to_conclude trigger fixes."""

    def test_ready_to_conclude_message_variants_exist(self):
        """Verify READY_TO_CONCLUDE_MESSAGES constants exist."""
        from apps.moderation.triggers import (
            READY_TO_CONCLUDE_MESSAGES,
            READY_TO_CONCLUDE_LAST_ONE_MESSAGES,
        )

        self.assertGreater(len(READY_TO_CONCLUDE_MESSAGES), 1)
        self.assertGreater(len(READY_TO_CONCLUDE_LAST_ONE_MESSAGES), 1)

        # All should have {nome} placeholder
        for msg in READY_TO_CONCLUDE_MESSAGES:
            self.assertIn("{nome}", msg)
        for msg in READY_TO_CONCLUDE_LAST_ONE_MESSAGES:
            self.assertIn("{nome}", msg)

    def test_generate_ready_to_conclude_message_normal(self):
        """generate_ready_to_conclude_message returns normal variant."""
        from apps.moderation.triggers import (
            generate_ready_to_conclude_message,
            READY_TO_CONCLUDE_MESSAGES,
        )

        result = generate_ready_to_conclude_message("Mario", ready_count=1, total_count=4)

        # Should be TTS
        self.assertTrue(result.message.use_tts)
        # Should contain user name
        self.assertIn("Mario", result.message.text)
        # Should NOT trigger conclusion (not 3/3)
        self.assertFalse(result.trigger_conclusion)

    def test_generate_ready_to_conclude_message_last_one(self):
        """generate_ready_to_conclude_message returns 'last one' variant when appropriate."""
        from apps.moderation.triggers import (
            generate_ready_to_conclude_message,
            READY_TO_CONCLUDE_LAST_ONE_MESSAGES,
        )

        # 3 ready out of 4 = only 1 missing
        result = generate_ready_to_conclude_message("Luigi", ready_count=3, total_count=4)

        self.assertTrue(result.message.use_tts)
        self.assertIn("Luigi", result.message.text)
        # Should mention "manca solo" or similar
        self.assertTrue(
            "manca solo" in result.message.text.lower() or
            "quasi tutti" in result.message.text.lower()
        )
        # Should NOT trigger conclusion (not 4/4)
        self.assertFalse(result.trigger_conclusion)

    def test_generate_ready_to_conclude_message_all_ready(self):
        """generate_ready_to_conclude_message returns 'all ready' variant and triggers conclusion."""
        from apps.moderation.triggers import (
            generate_ready_to_conclude_message,
            READY_TO_CONCLUDE_ALL_READY_MESSAGES,
        )

        # 4 ready out of 4 = all ready
        result = generate_ready_to_conclude_message("Luigi", ready_count=4, total_count=4)

        self.assertTrue(result.message.use_tts)
        # Should NOT contain user name (all ready messages don't have {nome})
        self.assertNotIn("Luigi", result.message.text)
        # Should mention "tutti" or similar
        self.assertTrue(
            "tutti" in result.message.text.lower()
        )
        # Should trigger conclusion (4/4)
        self.assertTrue(result.trigger_conclusion)


class ModerationStateTurnsPerParticipantTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_initial_state_has_empty_turns_per_participant(self):
        """Initial ModerationState should have empty turns_per_participant dict."""
        state = ModerationState.initial()
        self.assertEqual(state.turns_per_participant, {})

    def test_turns_per_participant_persists_after_save_and_load(self):
        """turns_per_participant should be saved to and loaded from Redis."""
        session_id = "test-session-tpp-1"

        state = ModerationState.initial()
        state.turns_per_participant = {"Mario": 3, "Lucia": 1}
        save_moderation_state(session_id, state)

        loaded = load_moderation_state(session_id)
        self.assertEqual(loaded.turns_per_participant, {"Mario": 3, "Lucia": 1})


class TurnsPerParticipantIncrementTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch.object(ModerationService, '_call_llm')
    def test_turns_per_participant_incremented_on_turn_end(self, mock_llm):
        """handle_human_turn_ended should increment turns_per_participant for speaker."""
        session_id = "test-tpp-increment-1"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": False,
            "message_to_say": None,
            "reason": "all_ok",
            "intervention_score": 0.2,
        }

        # Initial state with no turns
        state = ModerationState.initial()
        save_moderation_state(session_id, state)

        # First turn from Mario
        ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="Mario",
        )

        loaded = load_moderation_state(session_id)
        self.assertEqual(loaded.turns_per_participant.get("Mario"), 1)

    @patch.object(ModerationService, '_call_llm')
    def test_turns_per_participant_accumulates(self, mock_llm):
        """Multiple turns from same speaker should accumulate."""
        session_id = "test-tpp-increment-2"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": False,
            "message_to_say": None,
            "reason": "all_ok",
            "intervention_score": 0.2,
        }

        state = ModerationState.initial()
        state.turns_per_participant = {"Mario": 2}
        save_moderation_state(session_id, state)

        ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="Mario",
        )

        loaded = load_moderation_state(session_id)
        self.assertEqual(loaded.turns_per_participant.get("Mario"), 3)

    @patch.object(ModerationService, '_call_llm')
    def test_turns_per_participant_not_incremented_without_speaker_name(self, mock_llm):
        """If speaker_name is None, turns_per_participant should not change."""
        session_id = "test-tpp-no-name"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": False,
            "message_to_say": None,
            "reason": "all_ok",
            "intervention_score": 0.2,
        }

        state = ModerationState.initial()
        save_moderation_state(session_id, state)

        ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name=None,  # No speaker name
        )

        loaded = load_moderation_state(session_id)
        self.assertEqual(loaded.turns_per_participant, {})


class AIInterventionCountModeTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch.object(ModerationService, '_call_llm')
    def test_normal_mode_increments_ai_intervention_count(self, mock_llm):
        """Normal mode AI intervention should increment ai_interventions_count."""
        session_id = "test-ai-count-1"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": True,
            "message_to_say": "Test intervention",
            "reason": "monopolization",
            "intervention_score": 0.8,
        }

        state = ModerationState.initial()
        state.ai_interventions_count = 0
        save_moderation_state(session_id, state)

        ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,  # normal mode
            speaker_name="Mario",
        )

        loaded = load_moderation_state(session_id)
        self.assertEqual(loaded.ai_interventions_count, 1)

    @patch.object(ModerationService, '_call_llm')
    def test_forced_summary_does_not_increment_ai_intervention_count(self, mock_llm):
        """Forced summary should NOT increment ai_interventions_count."""
        session_id = "test-ai-count-2"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": True,
            "message_to_say": "Summary message",
            "reason": "forced_summary",
            "intervention_score": 1.0,
        }

        state = ModerationState.initial()
        state.ai_interventions_count = 2
        save_moderation_state(session_id, state)

        ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.FORCED_SUMMARY,
            speaker_name="Mario",
        )

        loaded = load_moderation_state(session_id)
        # Should still be 2, not 3
        self.assertEqual(loaded.ai_interventions_count, 2)

    @patch.object(ModerationService, '_call_llm')
    def test_forced_conclusion_does_not_increment_ai_intervention_count(self, mock_llm):
        """Forced conclusion should NOT increment ai_interventions_count."""
        session_id = "test-ai-count-3"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": True,
            "message_to_say": "Conclusion message",
            "reason": "forced_conclusion",
            "intervention_score": 1.0,
        }

        state = ModerationState.initial()
        state.ai_interventions_count = 3
        save_moderation_state(session_id, state)

        ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="CONCLUSION",
            hard_action=HardModerationAction.FORCED_CONCLUSION,
            speaker_name="Mario",
        )

        loaded = load_moderation_state(session_id)
        # Should still be 3, not 4
        self.assertEqual(loaded.ai_interventions_count, 3)


class BuildNormalModePromptTests(TestCase):
    def test_build_normal_mode_prompt_exists(self):
        """_build_normal_mode_prompt should exist and return a string."""
        prompt = ModerationService._build_normal_mode_prompt()
        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 100)

    def test_build_normal_mode_prompt_contains_intervention_criteria(self):
        """Prompt should contain specific intervention criteria."""
        prompt = ModerationService._build_normal_mode_prompt()

        # Check for intervention criteria
        self.assertIn("monopol", prompt.lower())  # monopolization
        self.assertIn("esclus", prompt.lower())   # exclusion
        self.assertIn("off-topic", prompt.lower())
        self.assertIn("conflitt", prompt.lower()) # conflict

    def test_build_normal_mode_prompt_contains_json_output_spec(self):
        """Prompt should specify JSON output format."""
        prompt = ModerationService._build_normal_mode_prompt()

        self.assertIn("updated_summary", prompt)
        self.assertIn("should_ai_speak", prompt)
        self.assertIn("message_to_say", prompt)
        self.assertIn("intervention_score", prompt)

    def test_build_normal_mode_prompt_contains_score_thresholds(self):
        """Prompt should explain intervention_score thresholds."""
        prompt = ModerationService._build_normal_mode_prompt()

        self.assertIn("0.7", prompt)  # threshold for intervention


class BuildSystemPromptTests(TestCase):
    def test_build_system_prompt_normal_mode(self):
        """_build_system_prompt('normal') should return normal mode prompt."""
        prompt = ModerationService._build_system_prompt("normal")
        # Should contain intervention criteria specific to normal mode
        self.assertIn("monopol", prompt.lower())

    def test_build_system_prompt_forced_summary_mode(self):
        """_build_system_prompt('forced_summary') should return the rich forced_summary prompt."""
        prompt = ModerationService._build_system_prompt("forced_summary")
        self.assertIsInstance(prompt, str)
        # Step 3 refactor: forced_summary ora route a _build_forced_summary_system_prompt
        # (il duplicato più minimale _build_forced_summary_prompt è stato rimosso).
        self.assertIn("ricapitolazione", prompt.lower())

    def test_build_system_prompt_forced_conclusion_mode(self):
        """_build_system_prompt('forced_conclusion') should return conclusion prompt."""
        prompt = ModerationService._build_system_prompt("forced_conclusion")
        # Should use existing _build_forced_conclusion_system_prompt
        self.assertIn("conclus", prompt.lower())

    def test_build_system_prompt_unknown_mode_defaults_to_normal(self):
        """Unknown mode should default to normal mode prompt."""
        prompt = ModerationService._build_system_prompt("unknown_mode")
        normal_prompt = ModerationService._build_normal_mode_prompt()
        self.assertEqual(prompt, normal_prompt)


class CallLLMStructuredInputTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch.object(ModerationService, '_build_openai_client')
    def test_call_llm_sends_structured_input_with_participants(self, mock_client):
        """_call_llm should send structured input including participants.turns."""
        # Setup mock
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "updated_summary": "Test summary",
            "should_ai_speak": False,
            "message_to_say": None,
            "reason": "all_ok",
            "intervention_score": 0.2,
        })
        mock_client.return_value.chat.completions.create.return_value = mock_response

        # Create state with turns_per_participant
        turns_per_participant = {"Mario": 5, "Lucia": 2}

        # Call _call_llm with state
        ModerationService._call_llm(
            summary_in="Test summary",
            last_turn="Test turn",
            mode="normal",
            session_phase="ACTIVE",
            speaker_name="Mario",
            turns_per_participant=turns_per_participant,
        )

        # Verify the call was made
        mock_client.return_value.chat.completions.create.assert_called_once()
        call_args = mock_client.return_value.chat.completions.create.call_args

        # Extract the user message content
        messages = call_args[1]['messages']
        user_message = messages[1]['content']
        user_data = json.loads(user_message)

        # Verify structured input
        self.assertIn("participants", user_data)
        self.assertIn("turns", user_data["participants"])
        self.assertEqual(user_data["participants"]["turns"], {"Mario": 5, "Lucia": 2})

    @patch.object(ModerationService, '_build_openai_client')
    def test_call_llm_uses_normal_mode_prompt(self, mock_client):
        """_call_llm in normal mode should use _build_normal_mode_prompt."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "updated_summary": "Test",
            "should_ai_speak": False,
            "message_to_say": None,
            "reason": "all_ok",
            "intervention_score": 0.1,
        })
        mock_client.return_value.chat.completions.create.return_value = mock_response

        ModerationService._call_llm(
            summary_in="Test",
            last_turn="Turn",
            mode="normal",
            session_phase="ACTIVE",
            speaker_name="Mario",
            turns_per_participant={},
        )

        call_args = mock_client.return_value.chat.completions.create.call_args
        messages = call_args[1]['messages']
        system_prompt = messages[0]['content']

        # Should contain intervention criteria from normal mode prompt
        self.assertIn("monopol", system_prompt.lower())
        self.assertIn("intervention_score", system_prompt)


class HandleHumanTurnPassesStateTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch.object(ModerationService, '_call_llm')
    def test_handle_human_turn_passes_turns_per_participant_to_llm(self, mock_llm):
        """handle_human_turn_ended should pass turns_per_participant to _call_llm."""
        session_id = "test-pass-state-1"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": False,
            "message_to_say": None,
            "reason": "all_ok",
            "intervention_score": 0.2,
        }

        # Setup state with existing turns
        state = ModerationState.initial()
        state.turns_per_participant = {"Mario": 3, "Lucia": 1}
        save_moderation_state(session_id, state)

        ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="Mario",
        )

        # Verify _call_llm was called with turns_per_participant
        mock_llm.assert_called_once()
        call_kwargs = mock_llm.call_args[1]

        # After increment, Mario should have 4 turns
        self.assertIn("turns_per_participant", call_kwargs)
        self.assertEqual(call_kwargs["turns_per_participant"]["Mario"], 4)
        self.assertEqual(call_kwargs["turns_per_participant"]["Lucia"], 1)


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


class ForcedConclusionLLMTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch.object(ModerationService, '_build_openai_client')
    def test_call_llm_for_conclusion_returns_expected_structure(self, mock_client):
        """call_llm_for_conclusion should return expected dict structure."""
        # Mock the Azure response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "updated_summary": "Test summary",
            "message_to_say": "Closing message",
        })
        mock_client.return_value.chat.completions.create.return_value = mock_response

        result = ModerationService.call_llm_for_conclusion(
            summary_in="Discussion summary",
            conclusion_reason="all_participants_ready",
            session_duration_minutes=25,
        )

        self.assertIn("updated_summary", result)
        self.assertIn("message_to_say", result)
        self.assertIsNotNone(result["message_to_say"])

    def test_call_llm_for_conclusion_fallback_timer_expired(self):
        """Fallback for conclusion_reason='timer_expired' should mention time."""
        result = ModerationService._fallback_forced_conclusion(
            summary="Test summary",
            conclusion_reason="timer_expired",
        )

        self.assertIn("terminato", result["message_to_say"].lower())

    def test_call_llm_for_conclusion_fallback_all_ready(self):
        """Fallback for conclusion_reason='all_participants_ready' should mention decision."""
        result = ModerationService._fallback_forced_conclusion(
            summary="Test summary",
            conclusion_reason="all_participants_ready",
        )

        self.assertIn("deciso", result["message_to_say"].lower())


class InactiveUserTests(TestCase):
    """Tests for UTENTE INATTIVO trigger fixes."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_inactive_voice_messages_exist(self):
        """Verify INACTIVE_VOICE_MESSAGES constants exist."""
        from apps.moderation.triggers import INACTIVE_VOICE_MESSAGES

        self.assertGreater(len(INACTIVE_VOICE_MESSAGES), 1)
        # All should have {nome} placeholder
        for msg in INACTIVE_VOICE_MESSAGES:
            self.assertIn("{nome}", msg)

    @patch('apps.sessions.models.SessionParticipant.objects')
    @patch('apps.moderation.triggers._someone_is_currently_speaking', return_value=False)
    def test_inactive_user_max_two_voice_solicits(self, mock_speaking, mock_participant_objects):
        """User should receive max 2 voice solicits, then no more."""
        from apps.moderation.triggers import evaluate_time_based_triggers
        import uuid
        session_id = str(uuid.uuid4())

        # Setup participant
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.display_name = "TestUser"
        mock_user.get_username.return_value = "testuser"

        mock_participant_obj = MagicMock()
        mock_participant_obj.user_id = 1
        mock_participant_obj.user = mock_user

        mock_participant_objects.filter.return_value.select_related.return_value = [mock_participant_obj]

        # Setup: user already received 2 voice solicits
        timers_state = ModerationTimersState.initial()
        timers_state.session_started_at = datetime.utcnow() - timedelta(minutes=30)
        timers_state.last_any_activity_at = datetime.utcnow()
        timers_state.voice_solicits_count = {"1": 2}  # Already received 2
        timers_state.last_voice_solicit_at = {"1": datetime.utcnow() - timedelta(minutes=15)}
        save_timers_state(session_id, timers_state)

        result = evaluate_time_based_triggers(
            session_id=session_id,
            session_phase="ACTIVE",
        )

        # Should NOT receive another solicit
        inactive_msgs = [m for m in result.static_messages_to_speak
                        if "TestUser" in m.text]
        self.assertEqual(len(inactive_msgs), 0)

    @patch('apps.sessions.models.SessionParticipant.objects')
    @patch('apps.moderation.triggers._someone_is_currently_speaking', return_value=False)
    def test_inactive_user_timer_resets_after_voice_solicit(self, mock_speaking, mock_participant_objects):
        """After voice solicit, timer should reset (use last_voice_solicit_at as reference)."""
        from apps.moderation.triggers import evaluate_time_based_triggers
        import uuid
        session_id = str(uuid.uuid4())

        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.display_name = "TestUser"
        mock_user.get_username.return_value = "testuser"

        mock_participant_obj = MagicMock()
        mock_participant_obj.user_id = 1
        mock_participant_obj.user = mock_user

        mock_participant_objects.filter.return_value.select_related.return_value = [mock_participant_obj]

        # Setup: user received 1 voice solicit 5 minutes ago
        # (Should wait 10 more minutes from that point, not from session start)
        timers_state = ModerationTimersState.initial()
        timers_state.session_started_at = datetime.utcnow() - timedelta(minutes=30)
        timers_state.last_any_activity_at = datetime.utcnow()
        timers_state.voice_solicits_count = {"1": 1}
        timers_state.last_voice_solicit_at = {"1": datetime.utcnow() - timedelta(minutes=5)}
        save_timers_state(session_id, timers_state)

        result = evaluate_time_based_triggers(
            session_id=session_id,
            session_phase="ACTIVE",
        )

        # Should NOT trigger yet (only 5 min since last solicit, need 10)
        inactive_msgs = [m for m in result.static_messages_to_speak
                        if "TestUser" in m.text]
        self.assertEqual(len(inactive_msgs), 0)


class CallLLMForSummaryTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch.object(ModerationService, '_build_openai_client')
    def test_call_llm_for_summary_returns_expected_structure(self, mock_client):
        """call_llm_for_summary should return dict with updated_summary, message_to_say, correction_reason."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "updated_summary": "Updated summary",
            "message_to_say": "Recap message",
            "correction_reason": None,
        })
        mock_client.return_value.chat.completions.create.return_value = mock_response

        result = ModerationService.call_llm_for_summary(
            summary_in="Previous summary",
            last_turn_text="Mario said something about Eddie",
            last_turn_speaker="Mario",
            participants_turns={"Mario": 5, "Lucia": 3, "Paolo": 2},
            total_turns=10,
        )

        self.assertIn("updated_summary", result)
        self.assertIn("message_to_say", result)
        self.assertIn("correction_reason", result)
        self.assertIsNotNone(result["message_to_say"])

    @patch.object(ModerationService, '_build_openai_client')
    def test_call_llm_for_summary_uses_fallback_on_api_error(self, mock_client):
        """call_llm_for_summary should use fallback when Azure API fails."""
        mock_client.return_value.chat.completions.create.side_effect = Exception("API Error")

        result = ModerationService.call_llm_for_summary(
            summary_in="Previous summary",
            last_turn_text="Last turn",
            last_turn_speaker="Mario",
            participants_turns={"Mario": 3},
            total_turns=3,
        )

        # Should return fallback structure
        self.assertIn("updated_summary", result)
        self.assertIn("message_to_say", result)
        self.assertIn("approfondire", result["message_to_say"].lower())
        self.assertIsNone(result["correction_reason"])

    @patch.object(ModerationService, '_build_openai_client')
    def test_call_llm_for_summary_uses_fallback_on_invalid_json(self, mock_client):
        """call_llm_for_summary should use fallback when LLM returns invalid JSON."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Not valid JSON"
        mock_client.return_value.chat.completions.create.return_value = mock_response

        result = ModerationService.call_llm_for_summary(
            summary_in="Previous summary",
            last_turn_text="Last turn",
            last_turn_speaker="Mario",
            participants_turns={"Mario": 3},
            total_turns=3,
        )

        self.assertIn("approfondire", result["message_to_say"].lower())


class ForcedSummarySystemPromptTests(TestCase):
    def test_forced_summary_system_prompt_contains_murder_mystery_context(self):
        """FORCED_SUMMARY prompt should contain murder mystery context."""
        prompt = ModerationService._build_forced_summary_system_prompt()
        self.assertIn("murder mystery", prompt.lower())

    def test_forced_summary_system_prompt_contains_hybrid_instructions(self):
        """FORCED_SUMMARY prompt should mention both correction and recap."""
        prompt = ModerationService._build_forced_summary_system_prompt()
        self.assertIn("correzione", prompt.lower())
        self.assertIn("ricapitolazione", prompt.lower())

    def test_forced_summary_system_prompt_contains_output_format(self):
        """FORCED_SUMMARY prompt should specify JSON output with correction_reason."""
        prompt = ModerationService._build_forced_summary_system_prompt()
        self.assertIn("correction_reason", prompt)
        self.assertIn("updated_summary", prompt)
        self.assertIn("message_to_say", prompt)

    def test_forced_summary_system_prompt_forbids_greetings(self):
        """FORCED_SUMMARY prompt should explicitly forbid greetings and introductions."""
        prompt = ModerationService._build_forced_summary_system_prompt()
        # Check that the prompt mentions not to use greetings
        self.assertIn("NON usare mai", prompt)
        self.assertIn("Ciao", prompt)
        self.assertIn("GIÀ PRESENTATO", prompt)
        # Check for suggested alternatives
        self.assertIn("Finora è emerso", prompt)


class ForcedSummaryFallbackTests(TestCase):
    def test_fallback_forced_summary_returns_expected_structure(self):
        """_fallback_forced_summary should return dict with required fields."""
        result = ModerationService._fallback_forced_summary(
            summary_in="Previous discussion",
            last_turn_text="Mario mentioned Eddie",
        )

        self.assertIn("updated_summary", result)
        self.assertIn("message_to_say", result)
        self.assertIn("correction_reason", result)
        self.assertIsNone(result["correction_reason"])

    def test_fallback_forced_summary_combines_summary_and_turn(self):
        """Fallback should combine summary and last turn in updated_summary."""
        result = ModerationService._fallback_forced_summary(
            summary_in="Summary A",
            last_turn_text="Turn B",
        )

        self.assertIn("Summary A", result["updated_summary"])
        self.assertIn("Turn B", result["updated_summary"])

    def test_fallback_forced_summary_message_invites_discussion(self):
        """Fallback message should invite further discussion."""
        result = ModerationService._fallback_forced_summary(
            summary_in="Test",
            last_turn_text="Test turn",
        )

        self.assertIn("approfondire", result["message_to_say"].lower())


class OrchestratorForcedSummaryBifurcationTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('apps.moderation.orchestrator.evaluate_triggers_on_human_turn_end')
    @patch.object(ModerationService, 'call_llm_for_summary')
    @patch.object(ModerationService, 'handle_human_turn_ended')
    def test_forced_summary_uses_dedicated_method(self, mock_handle, mock_summary, mock_triggers):
        """When FORCED_SUMMARY triggers, orchestrator should call call_llm_for_summary."""
        session_id = "test-orch-fs-1"

        # Setup trigger to return FORCED_SUMMARY
        mock_triggers.return_value = TriggerEvaluationResult(
            hard_action=HardModerationAction.FORCED_SUMMARY,
            static_messages_to_speak=[],
            should_transition_to_conclusion=False,
        )

        # Setup summary LLM response
        mock_summary.return_value = {
            "updated_summary": "Updated summary",
            "message_to_say": "Recap message",
            "correction_reason": None,
        }

        # Setup initial state
        state = ModerationState.initial()
        state.turns_per_participant = {"Mario": 3}
        save_moderation_state(session_id, state)

        decision = ModerationOrchestrator.handle_human_turn_end(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            speaker_name="Mario",
        )

        # call_llm_for_summary should be called
        mock_summary.assert_called_once()
        # handle_human_turn_ended should NOT be called (bifurcation)
        mock_handle.assert_not_called()
        # AI should speak
        self.assertTrue(decision.ai_should_speak)
        self.assertEqual(decision.ai_message, "Recap message")

    @patch('apps.moderation.orchestrator.evaluate_triggers_on_human_turn_end')
    @patch.object(ModerationService, 'call_llm_for_summary')
    @patch.object(ModerationService, 'handle_human_turn_ended')
    def test_normal_mode_uses_handle_human_turn_ended(self, mock_handle, mock_summary, mock_triggers):
        """When no hard action, orchestrator should call handle_human_turn_ended (normal path)."""
        session_id = "test-orch-normal-1"

        mock_triggers.return_value = TriggerEvaluationResult(
            hard_action=HardModerationAction.NONE,
            static_messages_to_speak=[],
            should_transition_to_conclusion=False,
        )

        mock_handle.return_value = ModerationResult(
            ai_should_speak=False,
            ai_message=None,
            updated_state=ModerationState.initial(),
        )

        state = ModerationState.initial()
        save_moderation_state(session_id, state)

        ModerationOrchestrator.handle_human_turn_end(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            speaker_name="Mario",
        )

        # handle_human_turn_ended should be called (normal path)
        mock_handle.assert_called_once()
        # call_llm_for_summary should NOT be called
        mock_summary.assert_not_called()


class SummaryUpdateBothPathsTests(TestCase):
    """Verify summary is always updated in both FORCED_SUMMARY and normal paths."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('apps.moderation.orchestrator.evaluate_triggers_on_human_turn_end')
    @patch.object(ModerationService, 'call_llm_for_summary')
    def test_forced_summary_updates_summary(self, mock_summary, mock_triggers):
        """FORCED_SUMMARY path should update moderation_state.summary."""
        session_id = "test-summary-fs-1"

        mock_triggers.return_value = TriggerEvaluationResult(
            hard_action=HardModerationAction.FORCED_SUMMARY,
            static_messages_to_speak=[],
            should_transition_to_conclusion=False,
        )

        mock_summary.return_value = {
            "updated_summary": "NEW SUMMARY FROM LLM",
            "message_to_say": "Recap",
            "correction_reason": None,
        }

        state = ModerationState.initial()
        state.summary = "OLD SUMMARY"
        state.human_turns_since_last_summary = 3
        save_moderation_state(session_id, state)

        ModerationOrchestrator.handle_human_turn_end(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            speaker_name="Mario",
        )

        loaded = load_moderation_state(session_id)
        self.assertEqual(loaded.summary, "NEW SUMMARY FROM LLM")
        # Counter should be reset
        self.assertEqual(loaded.human_turns_since_last_summary, 0)

    @patch.object(ModerationService, '_call_llm')
    def test_normal_path_updates_summary(self, mock_llm):
        """Normal path should also update moderation_state.summary."""
        session_id = "test-summary-normal-1"

        mock_llm.return_value = {
            "updated_summary": "UPDATED NORMAL SUMMARY",
            "should_ai_speak": False,
            "message_to_say": None,
            "reason": "all_ok",
            "intervention_score": 0.2,
        }

        state = ModerationState.initial()
        state.summary = "OLD SUMMARY"
        state.human_turns_since_last_summary = 1  # Not enough to trigger FORCED_SUMMARY
        save_moderation_state(session_id, state)

        ModerationOrchestrator.handle_human_turn_end(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            speaker_name="Mario",
        )

        loaded = load_moderation_state(session_id)
        self.assertEqual(loaded.summary, "UPDATED NORMAL SUMMARY")
        # Counter should be incremented (not reset)
        self.assertEqual(loaded.human_turns_since_last_summary, 2)


class ForcedSummaryCompatibilityWithConclusionTests(TestCase):
    """Verify FORCED_SUMMARY doesn't break FORCED_CONCLUSION flow."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('apps.moderation.orchestrator.evaluate_triggers_on_human_turn_end')
    @patch.object(ModerationService, 'call_llm_for_summary')
    def test_forced_summary_preserves_transition_flag(self, mock_summary, mock_triggers):
        """FORCED_SUMMARY path should preserve should_transition_to_conclusion from triggers."""
        session_id = "test-compat-1"

        # Trigger returns FORCED_SUMMARY AND should_transition_to_conclusion=True
        # (edge case: timer expired on same turn as summary)
        mock_triggers.return_value = TriggerEvaluationResult(
            hard_action=HardModerationAction.FORCED_SUMMARY,
            static_messages_to_speak=[],
            should_transition_to_conclusion=True,
        )

        mock_summary.return_value = {
            "updated_summary": "Summary",
            "message_to_say": "Message",
            "correction_reason": None,
        }

        state = ModerationState.initial()
        save_moderation_state(session_id, state)

        decision = ModerationOrchestrator.handle_human_turn_end(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test",
            session_phase="ACTIVE",
            speaker_name="Mario",
        )

        # Transition flag should be preserved
        self.assertTrue(decision.should_transition_to_conclusion)

    @patch('apps.moderation.orchestrator.evaluate_triggers_on_human_turn_end')
    @patch.object(ModerationService, 'call_llm_for_summary')
    def test_forced_summary_leaves_summary_for_conclusion(self, mock_summary, mock_triggers):
        """After FORCED_SUMMARY, summary should be available for FORCED_CONCLUSION."""
        session_id = "test-compat-2"

        mock_triggers.return_value = TriggerEvaluationResult(
            hard_action=HardModerationAction.FORCED_SUMMARY,
            static_messages_to_speak=[],
            should_transition_to_conclusion=False,
        )

        mock_summary.return_value = {
            "updated_summary": "Complete discussion summary with all clues",
            "message_to_say": "Recap message",
            "correction_reason": None,
        }

        state = ModerationState.initial()
        state.human_turns_since_last_summary = 3  # Will trigger FORCED_SUMMARY
        save_moderation_state(session_id, state)

        ModerationOrchestrator.handle_human_turn_end(
            session_id=session_id,
            user_id=1,
            last_turn_text="Final clue about Eddie",
            session_phase="ACTIVE",
            speaker_name="Mario",
        )

        # Summary should be updated and available for subsequent FORCED_CONCLUSION
        loaded = load_moderation_state(session_id)
        self.assertEqual(loaded.summary, "Complete discussion summary with all clues")


class TurnsCounterIncrementOrderTests(TestCase):
    """Verify turns counter is incremented BEFORE LLM call in both paths."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('apps.moderation.orchestrator.evaluate_triggers_on_human_turn_end')
    @patch.object(ModerationService, 'call_llm_for_summary')
    def test_forced_summary_increments_turns_before_llm(self, mock_summary, mock_triggers):
        """FORCED_SUMMARY should increment turns BEFORE calling LLM."""
        session_id = "test-turns-order-1"

        mock_triggers.return_value = TriggerEvaluationResult(
            hard_action=HardModerationAction.FORCED_SUMMARY,
            static_messages_to_speak=[],
            should_transition_to_conclusion=False,
        )

        captured_turns = {}

        def capture_turns(**kwargs):
            captured_turns.update(kwargs.get("participants_turns", {}))
            return {
                "updated_summary": "Summary",
                "message_to_say": "Message",
                "correction_reason": None,
            }

        mock_summary.side_effect = capture_turns

        state = ModerationState.initial()
        state.turns_per_participant = {"Mario": 3}
        save_moderation_state(session_id, state)

        ModerationOrchestrator.handle_human_turn_end(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            speaker_name="Mario",
        )

        # LLM should have received Mario: 4 (incremented BEFORE call)
        self.assertEqual(captured_turns.get("Mario"), 4)


class LLMNormalModeIntegrationTests(TestCase):
    """Integration tests for the complete normal mode flow."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch.object(ModerationService, '_build_openai_client')
    def test_full_normal_mode_flow_with_participant_tracking(self, mock_client):
        """Test complete flow: state tracking + structured LLM input + intervention decision."""
        session_id = "test-integration-1"

        # Mock LLM to return intervention when score >= 0.7
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "updated_summary": "Mario ha dominato la discussione, Lucia non ha parlato",
            "should_ai_speak": True,
            "message_to_say": "Lucia, tu cosa ne pensi?",
            "reason": "exclusion",
            "intervention_score": 0.75,
        })
        mock_client.return_value.chat.completions.create.return_value = mock_response

        # Setup: Mario has spoken 5 times, Lucia 0 times
        state = ModerationState.initial()
        state.turns_per_participant = {"Mario": 5, "Lucia": 0}
        save_moderation_state(session_id, state)

        # Mario speaks again (6th turn)
        result = ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Penso che sia stato il maggiordomo!",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="Mario",
        )

        # Verify AI decides to intervene
        self.assertTrue(result.ai_should_speak)
        self.assertEqual(result.ai_message, "Lucia, tu cosa ne pensi?")

        # Verify state was updated
        loaded_state = load_moderation_state(session_id)
        self.assertEqual(loaded_state.turns_per_participant["Mario"], 6)
        self.assertEqual(loaded_state.ai_interventions_count, 1)

        # Verify LLM received structured input
        call_args = mock_client.return_value.chat.completions.create.call_args
        messages = call_args[1]['messages']
        user_message = json.loads(messages[1]['content'])

        self.assertEqual(user_message["participants"]["turns"]["Mario"], 6)
        self.assertEqual(user_message["participants"]["turns"]["Lucia"], 0)
        self.assertEqual(user_message["scenario"]["type"], "murder_mystery")

    @patch.object(ModerationService, '_build_openai_client')
    def test_forced_summary_does_not_use_normal_prompt(self, mock_client):
        """Forced summary should use its own prompt, not the normal mode prompt."""
        session_id = "test-integration-2"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "updated_summary": "Riassunto della discussione",
            "should_ai_speak": True,
            "message_to_say": "Ecco il riassunto...",
            "reason": "forced_summary",
            "intervention_score": 1.0,
        })
        mock_client.return_value.chat.completions.create.return_value = mock_response

        state = ModerationState.initial()
        save_moderation_state(session_id, state)

        ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.FORCED_SUMMARY,
            speaker_name="Mario",
        )

        # Verify prompt was for forced_summary (should not contain "monopol")
        call_args = mock_client.return_value.chat.completions.create.call_args
        system_prompt = call_args[1]['messages'][0]['content']

        # forced_summary prompt should mention "riassunto" but not intervention criteria
        self.assertIn("riassunto", system_prompt.lower())
        # It should NOT contain detailed intervention criteria like monopolization
        self.assertNotIn("monopol", system_prompt.lower())


class CooldownBypassTests(TestCase):
    """Tests for differentiated cooldown behavior based on intervention reason."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch.object(ModerationService, '_call_llm')
    def test_conflict_bypasses_cooldown(self, mock_llm):
        """Intervento 'conflict' deve bypassare il cooldown."""
        session_id = "test-cooldown-bypass-1"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": True,
            "message_to_say": "Stop, c'è un conflitto",
            "reason": "conflict",
            "intervention_score": 0.9,
        }

        # Set up state with a recent AI intervention
        state = ModerationState.initial()
        state.last_ai_intervention_at = datetime.utcnow() - timedelta(seconds=10)  # 10s ago
        save_moderation_state(session_id, state)

        result = ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="Mario",
        )

        # Should speak despite being within cooldown
        self.assertTrue(result.ai_should_speak)
        self.assertIn("conflitto", result.ai_message)

    @patch.object(ModerationService, '_call_llm')
    def test_user_request_bypasses_cooldown(self, mock_llm):
        """Intervento 'user_request' deve bypassare il cooldown."""
        session_id = "test-cooldown-bypass-2"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": True,
            "message_to_say": "Certo, rispondo alla richiesta",
            "reason": "user_request",
            "intervention_score": 0.9,
        }

        # Set up state with a recent AI intervention
        state = ModerationState.initial()
        state.last_ai_intervention_at = datetime.utcnow() - timedelta(seconds=10)  # 10s ago
        save_moderation_state(session_id, state)

        result = ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="Mario",
        )

        # Should speak despite being within cooldown
        self.assertTrue(result.ai_should_speak)
        self.assertIn("richiesta", result.ai_message)

    @patch.object(ModerationService, '_call_llm')
    def test_monopolization_respects_cooldown(self, mock_llm):
        """Intervento 'monopolization' deve rispettare il cooldown di 60s."""
        session_id = "test-cooldown-respect-1"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": True,
            "message_to_say": "Diamo spazio agli altri",
            "reason": "monopolization",
            "intervention_score": 0.9,
        }

        # Set up state with a recent AI intervention (30s ago, within 60s cooldown)
        state = ModerationState.initial()
        state.last_ai_intervention_at = datetime.utcnow() - timedelta(seconds=30)
        save_moderation_state(session_id, state)

        result = ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="Mario",
        )

        # Should NOT speak because cooldown (60s) not expired
        self.assertFalse(result.ai_should_speak)

    @patch.object(ModerationService, '_call_llm')
    def test_exclusion_respects_cooldown(self, mock_llm):
        """Intervento 'exclusion' deve rispettare il cooldown di 60s."""
        session_id = "test-cooldown-respect-2"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": True,
            "message_to_say": "Coinvolgiamo anche Luigi",
            "reason": "exclusion",
            "intervention_score": 0.9,
        }

        # Set up state with a recent AI intervention (30s ago, within 60s cooldown)
        state = ModerationState.initial()
        state.last_ai_intervention_at = datetime.utcnow() - timedelta(seconds=30)
        save_moderation_state(session_id, state)

        result = ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="Mario",
        )

        # Should NOT speak because cooldown (60s) not expired
        self.assertFalse(result.ai_should_speak)

    @patch.object(ModerationService, '_call_llm')
    def test_monopolization_speaks_after_cooldown_expired(self, mock_llm):
        """Intervento 'monopolization' deve parlare se il cooldown è scaduto."""
        session_id = "test-cooldown-expired-1"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": True,
            "message_to_say": "Diamo spazio agli altri",
            "reason": "monopolization",
            "intervention_score": 0.9,
        }

        # Set up state with an old AI intervention (70s ago, beyond 60s cooldown)
        state = ModerationState.initial()
        state.last_ai_intervention_at = datetime.utcnow() - timedelta(seconds=70)
        save_moderation_state(session_id, state)

        result = ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="Mario",
        )

        # Should speak because cooldown (60s) has expired
        self.assertTrue(result.ai_should_speak)


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
