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

    @patch.object(ModerationService, '_build_openai_client')
    def test_full_conclusion_flow_timer_expired(self, mock_client):
        """Test complete flow when timer expires."""
        # Setup mock LLM response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"updated_summary": "Final", "message_to_say": "Closing"}'
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
