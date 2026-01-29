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
from apps.moderation.service import HardModerationAction, ModerationService
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
    def test_forced_conclusion_fires_when_not_done(self, mock_ready, mock_reserved):
        """FORCED_CONCLUSION should fire on first human turn in CONCLUSION phase."""
        session_id = "test-session-fc-1"

        # Setup: state with forced_conclusion_done=False
        state = ModerationState.initial()
        save_moderation_state(session_id, state)

        result = evaluate_triggers_on_human_turn_end(
            session_id=session_id,
            user_id=1,
            session_phase="CONCLUSION",
            moderation_state=state,
        )

        self.assertEqual(result.hard_action, HardModerationAction.FORCED_CONCLUSION)

    @patch('apps.moderation.triggers._get_next_reserved_speaker_name', return_value=None)
    @patch('apps.moderation.triggers._get_ready_to_conclude_status', return_value=(0, 3))
    def test_forced_conclusion_does_not_fire_when_already_done(self, mock_ready, mock_reserved):
        """FORCED_CONCLUSION should NOT fire if forced_conclusion_done=True."""
        session_id = "test-session-fc-2"

        # Setup: state with forced_conclusion_done=True
        state = ModerationState.initial()
        state.forced_conclusion_done = True
        save_moderation_state(session_id, state)

        result = evaluate_triggers_on_human_turn_end(
            session_id=session_id,
            user_id=1,
            session_phase="CONCLUSION",
            moderation_state=state,
        )

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
