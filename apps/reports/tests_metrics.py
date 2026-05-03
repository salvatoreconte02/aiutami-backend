"""
Test per le metriche di valutazione empirica nel report:
- Gini index (calcolato su speaking_time_per_participant)
- Sezione partecipazione nel PDF
- Gini nel fallback report

NOTA storica (mag 2026): in precedenza il Gini si calcolava su
turns_per_participant, ma quel campo non esisteva piu' nello state e il
report restituiva sempre Gini=0. Refactor: si usa speaking_time_per_participant
(secondi cumulativi parlati per partecipante), gia' raccolto correttamente
e usato anche da Mono/Excl detection in moderation/metrics.py.
"""

from datetime import timedelta
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.reports.llm_service import ReportLLMService
from apps.reports.pdf_service import ReportPDFService
from apps.sessions.models import (
    ParticipantRole,
    Session,
    SessionParticipant,
    SessionState,
)
from apps.sessions.services import _collect_report_data, _compute_gini

User = get_user_model()


class ComputeGiniTests(TestCase):
    """Test per _compute_gini() — accetta sia float (sec) che int (turn count)."""

    def test_empty_list_returns_zero(self):
        self.assertEqual(_compute_gini([]), 0.0)

    def test_all_zeros_returns_zero(self):
        self.assertEqual(_compute_gini([0, 0, 0]), 0.0)

    def test_uniform_distribution_returns_zero(self):
        result = _compute_gini([10.0, 10.0, 10.0])
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_single_value_returns_zero(self):
        result = _compute_gini([5.0])
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_maximum_inequality_one_speaker(self):
        """Caso di regressione: un partecipante non parla per niente.
        Pre-refactor questo case usciva con Gini=0 perche' turns_per_participant
        era vuoto. Ora con speaking_time deve uscire un Gini ALTO."""
        result = _compute_gini([0.0, 0.0, 300.0])
        # n=3, sorted=[0,0,300], sum=300:
        #   gini_sum = (-2)*0 + 0*0 + 2*300 = 600
        #   gini = 600 / (3 * 300) = 0.6667
        self.assertAlmostEqual(result, 0.6667, places=3)

    def test_moderate_inequality(self):
        result = _compute_gini([60.0, 150.0, 390.0])
        self.assertGreater(result, 0.2)
        self.assertLess(result, 0.6)

    def test_two_participants_equal(self):
        result = _compute_gini([240.0, 240.0])
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_two_participants_unequal(self):
        result = _compute_gini([60.0, 540.0])
        self.assertGreater(result, 0.3)


class CollectReportDataGiniTests(TestCase):
    """Test che _collect_report_data calcola Gini su speaking time."""

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

    def test_gini_index_in_data_uniform(self):
        """Tempo uguale tra partecipanti -> Gini ~ 0."""
        mod_state = MagicMock()
        mod_state.speaking_time_per_participant = {"Alice": 240.0, "Bob": 240.0}
        mod_state.ai_interventions_count = 3

        from apps.tasks.registry import get_task
        task = get_task("generic")
        data = _collect_report_data(self.session, mod_state, task)

        self.assertIn("gini_index", data)
        self.assertIsInstance(data["gini_index"], float)
        self.assertAlmostEqual(data["gini_index"], 0.0, places=4)

    def test_gini_with_unequal_speaking_time(self):
        mod_state = MagicMock()
        mod_state.speaking_time_per_participant = {"Alice": 60.0, "Bob": 540.0}
        mod_state.ai_interventions_count = 0

        data = _collect_report_data(self.session, mod_state)
        self.assertGreater(data["gini_index"], 0.3)

    def test_regression_silent_participant_yields_high_gini(self):
        """Bug-fix mag 2026: il bug originale faceva uscire Gini=0 quando un
        partecipante non parlava perche' turns_per_participant era sempre {}.
        Ora speaking_time_per_participant cattura correttamente il caso."""
        mod_state = MagicMock()
        mod_state.speaking_time_per_participant = {
            "Salvcon": 480.0,  # ~8 min
            "Anna": 240.0,     # ~4 min
            "Simocos": 0.0,    # silenzioso
        }
        mod_state.ai_interventions_count = 4
        data = _collect_report_data(self.session, mod_state)
        self.assertGreater(
            data["gini_index"], 0.35,
            f"Expected high Gini for silent participant, got {data['gini_index']}",
        )

    def test_participants_data_uses_speaking_time(self):
        mod_state = MagicMock()
        mod_state.speaking_time_per_participant = {"Alice": 100.0, "Bob": 300.0}
        mod_state.ai_interventions_count = 2

        data = _collect_report_data(self.session, mod_state)

        self.assertEqual(data["total_speaking_time_s"], 400.0)
        names = {p["name"] for p in data["participants"]}
        self.assertEqual(names, {"Alice", "Bob"})
        for p in data["participants"]:
            self.assertIn("speaking_time_s", p)
            self.assertIn("percentage", p)
            self.assertNotIn("turns", p)
            if p["name"] == "Alice":
                self.assertEqual(p["speaking_time_s"], 100.0)
                self.assertEqual(p["percentage"], 25.0)
            else:
                self.assertEqual(p["speaking_time_s"], 300.0)
                self.assertEqual(p["percentage"], 75.0)

    def test_no_mod_state_gini_zero(self):
        data = _collect_report_data(self.session)
        self.assertEqual(data["gini_index"], 0.0)
        self.assertEqual(data["total_speaking_time_s"], 0.0)
        self.assertEqual(data["participants"], [])


class ReportPDFParticipationTests(TestCase):
    """Test che il PDF contiene la sezione partecipazione (formato speaking time)."""

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
                    {"name": "Alice", "speaking_time_s": 240.0, "percentage": 50.0},
                    {"name": "Bob", "speaking_time_s": 240.0, "percentage": 50.0},
                ],
                "ai_interventions": 3,
                "total_speaking_time_s": 480.0,
                "gini_index": 0.0,
            },
        )
        SessionParticipant.objects.create(
            session=self.session, user=self.user, role=ParticipantRole.HOST
        )

    def test_pdf_generates_with_report_data(self):
        pdf_bytes = ReportPDFService.generate_pdf(self.session)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))

    def test_pdf_generates_without_report_data(self):
        self.session.report_data = None
        self.session.save()
        pdf_bytes = ReportPDFService.generate_pdf(self.session)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))


class FallbackReportGiniTests(TestCase):
    """Test che il fallback report include il Gini index e usa speaking time."""

    def test_fallback_contains_gini_and_speaking_time(self):
        data = {
            "session_title": "Test Session",
            "duration_minutes": 20,
            "participants": [
                {"name": "Alice", "speaking_time_s": 240.0, "percentage": 50.0},
                {"name": "Bob", "speaking_time_s": 240.0, "percentage": 50.0},
            ],
            "ai_interventions": 2,
            "total_speaking_time_s": 480.0,
            "gini_index": 0.15,
            "final_summary": "Test summary",
        }
        result = ReportLLMService._fallback_report(data)
        self.assertIn("Gini", result)
        self.assertIn("0.15", result)
        # Format mm:ss must be present (4 min 00 sec for 240s)
        self.assertIn("4 min", result)


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
        mod_state = MagicMock()
        mod_state.speaking_time_per_participant = {"Alice": 120.0, "Bob": 120.0}
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
                    {"name": "Alice", "speaking_time_s": 150.0, "percentage": 50.0},
                    {"name": "Bob", "speaking_time_s": 150.0, "percentage": 50.0},
                ],
                "ai_interventions": 2,
                "total_speaking_time_s": 300.0,
                "gini_index": 0.0,
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
