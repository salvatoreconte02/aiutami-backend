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


from django.contrib.auth import get_user_model
from apps.sessions.models import Session, SessionParticipant


class RequestSpeakBlockedDuringIntroTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user(username="testuser", password="test123")
        self.session = Session.objects.create(
            host=self.user,
            title="Test Session",
            context="MURDER_MYSTERY",
            min_size=3,
            max_size=3,
        )
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


class RequestReserveBlockedDuringIntroTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user(username="testuser2", password="test123")
        self.session = Session.objects.create(
            host=self.user,
            title="Test Session",
            context="MURDER_MYSTERY",
            min_size=3,
            max_size=3,
        )
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
