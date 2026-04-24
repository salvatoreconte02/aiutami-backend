"""
Test per le metriche di valutazione empirica nel report:
- Gini index
- Sezione partecipazione nel PDF
- Gini nel fallback report
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from apps.sessions.models import Session, SessionParticipant, SessionState, ParticipantRole
from apps.sessions.services import _compute_gini, _collect_report_data
from apps.reports.llm_service import ReportLLMService
from apps.reports.pdf_service import ReportPDFService

User = get_user_model()


class ComputeGiniTests(TestCase):
    """Test per _compute_gini()."""

    def test_empty_list_returns_zero(self):
        self.assertEqual(_compute_gini([]), 0.0)

    def test_all_zeros_returns_zero(self):
        self.assertEqual(_compute_gini([0, 0, 0]), 0.0)

    def test_uniform_distribution_returns_zero(self):
        """Distribuzione perfettamente uniforme -> Gini ~ 0."""
        result = _compute_gini([10, 10, 10])
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_single_value_returns_zero(self):
        """Un solo valore -> Gini 0."""
        result = _compute_gini([5])
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_maximum_inequality(self):
        """Un solo speaker con tutti i turni -> Gini alto."""
        result = _compute_gini([0, 0, 30])
        # Per [0, 0, 30] con n=3: Gini = (2*3-3-1)*30 / (3*30) = 60/90 = 0.6667
        self.assertGreater(result, 0.6)

    def test_moderate_inequality(self):
        """Distribuzione moderatamente sbilanciata."""
        result = _compute_gini([2, 5, 13])
        self.assertGreater(result, 0.2)
        self.assertLess(result, 0.6)

    def test_two_participants_equal(self):
        result = _compute_gini([8, 8])
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_two_participants_unequal(self):
        result = _compute_gini([2, 18])
        self.assertGreater(result, 0.3)

    def test_known_value(self):
        """Verifica con calcolo manuale: [1, 2, 3] -> Gini = 2/9."""
        result = _compute_gini([1, 2, 3])
        expected = 2 / 9  # ~0.2222
        self.assertAlmostEqual(result, expected, places=4)


class CollectReportDataGiniTests(TestCase):
    """Test che _collect_report_data include gini_index."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="host", email="host@example.com", password="pass123"
        )
        now = timezone.now()
        self.session = Session.objects.create(
            title="Test Session",
            context="generic",
            state=SessionState.CLOSED,
            min_size=2,
            max_size=4,
            host=self.user,
            started_at=now - timedelta(minutes=30),
            ended_at=now,
        )

    def test_gini_index_in_data(self):
        """report_data deve contenere gini_index."""
        from unittest.mock import MagicMock
        mod_state = MagicMock()
        mod_state.turns_per_participant = {"Alice": 10, "Bob": 10}
        mod_state.ai_interventions_count = 3

        from apps.tasks.registry import get_task
        task = get_task("generic")

        data = _collect_report_data(self.session, mod_state, task)

        self.assertIn("gini_index", data)
        self.assertIsInstance(data["gini_index"], float)
        self.assertAlmostEqual(data["gini_index"], 0.0, places=4)

    def test_gini_with_unequal_turns(self):
        from unittest.mock import MagicMock
        mod_state = MagicMock()
        mod_state.turns_per_participant = {"Alice": 2, "Bob": 18}
        mod_state.ai_interventions_count = 0

        data = _collect_report_data(self.session, mod_state)
        self.assertGreater(data["gini_index"], 0.3)

    def test_total_turns_fields(self):
        from unittest.mock import MagicMock
        mod_state = MagicMock()
        mod_state.turns_per_participant = {"Alice": 5, "Bob": 10}
        mod_state.ai_interventions_count = 3

        data = _collect_report_data(self.session, mod_state)

        self.assertEqual(data["total_human_turns"], 15)
        self.assertEqual(data["total_turns"], 18)

    def test_no_mod_state_gini_zero(self):
        """Senza mod_state, Gini deve essere 0."""
        data = _collect_report_data(self.session)
        self.assertEqual(data["gini_index"], 0.0)


class ReportPDFParticipationTests(TestCase):
    """Test che il PDF contiene la sezione partecipazione."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="host", email="host@example.com", password="pass123"
        )
        now = timezone.now()
        self.session = Session.objects.create(
            title="Test Session",
            context="generic",
            state=SessionState.CLOSED,
            min_size=2,
            max_size=4,
            host=self.user,
            started_at=now - timedelta(minutes=30),
            ended_at=now,
            report_text="Test report content.",
            report_data={
                "participants": [
                    {"name": "Alice", "turns": 10, "percentage": 50},
                    {"name": "Bob", "turns": 10, "percentage": 50},
                ],
                "ai_interventions": 3,
                "ai_intervention_percentage": 13,
                "gini_index": 0.0,
                "total_human_turns": 20,
                "total_turns": 23,
            },
        )
        SessionParticipant.objects.create(
            session=self.session, user=self.user, role=ParticipantRole.HOST
        )

    def test_pdf_generates_with_report_data(self):
        """PDF deve generarsi senza errori con report_data presente."""
        pdf_bytes = ReportPDFService.generate_pdf(self.session)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))

    def test_pdf_generates_without_report_data(self):
        """PDF deve generarsi anche senza report_data (backward compat)."""
        self.session.report_data = None
        self.session.save()
        pdf_bytes = ReportPDFService.generate_pdf(self.session)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))


class FallbackReportGiniTests(TestCase):
    """Test che il fallback report include il Gini index."""

    def test_fallback_contains_gini(self):
        data = {
            "session_title": "Test Session",
            "duration_minutes": 20,
            "participants": [
                {"name": "Alice", "turns": 10, "percentage": 50},
                {"name": "Bob", "turns": 10, "percentage": 50},
            ],
            "ai_interventions": 2,
            "ai_intervention_percentage": 9,
            "gini_index": 0.15,
            "final_summary": "Test summary",
        }
        result = ReportLLMService._fallback_report(data)
        self.assertIn("Gini", result)
        self.assertIn("0.15", result)


class CollectReportDataInterventionsLogTests(TestCase):
    """Test che _collect_report_data include interventions_log."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="host_log", email="host_log@example.com", password="pass123"
        )
        now = timezone.now()
        self.session = Session.objects.create(
            title="Test Interventions Log",
            context="generic",
            state=SessionState.CLOSED,
            min_size=2,
            max_size=4,
            host=self.user,
            started_at=now - timedelta(minutes=30),
            ended_at=now,
        )

    def test_interventions_log_included_from_mod_state(self):
        from unittest.mock import MagicMock
        mod_state = MagicMock()
        mod_state.turns_per_participant = {"Alice": 5, "Bob": 5}
        mod_state.ai_interventions_count = 2
        mod_state.interventions_log = [
            {"ts": "2026-04-24T14:30:00", "reason": "monopolization",
             "score": 0.85, "speaker": "Alice", "message": "Bob, tu cosa ne pensi?"},
        ]
        data = _collect_report_data(self.session, mod_state)
        self.assertIn("interventions_log", data)
        self.assertEqual(len(data["interventions_log"]), 1)
        self.assertEqual(data["interventions_log"][0]["reason"], "monopolization")

    def test_interventions_log_empty_without_mod_state(self):
        data = _collect_report_data(self.session)
        self.assertIn("interventions_log", data)
        self.assertEqual(data["interventions_log"], [])


class ReportPDFInterventionsTests(TestCase):
    """Test che il PDF genera la sezione interventi del moderatore."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="host_int", email="host_int@example.com", password="pass123"
        )
        now = timezone.now()
        self.session = Session.objects.create(
            title="Test Interventions PDF",
            context="generic",
            state=SessionState.CLOSED,
            min_size=2,
            max_size=4,
            host=self.user,
            started_at=now - timedelta(minutes=30),
            ended_at=now,
            report_text="Test report.",
            report_data={
                "participants": [
                    {"name": "Alice", "turns": 5, "percentage": 50},
                    {"name": "Bob", "turns": 5, "percentage": 50},
                ],
                "ai_interventions": 2,
                "ai_intervention_percentage": 17,
                "gini_index": 0.0,
                "total_human_turns": 10,
                "total_turns": 12,
                "interventions_log": [
                    {"ts": "2026-04-24T14:30:00", "reason": "monopolization",
                     "score": 0.85, "speaker": "Alice", "message": "Bob, parla tu"},
                    {"ts": "2026-04-24T14:35:00", "reason": "off_topic",
                     "score": 0.9, "speaker": "Bob", "message": "Torniamo al tema"},
                ],
            },
        )
        SessionParticipant.objects.create(
            session=self.session, user=self.user, role=ParticipantRole.HOST
        )

    def test_pdf_generates_with_interventions_log(self):
        pdf_bytes = ReportPDFService.generate_pdf(self.session)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))

    def test_pdf_generates_with_empty_interventions_log(self):
        self.session.report_data["interventions_log"] = []
        self.session.save()
        pdf_bytes = ReportPDFService.generate_pdf(self.session)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))
