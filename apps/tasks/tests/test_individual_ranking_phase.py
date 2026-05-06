"""Test transizione di stato LOBBY -> INDIVIDUAL_RANKING / ACTIVE in base al task plugin.
Verifica il routing del Session.start e la regression per task senza fase pre-discussione.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.sessions.models import (
    Session, SessionEvent, SessionEventType, SessionParticipant,
    SessionState, ParticipantRole,
)

User = get_user_model()


def _create_lobby_session(host, context: str, min_size: int, max_size: int) -> Session:
    session = Session.objects.create(
        title=f"T-{context}",
        context=context,
        min_size=min_size,
        max_size=max_size,
        host=host,
    )
    SessionParticipant.objects.create(
        session=session, user=host, role=ParticipantRole.HOST,
    )
    return session


def _fill_to_min(session: Session) -> None:
    """Aggiunge altri partecipanti finché non si raggiunge min_size."""
    needed = session.min_size - session.participants.count()
    for i in range(needed):
        u = User.objects.create_user(username=f"p_{session.id}_{i}", password="x")
        SessionParticipant.objects.create(
            session=session, user=u, role=ParticipantRole.PARTICIPANT,
        )


class IndividualRankingPhaseRoutingTests(TestCase):
    def setUp(self) -> None:
        self.host = User.objects.create_user(username="host_p", password="x")
        self.client = APIClient()
        self.client.force_authenticate(user=self.host)

    def test_nasa_moon_starts_in_individual_ranking(self) -> None:
        session = _create_lobby_session(self.host, "nasa_moon_survival", 3, 6)
        _fill_to_min(session)
        resp = self.client.post(f"/api/sessions/{session.id}/start/", data={})
        self.assertEqual(resp.status_code, 200, resp.json())
        session.refresh_from_db()
        self.assertEqual(session.state, SessionState.INDIVIDUAL_RANKING)
        self.assertIsNotNone(session.individual_ranking_started_at)
        self.assertIsNone(session.started_at)

    def test_lost_at_sea_starts_in_individual_ranking(self) -> None:
        session = _create_lobby_session(self.host, "lost_at_sea", 3, 6)
        _fill_to_min(session)
        resp = self.client.post(f"/api/sessions/{session.id}/start/", data={})
        self.assertEqual(resp.status_code, 200, resp.json())
        session.refresh_from_db()
        self.assertEqual(session.state, SessionState.INDIVIDUAL_RANKING)
        self.assertIsNotNone(session.individual_ranking_started_at)

    def test_generic_starts_in_active(self) -> None:
        session = _create_lobby_session(self.host, "generic", 2, 8)
        _fill_to_min(session)
        resp = self.client.post(f"/api/sessions/{session.id}/start/", data={})
        self.assertEqual(resp.status_code, 200, resp.json())
        session.refresh_from_db()
        self.assertEqual(session.state, SessionState.ACTIVE)
        self.assertIsNotNone(session.started_at)
        self.assertIsNone(session.individual_ranking_started_at)

    def test_murder_mystery_starts_in_active(self) -> None:
        session = _create_lobby_session(self.host, "murder_mystery", 3, 3)
        _fill_to_min(session)
        resp = self.client.post(f"/api/sessions/{session.id}/start/", data={})
        self.assertEqual(resp.status_code, 200, resp.json())
        session.refresh_from_db()
        self.assertEqual(session.state, SessionState.ACTIVE)
        self.assertIsNotNone(session.started_at)
        self.assertIsNone(session.individual_ranking_started_at)

    def test_individual_ranking_session_event_payload(self) -> None:
        """Per IR il SessionEvent STARTED ha payload {phase, started_at, deadline}."""
        from datetime import timedelta
        session = _create_lobby_session(self.host, "nasa_moon_survival", 3, 6)
        _fill_to_min(session)
        self.client.post(f"/api/sessions/{session.id}/start/", data={})
        event = SessionEvent.objects.get(session=session, type=SessionEventType.STARTED)
        self.assertEqual(event.payload["phase"], "INDIVIDUAL_RANKING")
        self.assertIn("individual_ranking_started_at", event.payload)
        self.assertIn("phase_deadline_at", event.payload)
        self.assertNotIn("started_at", event.payload)
        # Deadline = started_at + 480s (default da TaskDefinition)
        from datetime import datetime
        ir_at = datetime.fromisoformat(event.payload["individual_ranking_started_at"])
        deadline = datetime.fromisoformat(event.payload["phase_deadline_at"])
        self.assertEqual(deadline - ir_at, timedelta(seconds=480))

    def test_active_session_event_payload_legacy(self) -> None:
        """Per ACTIVE il SessionEvent STARTED ha payload legacy {started_at}."""
        session = _create_lobby_session(self.host, "generic", 2, 8)
        _fill_to_min(session)
        self.client.post(f"/api/sessions/{session.id}/start/", data={})
        event = SessionEvent.objects.get(session=session, type=SessionEventType.STARTED)
        self.assertIn("started_at", event.payload)
        self.assertNotIn("phase", event.payload)
        self.assertNotIn("phase_deadline_at", event.payload)


class IndividualRankingBlocksOtherSessionsTests(TestCase):
    """Un utente in fase INDIVIDUAL_RANKING non puo' creare/joinare altre sessioni."""

    def setUp(self) -> None:
        self.host = User.objects.create_user(username="host_block", password="x")
        self.client = APIClient()
        self.client.force_authenticate(user=self.host)
        # Avvia una sessione NASA in INDIVIDUAL_RANKING
        self.s1 = _create_lobby_session(self.host, "nasa_moon_survival", 3, 6)
        _fill_to_min(self.s1)
        self.client.post(f"/api/sessions/{self.s1.id}/start/", data={})
        self.s1.refresh_from_db()
        assert self.s1.state == SessionState.INDIVIDUAL_RANKING

    def test_cannot_create_second_session_during_individual_ranking(self) -> None:
        resp = self.client.post(
            "/api/sessions/",
            data={"title": "T2", "context": "generic", "min_size": 2, "max_size": 4},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_cannot_join_second_session_during_individual_ranking(self) -> None:
        from apps.sessions.models import Invitation
        host2 = User.objects.create_user(username="host_block_2", password="x")
        s2 = Session.objects.create(
            title="T2", context="generic", min_size=2, max_size=4, host=host2,
        )
        SessionParticipant.objects.create(session=s2, user=host2, role=ParticipantRole.HOST)
        inv = Invitation.objects.create(session=s2)
        resp = self.client.post(
            "/api/sessions/join_by_token/",
            data={"token": inv.token},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)
