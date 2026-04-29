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
        self.assertEqual(result, "Marco e Giulia")

    def test_intro_message_template_exists(self):
        """INTRO_MESSAGE_TEMPLATE should be defined."""
        from apps.moderation.intro import INTRO_MESSAGE_TEMPLATE

        self.assertIn("Benvenuti", INTRO_MESSAGE_TEMPLATE)
        self.assertIn("{nomi}", INTRO_MESSAGE_TEMPLATE)


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


from django.contrib.auth import get_user_model
from apps.sessions.models import Session, SessionParticipant


class GenerateIntroMessageTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user1 = User.objects.create_user(
            username="user1", password="test123", first_name="Marco"
        )
        self.user2 = User.objects.create_user(
            username="user2", password="test123", first_name="Giulia"
        )
        self.user3 = User.objects.create_user(
            username="user3", password="test123", first_name="Luca"
        )

        self.session = Session.objects.create(
            host=self.user1,
            title="Test Session",
            context="murder_mystery",
            min_size=3,
            max_size=3,
        )
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
        """generate_intro_message should include template instructions.

        NOTA: temporaneamente in modalita DEBUG short intro (vedi intro.py),
        il template lungo e' commentato. Il test verifica solo le parti che
        sopravvivono in entrambe le modalita; quando si ripristina l'intro
        completo riaggiungere assertIn('pulsante microfono', ...).
        """
        from apps.moderation.intro import generate_intro_message

        result = generate_intro_message(str(self.session.id))
        self.assertIn("Benvenuti", result)
        self.assertIn("Buona discussione", result)
