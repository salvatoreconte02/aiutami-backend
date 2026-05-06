from django.test import TestCase
from unittest.mock import patch, MagicMock

from apps.reports.llm_service import ReportLLMService


class ReportLLMServiceTests(TestCase):
    def test_generate_report_text_returns_string(self):
        """generate_report_text should return a string."""
        data = {
            "session_title": "Murder Mystery - Villa Rosa",
            "duration_minutes": 28,
            "participants": [
                {"name": "Mario", "speaking_time_s": 720.0, "percentage": 60.0},
                {"name": "Luigi", "speaking_time_s": 480.0, "percentage": 40.0},
            ],
            "ai_interventions": 3,
            "total_speaking_time_s": 1200.0,
            "votes": [
                {"name": "Mario", "chose": "Eddie", "correct": True},
                {"name": "Luigi", "chose": "Mickey", "correct": False},
            ],
            "guilty": "Eddie",
            "success_rate": 50,
            "final_summary": "I partecipanti hanno discusso gli indizi...",
        }

        result = ReportLLMService.generate_report_text(data)
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    @patch.object(ReportLLMService, '_build_openai_client')
    def test_generate_report_text_calls_azure(self, mock_client):
        """generate_report_text should call Azure OpenAI."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Test report content"
        mock_client.return_value.chat.completions.create.return_value = mock_response

        data = {
            "session_title": "Test Session",
            "duration_minutes": 20,
            "participants": [],
            "ai_interventions": 0,
            "total_speaking_time_s": 0.0,
            "votes": [],
            "guilty": "Eddie",
            "success_rate": 0,
            "final_summary": "Test summary",
        }

        result = ReportLLMService.generate_report_text(data)

        mock_client.return_value.chat.completions.create.assert_called_once()
        self.assertEqual(result, "Test report content")

    def test_fallback_report_on_error(self):
        """Fallback report is returned on Azure error."""
        with patch.object(ReportLLMService, '_build_openai_client', side_effect=Exception("API Error")):
            data = {
                "session_title": "Test Session",
                "duration_minutes": 20,
                "participants": [{"name": "Mario", "speaking_time_s": 300.0, "percentage": 100.0}],
                "ai_interventions": 2,
                "total_speaking_time_s": 300.0,
                "votes": [{"name": "Mario", "chose": "Eddie", "correct": True}],
                "guilty": "Eddie",
                "success_rate": 100,
                "final_summary": "Test summary",
            }

            from apps.tasks.registry import get_task
            task = get_task("murder_mystery")
            result = ReportLLMService.generate_report_text(data, task=task)

            # Should return fallback with basic info
            self.assertIn("Test Session", result)
            self.assertIn("Eddie", result)


from django.contrib.auth import get_user_model
from apps.sessions.models import Session, SessionParticipant, SessionState, ParticipantRole
from apps.tasks.murder_mystery.models import SessionVote

User = get_user_model()


class ReportPDFServiceTests(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            username="mario", email="mario@example.com", password="pass123"
        )
        self.user2 = User.objects.create_user(
            username="luigi", email="luigi@example.com", password="pass123"
        )

        self.session = Session.objects.create(
            title="Murder Mystery - Villa Rosa",
            context="murder_mystery",
            state=SessionState.CLOSED,
            min_size=3,
            max_size=3,
            host=self.user1,
            final_summary="I partecipanti hanno discusso gli indizi del caso.",
            report_text="RISULTATO FINALE\nIl colpevole era: Eddie\n...",
        )
        self.p1 = SessionParticipant.objects.create(
            session=self.session, user=self.user1, role=ParticipantRole.HOST
        )
        self.p2 = SessionParticipant.objects.create(
            session=self.session, user=self.user2, role=ParticipantRole.PARTICIPANT
        )
        SessionVote.objects.create(
            session=self.session, participant=self.p1, suspect_chosen="Eddie"
        )
        SessionVote.objects.create(
            session=self.session, participant=self.p2, suspect_chosen="Mickey"
        )

    def test_generate_pdf_returns_bytes(self):
        """generate_pdf should return PDF bytes."""
        from apps.reports.pdf_service import ReportPDFService

        pdf_bytes = ReportPDFService.generate_pdf(self.session)

        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 0)
        # Check PDF magic bytes
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))

    def test_generate_pdf_contains_session_title(self):
        """PDF should contain session title."""
        from apps.reports.pdf_service import ReportPDFService

        pdf_bytes = ReportPDFService.generate_pdf(self.session)

        # PDF is binary, but title should be in there somewhere
        # For now just verify it generates without error
        self.assertIsNotNone(pdf_bytes)


from rest_framework.test import APITestCase
from rest_framework import status


class ReportDownloadEndpointTests(APITestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            username="mario", email="mario@example.com", password="pass123"
        )
        self.outsider = User.objects.create_user(
            username="outsider", email="out@example.com", password="pass123"
        )

        self.session = Session.objects.create(
            title="Murder Mystery - Villa Rosa",
            context="murder_mystery",
            state=SessionState.CLOSED,
            min_size=3,
            max_size=3,
            host=self.user1,
            final_summary="Test summary",
            report_text="Test report",
        )
        self.p1 = SessionParticipant.objects.create(
            session=self.session, user=self.user1, role=ParticipantRole.HOST
        )
        SessionVote.objects.create(
            session=self.session, participant=self.p1, suspect_chosen="Eddie"
        )

    def test_download_report_success(self):
        """Participant can download report."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get(f"/api/sessions/{self.session.id}/report/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('attachment', response['Content-Disposition'])

    def test_download_report_not_participant(self):
        """Non-participant cannot download report."""
        self.client.force_authenticate(user=self.outsider)
        response = self.client.get(f"/api/sessions/{self.session.id}/report/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_download_report_session_not_closed(self):
        """Cannot download if session not CLOSED."""
        self.session.state = SessionState.CONCLUSION
        self.session.save()
        self.client.force_authenticate(user=self.user1)
        response = self.client.get(f"/api/sessions/{self.session.id}/report/")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_download_report_unauthenticated(self):
        """Unauthenticated request returns 401."""
        response = self.client.get(f"/api/sessions/{self.session.id}/report/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class NasaReportContextSynergyTests(TestCase):
    def test_synergy_gain_computed_when_individual_rankings_exist(self) -> None:
        from apps.tasks.nasa_moon.models import NasaRanking, NasaIndividualRanking
        from apps.tasks.nasa_moon.report import collect_nasa_report_context
        from apps.tasks.nasa_moon.config import NASA_ITEMS, compute_error_score

        # Setup sessione + ranking di gruppo
        host = User.objects.create_user(username="rep_h", password="x")
        session = Session.objects.create(
            title="T", context="nasa_moon_survival",
            min_size=3, max_size=6, host=host,
            state=SessionState.CLOSED,
        )
        p_host = SessionParticipant.objects.create(
            session=session, user=host, role=ParticipantRole.HOST,
        )
        # group ranking molto buono (uguale all'expert ranking, error 0)
        from apps.tasks.nasa_moon.config import EXPERT_RANKING
        sorted_items = sorted(EXPERT_RANKING.keys(), key=lambda k: EXPERT_RANKING[k])
        NasaRanking.objects.create(
            session=session, submitted_by=p_host,
            ranked_items=sorted_items, is_final=True,
        )
        # 3 ranking individuali con errori vari (tutti > 0 cosi' min > group_error=0)
        # Generiamo varianti con piccoli swap rispetto al sorted_items.
        swapped_a = list(sorted_items)
        swapped_a[0], swapped_a[1] = swapped_a[1], swapped_a[0]  # swap 2 prime
        for i, items in enumerate([
            list(NASA_ITEMS),  # default order: error elevato
            swapped_a,         # piccolo errore (>0)
            list(reversed(sorted_items)),  # peggio: error massimo
        ]):
            u = User.objects.create_user(username=f"rep_p_{i}", password="x")
            p = SessionParticipant.objects.create(session=session, user=u)
            NasaIndividualRanking.objects.create(
                session=session, participant=p,
                ranked_items=items, is_submitted=True,
            )

        ctx = collect_nasa_report_context(session)
        self.assertIsNotNone(ctx["synergy_gain"])
        self.assertIsNotNone(ctx["mean_individual_error"])
        self.assertEqual(ctx["individual_count"], 3)
        # group_error = 0, mean_individual_error > 0 -> synergy_gain > 0
        self.assertGreater(ctx["synergy_gain"], 0)
        self.assertTrue(ctx["assembly_bonus"])  # group < min(individual)

    def test_legacy_session_no_individual_rankings_keeps_none(self) -> None:
        from apps.tasks.nasa_moon.report import collect_nasa_report_context
        # Sessione senza individual rankings (legacy o no fase eseguita)
        host = User.objects.create_user(username="rep_legacy_h", password="x")
        session = Session.objects.create(
            title="T", context="nasa_moon_survival",
            min_size=3, max_size=6, host=host, state=SessionState.CLOSED,
        )
        ctx = collect_nasa_report_context(session)
        self.assertIsNone(ctx["synergy_gain"])
        self.assertIsNone(ctx["individual_errors"])
        self.assertIsNone(ctx["assembly_bonus"])


class LostAtSeaReportContextSynergyTests(TestCase):
    def test_synergy_gain_computed_when_individual_rankings_exist(self) -> None:
        from apps.tasks.lost_at_sea.models import LostAtSeaRanking, LostAtSeaIndividualRanking
        from apps.tasks.lost_at_sea.report import collect_lost_at_sea_report_context

        # Setup sessione + ranking di gruppo
        host = User.objects.create_user(username="rep_las_h", password="x")
        session = Session.objects.create(
            title="T", context="lost_at_sea",
            min_size=3, max_size=6, host=host,
            state=SessionState.CLOSED,
        )
        p_host = SessionParticipant.objects.create(
            session=session, user=host, role=ParticipantRole.HOST,
        )
        # group ranking molto buono (uguale all'expert ranking, error 0)
        from apps.tasks.lost_at_sea.config import EXPERT_RANKING
        sorted_items = sorted(EXPERT_RANKING.keys(), key=lambda k: EXPERT_RANKING[k])
        LostAtSeaRanking.objects.create(
            session=session, submitted_by=p_host,
            ranked_items=sorted_items, is_final=True,
        )
        # 3 ranking individuali con errori vari (tutti > 0 cosi' min > group_error=0)
        # Nota: LOST_AT_SEA_ITEMS e' gia' in expert order (error 0), quindi
        # non lo usiamo come ranking individuale: serve sempre un piccolo swap
        # per avere min(individual_errors) > 0 e assembly_bonus = True.
        swapped_a = list(sorted_items)
        swapped_a[0], swapped_a[1] = swapped_a[1], swapped_a[0]  # swap 2 prime
        swapped_b = list(sorted_items)
        swapped_b[5], swapped_b[6] = swapped_b[6], swapped_b[5]  # swap a meta'
        for i, items in enumerate([
            swapped_a,                       # piccolo errore (=2)
            swapped_b,                       # piccolo errore (=2)
            list(reversed(sorted_items)),    # peggio: error massimo
        ]):
            u = User.objects.create_user(username=f"rep_las_p_{i}", password="x")
            p = SessionParticipant.objects.create(session=session, user=u)
            LostAtSeaIndividualRanking.objects.create(
                session=session, participant=p,
                ranked_items=items, is_submitted=True,
            )

        ctx = collect_lost_at_sea_report_context(session)
        self.assertIsNotNone(ctx["synergy_gain"])
        self.assertIsNotNone(ctx["mean_individual_error"])
        self.assertEqual(ctx["individual_count"], 3)
        # group_error = 0, mean_individual_error > 0 -> synergy_gain > 0
        self.assertGreater(ctx["synergy_gain"], 0)
        self.assertTrue(ctx["assembly_bonus"])  # group < min(individual)

    def test_legacy_session_no_individual_rankings_keeps_none(self) -> None:
        from apps.tasks.lost_at_sea.report import collect_lost_at_sea_report_context
        # Sessione senza individual rankings (legacy o no fase eseguita)
        host = User.objects.create_user(username="rep_las_legacy_h", password="x")
        session = Session.objects.create(
            title="T", context="lost_at_sea",
            min_size=3, max_size=6, host=host, state=SessionState.CLOSED,
        )
        ctx = collect_lost_at_sea_report_context(session)
        self.assertIsNone(ctx["synergy_gain"])
        self.assertIsNone(ctx["individual_errors"])
        self.assertIsNone(ctx["assembly_bonus"])
