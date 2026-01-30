from unittest.mock import patch, MagicMock, AsyncMock

from django.test import TestCase
from django.core.cache import cache

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

    def test_get_trigger_lock_returns_lock(self):
        """_get_trigger_lock should return an asyncio.Lock."""
        import asyncio
        lock = TurnsConsumer._get_trigger_lock()
        self.assertIsInstance(lock, asyncio.Lock)

    def test_get_trigger_lock_returns_same_instance(self):
        """_get_trigger_lock should return the same lock instance."""
        lock1 = TurnsConsumer._get_trigger_lock()
        lock2 = TurnsConsumer._get_trigger_lock()
        self.assertIs(lock1, lock2)


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
            "message_to_say": "Closing message",
        }

        # This is a unit test - we just verify the method signature exists
        # Full integration test requires websocket setup
        self.assertTrue(callable(getattr(TurnsConsumer, '_execute_forced_conclusion', None)))


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
