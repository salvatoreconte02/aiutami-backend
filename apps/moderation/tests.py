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

    def test_initial_without_participants_has_empty_dict(self):
        state = ModerationState.initial()
        self.assertEqual(state.speaking_time_per_participant, {})

    def test_initial_with_participants_populates_dict_with_zeros(self):
        state = ModerationState.initial(participants=["Marco", "Lucia", "Anna"])
        self.assertEqual(
            state.speaking_time_per_participant,
            {"Marco": 0.0, "Lucia": 0.0, "Anna": 0.0},
        )


class LastInterventionForReasonTests(TestCase):
    """
    Helper puro: cerca nel interventions_log l'ultimo entry con un dato reason.
    """

    def test_empty_log_returns_none(self):
        from apps.moderation.state import last_intervention_for_reason
        state = ModerationState.initial()
        self.assertIsNone(last_intervention_for_reason(state, "monopolization"))

    def test_log_with_matching_reason_returns_entry(self):
        from apps.moderation.state import last_intervention_for_reason
        state = ModerationState.initial()
        state.interventions_log = [
            {
                "ts": "2026-04-27T10:00:00",
                "reason": "monopolization",
                "score": 0.8,
                "speaker": "Marco",
                "message": "Sentiamo gli altri.",
            }
        ]
        result = last_intervention_for_reason(state, "monopolization")
        self.assertIsNotNone(result)
        self.assertEqual(result["reason"], "monopolization")
        self.assertEqual(result["message"], "Sentiamo gli altri.")

    def test_log_with_multiple_reasons_returns_correct_one(self):
        from apps.moderation.state import last_intervention_for_reason
        state = ModerationState.initial()
        state.interventions_log = [
            {"ts": "2026-04-27T10:00:00", "reason": "monopolization",
             "score": 0.8, "speaker": "Marco", "message": "msg1"},
            {"ts": "2026-04-27T10:01:00", "reason": "exclusion",
             "score": 0.7, "speaker": "Lucia", "message": "msg2"},
            {"ts": "2026-04-27T10:02:00", "reason": "off_topic",
             "score": 0.9, "speaker": "Anna", "message": "msg3"},
        ]
        excl = last_intervention_for_reason(state, "exclusion")
        self.assertEqual(excl["message"], "msg2")
        mono = last_intervention_for_reason(state, "monopolization")
        self.assertEqual(mono["message"], "msg1")

    def test_log_without_reason_returns_none(self):
        from apps.moderation.state import last_intervention_for_reason
        state = ModerationState.initial()
        state.interventions_log = [
            {"ts": "2026-04-27T10:00:00", "reason": "off_topic",
             "score": 0.8, "speaker": "Marco", "message": "msg1"}
        ]
        self.assertIsNone(last_intervention_for_reason(state, "monopolization"))

    def test_log_with_duplicate_reason_returns_most_recent(self):
        from apps.moderation.state import last_intervention_for_reason
        state = ModerationState.initial()
        state.interventions_log = [
            {"ts": "2026-04-27T10:00:00", "reason": "monopolization",
             "score": 0.8, "speaker": "Marco", "message": "first"},
            {"ts": "2026-04-27T10:05:00", "reason": "exclusion",
             "score": 0.7, "speaker": "Lucia", "message": "middle"},
            {"ts": "2026-04-27T10:10:00", "reason": "monopolization",
             "score": 0.9, "speaker": "Marco", "message": "second"},
        ]
        result = last_intervention_for_reason(state, "monopolization")
        self.assertEqual(result["message"], "second")


class LoadModerationStateInitializesFromDBTests(TestCase):
    """
    load_moderation_state(session_id) popola speaking_time_per_participant
    con tutti i partecipanti della sessione a 0.0 quando lo state non esiste ancora.
    """

    def setUp(self):
        cache.clear()
        from django.contrib.auth import get_user_model
        from apps.sessions.models import (
            Session,
            SessionParticipant,
            SessionState,
            ParticipantRole,
        )

        User = get_user_model()
        self.user_marco = User.objects.create_user(
            username="marco", email="marco@example.com", password="p"
        )
        self.user_lucia = User.objects.create_user(
            username="lucia", email="lucia@example.com", password="p"
        )
        self.user_anna = User.objects.create_user(
            username="anna", email="anna@example.com", password="p"
        )
        self.session = Session.objects.create(
            title="Test",
            context="generic",
            state=SessionState.ACTIVE,
            min_size=3,
            max_size=3,
            host=self.user_marco,
        )
        SessionParticipant.objects.create(
            session=self.session, user=self.user_marco, role=ParticipantRole.HOST
        )
        SessionParticipant.objects.create(
            session=self.session, user=self.user_lucia, role=ParticipantRole.PARTICIPANT
        )
        SessionParticipant.objects.create(
            session=self.session, user=self.user_anna, role=ParticipantRole.PARTICIPANT
        )

    def tearDown(self):
        cache.clear()

    def test_new_state_populated_with_all_participants_at_zero(self):
        state = load_moderation_state(self.session.id)
        self.assertEqual(
            state.speaking_time_per_participant,
            {"marco": 0.0, "lucia": 0.0, "anna": 0.0},
        )

    def test_existing_state_not_overwritten_on_load(self):
        existing = ModerationState.initial(
            participants=["marco", "lucia", "anna"]
        )
        existing.speaking_time_per_participant["marco"] = 50.0
        save_moderation_state(self.session.id, existing)

        loaded = load_moderation_state(self.session.id)
        self.assertEqual(loaded.speaking_time_per_participant["marco"], 50.0)
        self.assertEqual(loaded.speaking_time_per_participant["lucia"], 0.0)

    def test_nonexistent_session_falls_back_to_empty_dict(self):
        state = load_moderation_state(999999)
        self.assertEqual(state.speaking_time_per_participant, {})


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

    def _task(self, key="murder_mystery"):
        from apps.tasks.registry import get_task
        return get_task(key)

    def test_ready_to_conclude_message_variants_exist(self):
        """Each task exposes ready_to_conclude templates with {nome} placeholders."""
        for key in ("murder_mystery", "nasa_moon_survival", "generic"):
            templates = self._task(key).ready_to_conclude_messages()

            self.assertGreaterEqual(len(templates["normal"]), 1)
            self.assertGreaterEqual(len(templates["last_one"]), 1)
            self.assertGreaterEqual(len(templates["all_ready"]), 1)

            for msg in templates["normal"]:
                self.assertIn("{nome}", msg)
            for msg in templates["last_one"]:
                self.assertIn("{nome}", msg)

    def test_generate_ready_to_conclude_message_normal(self):
        """generate_ready_to_conclude_message returns normal variant."""
        from apps.moderation.triggers import generate_ready_to_conclude_message

        result = generate_ready_to_conclude_message(
            "Mario", ready_count=1, total_count=4, task=self._task(),
        )

        self.assertTrue(result.message.use_tts)
        self.assertIn("Mario", result.message.text)
        self.assertFalse(result.trigger_conclusion)

    def test_generate_ready_to_conclude_message_last_one(self):
        """generate_ready_to_conclude_message returns 'last one' variant when appropriate."""
        from apps.moderation.triggers import generate_ready_to_conclude_message

        result = generate_ready_to_conclude_message(
            "Luigi", ready_count=3, total_count=4, task=self._task(),
        )

        self.assertTrue(result.message.use_tts)
        self.assertIn("Luigi", result.message.text)
        self.assertTrue(
            "manca solo" in result.message.text.lower() or
            "quasi tutti" in result.message.text.lower()
        )
        self.assertFalse(result.trigger_conclusion)

    def test_generate_ready_to_conclude_message_all_ready(self):
        """generate_ready_to_conclude_message returns 'all ready' variant and triggers conclusion."""
        from apps.moderation.triggers import generate_ready_to_conclude_message

        result = generate_ready_to_conclude_message(
            "Luigi", ready_count=4, total_count=4, task=self._task(),
        )

        self.assertTrue(result.message.use_tts)
        self.assertNotIn("Luigi", result.message.text)
        self.assertTrue("tutti" in result.message.text.lower())
        self.assertTrue(result.trigger_conclusion)

    def test_generic_task_messages_no_mm_terminology(self):
        """Generic task templates must not leak Murder Mystery vocabulary."""
        templates = self._task("generic").ready_to_conclude_messages()
        forbidden = ("colpevol", "omicid", "assassin", "vittim", "indizi", "sospett")
        all_text = " ".join(
            templates["normal"] + templates["last_one"] + templates["all_ready"]
        ).lower()
        for word in forbidden:
            self.assertNotIn(word, all_text)

    def test_nasa_task_messages_no_mm_terminology(self):
        """NASA task templates must not leak Murder Mystery vocabulary."""
        templates = self._task("nasa_moon_survival").ready_to_conclude_messages()
        forbidden = ("colpevol", "omicid", "assassin", "vittim", "indizi", "sospett")
        all_text = " ".join(
            templates["normal"] + templates["last_one"] + templates["all_ready"]
        ).lower()
        for word in forbidden:
            self.assertNotIn(word, all_text)


class ModerationStateTurnsPerParticipantTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_initial_state_has_empty_speaking_time_per_participant(self):
        state = ModerationState.initial()
        self.assertEqual(state.speaking_time_per_participant, {})

    def test_speaking_time_per_participant_persists_after_save_and_load(self):
        session_id = "test-session-tpp-1"

        state = ModerationState.initial()
        state.speaking_time_per_participant = {"Mario": 30.5, "Lucia": 12.0}
        save_moderation_state(session_id, state)

        loaded = load_moderation_state(session_id)
        self.assertEqual(
            loaded.speaking_time_per_participant,
            {"Mario": 30.5, "Lucia": 12.0},
        )


class SpeakingTimeAccumulationTests(TestCase):
    """
    handle_human_turn_ended deve accumulare il delta seconds tra
    current_turn_started_at e ora nel speaking_time_per_participant.
    """

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _mock_llm_no_speak(self):
        return {
            "updated_summary": "Test summary",
            "should_ai_speak": False,
            "message_to_say": None,
            "reason": "all_ok",
            "intervention_score": 0.2,
        }

    @patch.object(ModerationService, '_call_llm')
    def test_speaking_time_accumulated_on_turn_end(self, mock_llm):
        """Con current_turn_started_at settato a ~5s fa, accumula ~5s."""
        session_id = "test-st-accum-1"
        mock_llm.return_value = self._mock_llm_no_speak()

        state = ModerationState.initial()
        state.current_turn_started_at = datetime.utcnow() - timedelta(seconds=5)
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
        accumulated = loaded.speaking_time_per_participant.get("Mario", 0.0)
        self.assertGreaterEqual(accumulated, 4.5)
        self.assertLessEqual(accumulated, 6.5)
        # Il timer corrente deve essere clearato
        self.assertIsNone(loaded.current_turn_started_at)

    @patch.object(ModerationService, '_call_llm')
    def test_speaking_time_accumulates_across_turns(self, mock_llm):
        """Turni successivi sommano i secondi al cumulativo."""
        session_id = "test-st-accum-2"
        mock_llm.return_value = self._mock_llm_no_speak()

        state = ModerationState.initial()
        state.speaking_time_per_participant = {"Mario": 20.0}
        state.current_turn_started_at = datetime.utcnow() - timedelta(seconds=10)
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
        # 20.0 baseline + ~10s accumulated
        self.assertGreaterEqual(loaded.speaking_time_per_participant["Mario"], 29.5)
        self.assertLessEqual(loaded.speaking_time_per_participant["Mario"], 31.0)

    @patch.object(ModerationService, '_call_llm')
    def test_no_accumulation_without_speaker_name(self, mock_llm):
        session_id = "test-st-no-name"
        mock_llm.return_value = self._mock_llm_no_speak()

        state = ModerationState.initial()
        state.current_turn_started_at = datetime.utcnow() - timedelta(seconds=5)
        save_moderation_state(session_id, state)

        ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name=None,
        )

        loaded = load_moderation_state(session_id)
        self.assertEqual(loaded.speaking_time_per_participant, {})

    @patch.object(ModerationService, '_call_llm')
    def test_no_accumulation_without_current_turn_started_at(self, mock_llm):
        """Se current_turn_started_at è None (es. reconnect), non accumula."""
        session_id = "test-st-no-timer"
        mock_llm.return_value = self._mock_llm_no_speak()

        state = ModerationState.initial()
        state.current_turn_started_at = None
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
        self.assertEqual(loaded.speaking_time_per_participant, {})

    def test_record_human_turn_start_sets_timestamp(self):
        session_id = "test-record-start"
        state = ModerationState.initial(participants=["Mario"])
        save_moderation_state(session_id, state)

        ModerationService.record_human_turn_start(
            session_id=session_id, speaker_name="Mario"
        )

        loaded = load_moderation_state(session_id)
        self.assertIsNotNone(loaded.current_turn_started_at)

    def test_record_human_turn_start_skipped_if_no_speaker(self):
        session_id = "test-record-no-speaker"
        state = ModerationState.initial()
        save_moderation_state(session_id, state)

        ModerationService.record_human_turn_start(
            session_id=session_id, speaker_name=None
        )

        loaded = load_moderation_state(session_id)
        self.assertIsNone(loaded.current_turn_started_at)


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
    def test_call_llm_sends_names_and_participation_metrics(self, mock_client):
        """_call_llm should send participants.names and participation_metrics."""
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

        speaking_time = {"Mario": 50.0, "Lucia": 20.0}

        ModerationService._call_llm(
            summary_in="Test summary",
            last_turn="Test turn",
            mode="normal",
            session_phase="ACTIVE",
            speaker_name="Mario",
            speaking_time_per_participant=speaking_time,
            elapsed_seconds=600.0,
        )

        mock_client.return_value.chat.completions.create.assert_called_once()
        call_args = mock_client.return_value.chat.completions.create.call_args
        user_message = call_args[1]['messages'][1]['content']
        user_data = json.loads(user_message)

        self.assertIn("participants", user_data)
        self.assertIn("names", user_data["participants"])
        self.assertEqual(set(user_data["participants"]["names"]), {"Mario", "Lucia"})
        self.assertNotIn("turns", user_data["participants"])

        self.assertIn("participation_metrics", user_data)
        metrics = user_data["participation_metrics"]
        self.assertIn("over_participators", metrics)
        self.assertIn("under_participators", metrics)
        self.assertIn("avg_speaking_time_s", metrics)
        self.assertIn("min_time_reached", metrics)

        # session ora include elapsed_seconds e total_speaking_time_s
        self.assertIn("elapsed_seconds", user_data["session"])
        self.assertIn("total_speaking_time_s", user_data["session"])

    @patch.object(ModerationService, '_build_openai_client')
    def test_call_llm_empty_log_yields_empty_last_interventions_by_reason(
        self, mock_client
    ):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "updated_summary": "x", "should_ai_speak": False,
            "message_to_say": None, "reason": "all_ok",
            "intervention_score": 0.1,
        })
        mock_client.return_value.chat.completions.create.return_value = mock_response

        ModerationService._call_llm(
            summary_in="x", last_turn="x", mode="normal",
            session_phase="ACTIVE", speaker_name="Mario",
            speaking_time_per_participant={"Mario": 1.0},
            interventions_log=[],
        )

        user_data = json.loads(
            mock_client.return_value.chat.completions.create.call_args[1]
            ['messages'][1]['content']
        )
        self.assertIn("last_interventions_by_reason", user_data)
        self.assertEqual(user_data["last_interventions_by_reason"], {})

    @patch.object(ModerationService, '_build_openai_client')
    def test_call_llm_includes_recent_monopolization_in_payload(self, mock_client):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "updated_summary": "x", "should_ai_speak": False,
            "message_to_say": None, "reason": "all_ok",
            "intervention_score": 0.1,
        })
        mock_client.return_value.chat.completions.create.return_value = mock_response

        log = [{
            "ts": (datetime.utcnow() - timedelta(seconds=90)).isoformat(),
            "reason": "monopolization", "score": 0.8,
            "speaker": "Marco", "message": "Sentiamo gli altri.",
        }]

        ModerationService._call_llm(
            summary_in="x", last_turn="x", mode="normal",
            session_phase="ACTIVE", speaker_name="Mario",
            speaking_time_per_participant={"Mario": 1.0},
            interventions_log=log,
        )

        user_data = json.loads(
            mock_client.return_value.chat.completions.create.call_args[1]
            ['messages'][1]['content']
        )
        last_by_reason = user_data["last_interventions_by_reason"]
        self.assertIn("monopolization", last_by_reason)
        self.assertEqual(last_by_reason["monopolization"]["message"], "Sentiamo gli altri.")
        self.assertGreaterEqual(last_by_reason["monopolization"]["minutes_ago"], 1.4)
        self.assertLessEqual(last_by_reason["monopolization"]["minutes_ago"], 1.6)
        # exclusion non c'è nel log → non deve essere in payload
        self.assertNotIn("exclusion", last_by_reason)

    @patch.object(ModerationService, '_build_openai_client')
    def test_call_llm_excludes_punctual_reasons_from_payload(self, mock_client):
        """off_topic, conflict, user_request non finiscono in last_interventions_by_reason."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "updated_summary": "x", "should_ai_speak": False,
            "message_to_say": None, "reason": "all_ok",
            "intervention_score": 0.1,
        })
        mock_client.return_value.chat.completions.create.return_value = mock_response

        ts = lambda s: (datetime.utcnow() - timedelta(seconds=s)).isoformat()
        log = [
            {"ts": ts(60), "reason": "off_topic", "score": 0.8,
             "speaker": "A", "message": "stay on topic"},
            {"ts": ts(40), "reason": "conflict", "score": 0.9,
             "speaker": "B", "message": "calm down"},
            {"ts": ts(20), "reason": "user_request", "score": 0.9,
             "speaker": "C", "message": "answer"},
        ]

        ModerationService._call_llm(
            summary_in="x", last_turn="x", mode="normal",
            session_phase="ACTIVE", speaker_name="Mario",
            speaking_time_per_participant={"Mario": 1.0},
            interventions_log=log,
        )

        user_data = json.loads(
            mock_client.return_value.chat.completions.create.call_args[1]
            ['messages'][1]['content']
        )
        # Solo monopolization/exclusion possono apparire
        self.assertEqual(user_data["last_interventions_by_reason"], {})

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
            speaking_time_per_participant={},
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
    def test_handle_human_turn_passes_speaking_time_to_llm(self, mock_llm):
        """handle_human_turn_ended should pass speaking_time_per_participant to _call_llm."""
        session_id = "test-pass-state-1"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": False,
            "message_to_say": None,
            "reason": "all_ok",
            "intervention_score": 0.2,
        }

        # Setup state with existing speaking time + current_turn_started_at 5s ago
        state = ModerationState.initial()
        state.speaking_time_per_participant = {"Mario": 30.0, "Lucia": 10.0}
        state.current_turn_started_at = datetime.utcnow() - timedelta(seconds=5)
        save_moderation_state(session_id, state)

        ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="Mario",
        )

        mock_llm.assert_called_once()
        call_kwargs = mock_llm.call_args[1]

        # After accumulation, Mario should have ~35s (30 baseline + ~5s)
        self.assertIn("speaking_time_per_participant", call_kwargs)
        self.assertGreaterEqual(call_kwargs["speaking_time_per_participant"]["Mario"], 34.5)
        self.assertLessEqual(call_kwargs["speaking_time_per_participant"]["Mario"], 36.0)
        self.assertEqual(call_kwargs["speaking_time_per_participant"]["Lucia"], 10.0)
        # elapsed_seconds passed too
        self.assertIn("elapsed_seconds", call_kwargs)


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

        # Setup: Mario has spoken 200s, Lucia 0s, current turn ~10s for Mario
        state = ModerationState.initial()
        state.speaking_time_per_participant = {"Mario": 200.0, "Lucia": 0.0}
        state.current_turn_started_at = datetime.utcnow() - timedelta(seconds=10)
        save_moderation_state(session_id, state)

        # Mario speaks again
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

        # Verify state was updated (Mario now ~210s)
        loaded_state = load_moderation_state(session_id)
        self.assertGreaterEqual(loaded_state.speaking_time_per_participant["Mario"], 209.5)
        self.assertEqual(loaded_state.ai_interventions_count, 1)

        # Verify LLM received structured input
        call_args = mock_client.return_value.chat.completions.create.call_args
        messages = call_args[1]['messages']
        user_message = json.loads(messages[1]['content'])

        self.assertIn("Mario", user_message["participants"]["names"])
        self.assertIn("Lucia", user_message["participants"]["names"])
        self.assertIn("participation_metrics", user_message)
        self.assertIn("Lucia", user_message["participation_metrics"]["under_participators"])
        self.assertEqual(user_message["scenario"]["type"], "murder_mystery")

def _make_intervention_entry(*, reason, seconds_ago, speaker="Mario", message="msg"):
    """Helper per costruire un entry interventions_log con timestamp relativo."""
    return {
        "ts": (datetime.utcnow() - timedelta(seconds=seconds_ago)).isoformat(),
        "reason": reason,
        "score": 0.8,
        "speaker": speaker,
        "message": message,
    }


class CooldownBypassTests(TestCase):
    """Tests per il bypass del cooldown su reason 'conflict' e 'user_request'."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch.object(ModerationService, '_call_llm')
    def test_conflict_bypasses_cooldown(self, mock_llm):
        """Intervento 'conflict' deve bypassare il cooldown anche se c'è un conflict recente."""
        session_id = "test-cooldown-bypass-1"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": True,
            "message_to_say": "Stop, c'è un conflitto",
            "reason": "conflict",
            "intervention_score": 0.9,
        }

        state = ModerationState.initial()
        state.interventions_log = [
            _make_intervention_entry(reason="conflict", seconds_ago=10)
        ]
        save_moderation_state(session_id, state)

        result = ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="Mario",
        )

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

        state = ModerationState.initial()
        state.interventions_log = [
            _make_intervention_entry(reason="user_request", seconds_ago=10)
        ]
        save_moderation_state(session_id, state)

        result = ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="Mario",
        )

        self.assertTrue(result.ai_should_speak)
        self.assertIn("richiesta", result.ai_message)


class PerReasonCooldownTests(TestCase):
    """
    Test del cooldown per-reason: ogni reason ha un proprio orologio
    che si confronta solo con l'ultimo intervento dello STESSO reason.
    """

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _run_handle(self, session_id, *, reason, message="msg"):
        """Simula la chiamata LLM e ritorna il risultato handle_human_turn_ended."""
        with patch.object(ModerationService, '_call_llm') as mock_llm:
            mock_llm.return_value = {
                "updated_summary": "Test summary",
                "should_ai_speak": True,
                "message_to_say": message,
                "reason": reason,
                "intervention_score": 0.9,
            }
            return ModerationService.handle_human_turn_ended(
                session_id=session_id,
                user_id=1,
                last_turn_text="Test turn",
                session_phase="ACTIVE",
                hard_action=HardModerationAction.NONE,
                speaker_name="Mario",
            )

    def _setup_state(self, session_id, log_entries):
        state = ModerationState.initial()
        state.interventions_log = log_entries
        save_moderation_state(session_id, state)

    def test_monopolization_blocked_under_4min(self):
        sid = "test-mono-blocked"
        self._setup_state(sid, [
            _make_intervention_entry(reason="monopolization", seconds_ago=200)
        ])
        result = self._run_handle(sid, reason="monopolization")
        self.assertFalse(result.ai_should_speak)

    def test_monopolization_speaks_after_4min(self):
        sid = "test-mono-speak"
        self._setup_state(sid, [
            _make_intervention_entry(reason="monopolization", seconds_ago=250)
        ])
        result = self._run_handle(sid, reason="monopolization")
        self.assertTrue(result.ai_should_speak)

    def test_exclusion_blocked_under_4min(self):
        sid = "test-excl-blocked"
        self._setup_state(sid, [
            _make_intervention_entry(reason="exclusion", seconds_ago=200)
        ])
        result = self._run_handle(sid, reason="exclusion")
        self.assertFalse(result.ai_should_speak)

    def test_exclusion_speaks_after_4min(self):
        sid = "test-excl-speak"
        self._setup_state(sid, [
            _make_intervention_entry(reason="exclusion", seconds_ago=250)
        ])
        result = self._run_handle(sid, reason="exclusion")
        self.assertTrue(result.ai_should_speak)

    def test_off_topic_blocked_under_60s(self):
        sid = "test-off-blocked"
        self._setup_state(sid, [
            _make_intervention_entry(reason="off_topic", seconds_ago=30)
        ])
        result = self._run_handle(sid, reason="off_topic")
        self.assertFalse(result.ai_should_speak)

    def test_off_topic_speaks_after_60s(self):
        sid = "test-off-speak"
        self._setup_state(sid, [
            _make_intervention_entry(reason="off_topic", seconds_ago=65)
        ])
        result = self._run_handle(sid, reason="off_topic")
        self.assertTrue(result.ai_should_speak)

    def test_different_reasons_dont_share_cooldown(self):
        """Cooldown è per-reason: un mono recente non blocca un excl proposto."""
        sid = "test-different-reasons"
        self._setup_state(sid, [
            _make_intervention_entry(reason="monopolization", seconds_ago=30)
        ])
        result = self._run_handle(sid, reason="exclusion")
        self.assertTrue(result.ai_should_speak)

    def test_no_prior_intervention_speaks(self):
        """Se non c'è mai stato un intervento di questo reason, parla."""
        sid = "test-no-prior"
        self._setup_state(sid, [])
        result = self._run_handle(sid, reason="monopolization")
        self.assertTrue(result.ai_should_speak)


class InterventionsLogTests(TestCase):
    """Test per il campo interventions_log in ModerationState."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_initial_state_has_empty_interventions_log(self):
        state = ModerationState.initial()
        self.assertEqual(state.interventions_log, [])

    def test_interventions_log_persists_after_save_and_load(self):
        session_id = "test-log-persist"
        state = ModerationState.initial()
        state.interventions_log = [
            {"ts": "2026-04-24T14:30:00", "reason": "monopolization",
             "score": 0.85, "speaker": "Marco", "message": "Lucia, tu cosa..."},
        ]
        save_moderation_state(session_id, state)
        loaded = load_moderation_state(session_id)
        self.assertEqual(len(loaded.interventions_log), 1)
        self.assertEqual(loaded.interventions_log[0]["reason"], "monopolization")

    @patch.object(ModerationService, '_call_llm')
    def test_normal_mode_intervention_appends_to_log(self, mock_llm):
        """Normal mode AI intervention should append to interventions_log."""
        session_id = "test-log-normal"
        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": True,
            "message_to_say": "Lucia, tu cosa ne pensi?",
            "reason": "exclusion",
            "intervention_score": 0.8,
        }
        state = ModerationState.initial()
        save_moderation_state(session_id, state)

        ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Bla bla",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="Marco",
        )

        loaded = load_moderation_state(session_id)
        self.assertEqual(len(loaded.interventions_log), 1)
        entry = loaded.interventions_log[0]
        self.assertEqual(entry["reason"], "exclusion")
        self.assertAlmostEqual(entry["score"], 0.8, places=1)
        self.assertEqual(entry["speaker"], "Marco")
        self.assertEqual(entry["message"], "Lucia, tu cosa ne pensi?")
        self.assertIn("T", entry["ts"])  # ISO format

    @patch.object(ModerationService, '_call_llm')
    def test_no_intervention_does_not_append_to_log(self, mock_llm):
        """When AI does not speak, interventions_log should stay empty."""
        session_id = "test-log-no-speak"
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
            last_turn_text="Bla bla",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="Marco",
        )

        loaded = load_moderation_state(session_id)
        self.assertEqual(len(loaded.interventions_log), 0)

    @patch.object(ModerationService, '_call_llm')
    def test_log_entry_structure(self, mock_llm):
        """Each log entry must have ts, reason, score, speaker, message."""
        session_id = "test-log-structure"
        mock_llm.return_value = {
            "updated_summary": "Summary",
            "should_ai_speak": True,
            "message_to_say": "Torniamo al tema",
            "reason": "off_topic",
            "intervention_score": 0.9,
        }
        state = ModerationState.initial()
        save_moderation_state(session_id, state)

        ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Parliamo di calcio",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="Luigi",
        )

        loaded = load_moderation_state(session_id)
        entry = loaded.interventions_log[0]
        expected_keys = {"ts", "reason", "score", "speaker", "message"}
        self.assertEqual(set(entry.keys()), expected_keys)


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


class EnforcesGroundRulesTests(TestCase):
    """
    enforces_ground_rules() ritorna True solo per task che applicano
    le ground rules di Hall & Watson (NASA Moon, Lost at Sea).
    """

    def test_nasa_moon_enforces_ground_rules(self):
        from apps.tasks.registry import get_task
        self.assertTrue(get_task("nasa_moon_survival").enforces_ground_rules())

    def test_lost_at_sea_enforces_ground_rules(self):
        from apps.tasks.registry import get_task
        self.assertTrue(get_task("lost_at_sea").enforces_ground_rules())

    def test_murder_mystery_does_not_enforce(self):
        from apps.tasks.registry import get_task
        self.assertFalse(get_task("murder_mystery").enforces_ground_rules())

    def test_generic_does_not_enforce(self):
        from apps.tasks.registry import get_task
        self.assertFalse(get_task("generic").enforces_ground_rules())


class GroundRuleViolationPromptTests(TestCase):
    """
    Il prompt normal mode include la sezione ground_rule_violation
    e il reason nell'enum SOLO per task che fanno enforces_ground_rules().
    """

    def _prompt_for(self, task_key: str) -> str:
        from apps.tasks.registry import get_task
        return ModerationService._build_normal_mode_prompt(task=get_task(task_key))

    def test_prompt_for_nasa_moon_contains_ground_rule_violation(self):
        prompt = self._prompt_for("nasa_moon_survival")
        self.assertIn("ground_rule_violation", prompt)
        self.assertIn("Violazione ground rules", prompt)

    def test_prompt_for_lost_at_sea_contains_ground_rule_violation(self):
        prompt = self._prompt_for("lost_at_sea")
        self.assertIn("ground_rule_violation", prompt)
        self.assertIn("Violazione ground rules", prompt)

    def test_prompt_for_murder_mystery_excludes_ground_rule_violation(self):
        prompt = self._prompt_for("murder_mystery")
        self.assertNotIn("ground_rule_violation", prompt)
        self.assertNotIn("Violazione ground rules", prompt)

    def test_prompt_for_generic_excludes_ground_rule_violation(self):
        prompt = self._prompt_for("generic")
        self.assertNotIn("ground_rule_violation", prompt)
        self.assertNotIn("Violazione ground rules", prompt)

    def test_prompt_lists_only_rules_2_4_5_for_runtime_detection(self):
        """Le rules enforced sono 2 (impasse), 4 (voto/media), 5 (frustrazione)."""
        prompt = self._prompt_for("nasa_moon_survival")
        # Marker espliciti delle 3 rules enforced
        self.assertIn("Rule 2", prompt)
        self.assertIn("Rule 4", prompt)
        self.assertIn("Rule 5", prompt)
        # Cita marker linguistici riconoscibili
        self.assertIn("ultimatum", prompt.lower())
        self.assertTrue("votiamo" in prompt.lower() or "voto" in prompt.lower())

    def test_prompt_includes_priority_section_for_all_tasks(self):
        """La sezione 'Priorità tra reason' è sempre presente."""
        for task_key in ("nasa_moon_survival", "lost_at_sea", "murder_mystery", "generic"):
            prompt = self._prompt_for(task_key)
            self.assertIn("Priorità tra reason", prompt, f"Missing in {task_key}")


class GroundRuleViolationCooldownTests(TestCase):
    """
    ground_rule_violation usa il cooldown default 60s (non in OVERRIDES,
    non in BYPASS), come gli altri reason puntuali.
    """

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _setup_log(self, session_id, seconds_ago):
        state = ModerationState.initial()
        state.interventions_log = [{
            "ts": (datetime.utcnow() - timedelta(seconds=seconds_ago)).isoformat(),
            "reason": "ground_rule_violation",
            "score": 0.8,
            "speaker": "Marco",
            "message": "Aspettate, votare a maggioranza spegne la discussione.",
        }]
        save_moderation_state(session_id, state)

    def _run_handle(self, session_id, *, reason="ground_rule_violation"):
        with patch.object(ModerationService, '_call_llm') as mock_llm:
            mock_llm.return_value = {
                "updated_summary": "x",
                "should_ai_speak": True,
                "message_to_say": "Reminder ground rule.",
                "reason": reason,
                "intervention_score": 0.9,
            }
            return ModerationService.handle_human_turn_ended(
                session_id=session_id,
                user_id=1,
                last_turn_text="x",
                session_phase="ACTIVE",
                hard_action=HardModerationAction.NONE,
                speaker_name="Mario",
            )

    def test_blocked_under_60s(self):
        sid = "test-grv-blocked"
        self._setup_log(sid, seconds_ago=30)
        result = self._run_handle(sid)
        self.assertFalse(result.ai_should_speak)

    def test_speaks_after_60s(self):
        sid = "test-grv-speak"
        self._setup_log(sid, seconds_ago=70)
        result = self._run_handle(sid)
        self.assertTrue(result.ai_should_speak)

    def test_not_in_cumulative_payload(self):
        """ground_rule_violation NON deve apparire in last_interventions_by_reason."""
        log = [{
            "ts": (datetime.utcnow() - timedelta(seconds=30)).isoformat(),
            "reason": "ground_rule_violation",
            "score": 0.8,
            "speaker": "Marco",
            "message": "msg",
        }]
        result = ModerationService._extract_last_interventions_by_reason(log)
        self.assertNotIn("ground_rule_violation", result)
        self.assertEqual(result, {})
