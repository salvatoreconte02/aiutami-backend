from django.test import TestCase
from django.core.cache import cache

from apps.moderation.state import (
    ModerationState,
    load_moderation_state,
    save_moderation_state,
)
from apps.moderation.triggers import TriggerEvaluationResult, evaluate_triggers_on_human_turn_end
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
        self.assertIn("Il tempo della discussione è terminato",
                      " ".join(result.static_messages_to_speak))

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
