"""Test endpoint + modello NasaIndividualRanking.

Suddiviso in classi:
- ModelTests: schema, constraint unicità.
- ViewTests: GET/PUT/POST submit/POST finalize-if-expired (futuri task).
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from apps.sessions.models import Session, SessionParticipant, ParticipantRole, SessionState
from apps.tasks.nasa_moon.config import NASA_ITEMS

User = get_user_model()


def _make_session(context: str = "nasa_moon_survival") -> tuple[Session, list[SessionParticipant]]:
    host = User.objects.create_user(username=f"h_{context}", password="x")
    session = Session.objects.create(
        title="T", context=context, min_size=3, max_size=6, host=host,
    )
    p_host = SessionParticipant.objects.create(
        session=session, user=host, role=ParticipantRole.HOST,
    )
    others = []
    for i in range(2):
        u = User.objects.create_user(username=f"u_{context}_{i}", password="x")
        others.append(SessionParticipant.objects.create(
            session=session, user=u, role=ParticipantRole.PARTICIPANT,
        ))
    return session, [p_host, *others]


class NasaIndividualRankingModelTests(TestCase):
    def test_create_and_defaults(self) -> None:
        from apps.tasks.nasa_moon.models import NasaIndividualRanking
        session, participants = _make_session()
        r = NasaIndividualRanking.objects.create(
            session=session,
            participant=participants[0],
            ranked_items=list(NASA_ITEMS),
        )
        self.assertFalse(r.is_submitted)
        self.assertIsNotNone(r.created_at)
        self.assertEqual(r.ranked_items, list(NASA_ITEMS))

    def test_unique_session_participant(self) -> None:
        from apps.tasks.nasa_moon.models import NasaIndividualRanking
        session, participants = _make_session()
        NasaIndividualRanking.objects.create(
            session=session, participant=participants[0],
            ranked_items=list(NASA_ITEMS),
        )
        with self.assertRaises(IntegrityError):
            NasaIndividualRanking.objects.create(
                session=session, participant=participants[0],
                ranked_items=list(NASA_ITEMS),
            )


def _put_session_in_individual_ranking(session: Session) -> None:
    session.state = SessionState.INDIVIDUAL_RANKING
    session.individual_ranking_started_at = timezone.now()
    session.save(update_fields=["state", "individual_ranking_started_at"])


class NasaIndividualRankingGetPutTests(TestCase):
    def setUp(self) -> None:
        self.session, self.participants = _make_session()
        _put_session_in_individual_ranking(self.session)
        self.host_user = self.participants[0].user
        self.client = APIClient()
        self.client.force_authenticate(user=self.host_user)
        self.url = f"/api/tasks/nasa-moon/sessions/{self.session.id}/individual-ranking/"

    def test_get_returns_null_when_no_row(self) -> None:
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200, resp.json())
        body = resp.json()
        self.assertIsNone(body["ranked_items"])
        self.assertFalse(body["is_submitted"])
        self.assertIsNotNone(body["phase_deadline_at"])

    def test_put_creates_row(self) -> None:
        resp = self.client.put(
            self.url, data={"ranked_items": list(NASA_ITEMS)}, format="json",
        )
        self.assertIn(resp.status_code, (200, 201), resp.json())
        from apps.tasks.nasa_moon.models import NasaIndividualRanking
        r = NasaIndividualRanking.objects.get(session=self.session, participant=self.participants[0])
        self.assertEqual(r.ranked_items, list(NASA_ITEMS))
        self.assertFalse(r.is_submitted)

    def test_put_invalid_length(self) -> None:
        resp = self.client.put(
            self.url, data={"ranked_items": list(NASA_ITEMS)[:14]}, format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_put_invalid_items(self) -> None:
        bad = list(NASA_ITEMS)
        bad[0] = "Oggetto inesistente"
        resp = self.client.put(self.url, data={"ranked_items": bad}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_put_duplicates(self) -> None:
        bad = list(NASA_ITEMS)
        bad[1] = bad[0]
        resp = self.client.put(self.url, data={"ranked_items": bad}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_put_in_wrong_state(self) -> None:
        self.session.state = SessionState.LOBBY
        self.session.save(update_fields=["state"])
        resp = self.client.put(
            self.url, data={"ranked_items": list(NASA_ITEMS)}, format="json",
        )
        self.assertEqual(resp.status_code, 409)

    def test_put_after_submit_blocked(self) -> None:
        from apps.tasks.nasa_moon.models import NasaIndividualRanking
        NasaIndividualRanking.objects.create(
            session=self.session, participant=self.participants[0],
            ranked_items=list(NASA_ITEMS), is_submitted=True,
        )
        resp = self.client.put(
            self.url, data={"ranked_items": list(NASA_ITEMS)}, format="json",
        )
        self.assertEqual(resp.status_code, 409)

    def test_put_after_deadline_finalizes_and_returns_409(self) -> None:
        # Sposta indietro il timestamp di inizio per simulare scadenza
        self.session.individual_ranking_started_at = (
            timezone.now() - timedelta(seconds=500)
        )
        self.session.save(update_fields=["individual_ranking_started_at"])
        resp = self.client.put(
            self.url, data={"ranked_items": list(NASA_ITEMS)}, format="json",
        )
        self.assertEqual(resp.status_code, 409)
        # La sessione è stata finalizzata e portata ad ACTIVE
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, SessionState.ACTIVE)


class NasaIndividualRankingSubmitTests(TestCase):
    def setUp(self) -> None:
        self.session, self.participants = _make_session()
        _put_session_in_individual_ranking(self.session)
        self.client = APIClient()
        self.url = f"/api/tasks/nasa-moon/sessions/{self.session.id}/individual-ranking/submit/"
        self.put_url = f"/api/tasks/nasa-moon/sessions/{self.session.id}/individual-ranking/"

    def _client_for(self, participant):
        c = APIClient()
        c.force_authenticate(user=participant.user)
        return c

    def test_submit_marks_is_submitted(self) -> None:
        from apps.tasks.nasa_moon.models import NasaIndividualRanking
        c = self._client_for(self.participants[0])
        c.put(self.put_url, data={"ranked_items": list(NASA_ITEMS)}, format="json")
        resp = c.post(self.url)
        self.assertEqual(resp.status_code, 200, resp.json())
        r = NasaIndividualRanking.objects.get(
            session=self.session, participant=self.participants[0],
        )
        self.assertTrue(r.is_submitted)

    def test_submit_without_existing_row_returns_400(self) -> None:
        c = self._client_for(self.participants[0])
        resp = c.post(self.url)
        self.assertEqual(resp.status_code, 400)

    def test_submit_already_submitted_returns_409(self) -> None:
        c = self._client_for(self.participants[0])
        c.put(self.put_url, data={"ranked_items": list(NASA_ITEMS)}, format="json")
        c.post(self.url)
        resp = c.post(self.url)
        self.assertEqual(resp.status_code, 409)

    def test_last_submit_triggers_finalize(self) -> None:
        # Tutti e 3 fanno PUT + submit; l'ultimo deve scattare la finalize
        for p in self.participants:
            c = self._client_for(p)
            c.put(self.put_url, data={"ranked_items": list(NASA_ITEMS)}, format="json")
            c.post(self.url)
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, SessionState.ACTIVE)


class NasaIndividualRankingFinalizeIfExpiredTests(TestCase):
    def setUp(self) -> None:
        self.session, self.participants = _make_session()
        _put_session_in_individual_ranking(self.session)
        self.client = APIClient()
        self.client.force_authenticate(user=self.participants[0].user)
        self.url = f"/api/tasks/nasa-moon/sessions/{self.session.id}/individual-ranking/finalize-if-expired/"

    def test_no_op_if_state_wrong(self) -> None:
        self.session.state = SessionState.LOBBY
        self.session.save(update_fields=["state"])
        resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["finalized"])

    def test_no_op_if_not_expired(self) -> None:
        resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["finalized"])

    def test_finalizes_if_expired(self) -> None:
        from datetime import timedelta
        from django.utils import timezone
        self.session.individual_ranking_started_at = (
            timezone.now() - timedelta(seconds=500)
        )
        self.session.save(update_fields=["individual_ranking_started_at"])
        resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["finalized"])
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, SessionState.ACTIVE)

    def test_idempotent(self) -> None:
        from datetime import timedelta
        from django.utils import timezone
        self.session.individual_ranking_started_at = (
            timezone.now() - timedelta(seconds=500)
        )
        self.session.save(update_fields=["individual_ranking_started_at"])
        self.client.post(self.url)
        resp2 = self.client.post(self.url)
        self.assertEqual(resp2.status_code, 200)
        self.assertFalse(resp2.json()["finalized"])
