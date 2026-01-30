from django.test import TestCase
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from rest_framework.test import APITestCase
from rest_framework import status

from apps.sessions.models import Session, SessionParticipant, SessionVote, SessionState, SessionContext, ParticipantRole

User = get_user_model()


class SessionVoteModelTests(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            username="user1", email="user1@example.com", password="pass123"
        )
        self.user2 = User.objects.create_user(
            username="user2", email="user2@example.com", password="pass123"
        )
        self.session = Session.objects.create(
            title="Test Murder Mystery",
            context=SessionContext.MURDER_MYSTERY,
            state=SessionState.CONCLUSION,
            min_size=3,
            max_size=3,
            host=self.user1,
        )
        self.participant1 = SessionParticipant.objects.create(
            session=self.session,
            user=self.user1,
            role=ParticipantRole.HOST,
        )
        self.participant2 = SessionParticipant.objects.create(
            session=self.session,
            user=self.user2,
            role=ParticipantRole.PARTICIPANT,
        )

    def test_session_vote_creation(self):
        """SessionVote can be created with valid data."""
        vote = SessionVote.objects.create(
            session=self.session,
            participant=self.participant1,
            suspect_chosen="Eddie",
        )
        self.assertEqual(vote.session, self.session)
        self.assertEqual(vote.participant, self.participant1)
        self.assertEqual(vote.suspect_chosen, "Eddie")
        self.assertIsNotNone(vote.created_at)

    def test_session_vote_unique_per_participant(self):
        """Only one vote per participant per session allowed."""
        SessionVote.objects.create(
            session=self.session,
            participant=self.participant1,
            suspect_chosen="Eddie",
        )
        with self.assertRaises(IntegrityError):
            SessionVote.objects.create(
                session=self.session,
                participant=self.participant1,
                suspect_chosen="Mickey",
            )

    def test_session_vote_cascade_delete(self):
        """Votes are deleted when session is deleted."""
        SessionVote.objects.create(
            session=self.session,
            participant=self.participant1,
            suspect_chosen="Eddie",
        )
        session_id = self.session.id
        self.session.delete()
        self.assertEqual(SessionVote.objects.filter(session_id=session_id).count(), 0)


class SessionReportTextTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="host", email="host@example.com", password="pass123"
        )
        self.session = Session.objects.create(
            title="Test Session",
            context=SessionContext.MURDER_MYSTERY,
            state=SessionState.CLOSED,
            min_size=3,
            max_size=3,
            host=self.user,
        )

    def test_session_report_text_default_empty(self):
        """Session.report_text defaults to empty string."""
        self.assertEqual(self.session.report_text, "")

    def test_session_report_text_can_be_set(self):
        """Session.report_text can be updated."""
        self.session.report_text = "This is the AI-generated report text."
        self.session.save(update_fields=["report_text"])
        self.session.refresh_from_db()
        self.assertEqual(self.session.report_text, "This is the AI-generated report text.")


class VoteEndpointTests(APITestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            username="host", email="host@example.com", password="pass123"
        )
        self.user2 = User.objects.create_user(
            username="player2", email="p2@example.com", password="pass123"
        )
        self.user3 = User.objects.create_user(
            username="player3", email="p3@example.com", password="pass123"
        )
        self.outsider = User.objects.create_user(
            username="outsider", email="out@example.com", password="pass123"
        )

        self.session = Session.objects.create(
            title="Test Murder Mystery",
            context=SessionContext.MURDER_MYSTERY,
            state=SessionState.CONCLUSION,
            min_size=3,
            max_size=3,
            host=self.user1,
        )
        self.p1 = SessionParticipant.objects.create(
            session=self.session, user=self.user1, role=ParticipantRole.HOST
        )
        self.p2 = SessionParticipant.objects.create(
            session=self.session, user=self.user2, role=ParticipantRole.PARTICIPANT
        )
        self.p3 = SessionParticipant.objects.create(
            session=self.session, user=self.user3, role=ParticipantRole.PARTICIPANT
        )

    def test_vote_success(self):
        """Valid vote is recorded."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.post(
            f"/api/sessions/{self.session.id}/vote/",
            {"suspect": "Eddie"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["votes_cast"], 1)
        self.assertEqual(response.data["total_participants"], 3)

    def test_vote_invalid_suspect(self):
        """Invalid suspect returns 400."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.post(
            f"/api/sessions/{self.session.id}/vote/",
            {"suspect": "InvalidName"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_vote_duplicate(self):
        """Duplicate vote returns 400."""
        self.client.force_authenticate(user=self.user1)
        self.client.post(
            f"/api/sessions/{self.session.id}/vote/",
            {"suspect": "Eddie"},
            format="json",
        )
        response = self.client.post(
            f"/api/sessions/{self.session.id}/vote/",
            {"suspect": "Mickey"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_vote_not_participant(self):
        """Non-participant returns 403."""
        self.client.force_authenticate(user=self.outsider)
        response = self.client.post(
            f"/api/sessions/{self.session.id}/vote/",
            {"suspect": "Eddie"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_vote_wrong_state(self):
        """Vote in non-CONCLUSION state returns 409."""
        self.session.state = SessionState.ACTIVE
        self.session.save()
        self.client.force_authenticate(user=self.user1)
        response = self.client.post(
            f"/api/sessions/{self.session.id}/vote/",
            {"suspect": "Eddie"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_vote_unauthenticated(self):
        """Unauthenticated request returns 401."""
        response = self.client.post(
            f"/api/sessions/{self.session.id}/vote/",
            {"suspect": "Eddie"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class VoteStatusEndpointTests(APITestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            username="host", email="host@example.com", password="pass123"
        )
        self.user2 = User.objects.create_user(
            username="player2", email="p2@example.com", password="pass123"
        )

        self.session = Session.objects.create(
            title="Test Murder Mystery",
            context=SessionContext.MURDER_MYSTERY,
            state=SessionState.CONCLUSION,
            min_size=3,
            max_size=3,
            host=self.user1,
        )
        self.p1 = SessionParticipant.objects.create(
            session=self.session, user=self.user1, role=ParticipantRole.HOST
        )
        self.p2 = SessionParticipant.objects.create(
            session=self.session, user=self.user2, role=ParticipantRole.PARTICIPANT
        )

    def test_vote_status_no_votes(self):
        """Vote status with no votes cast."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get(f"/api/sessions/{self.session.id}/vote-status/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_participants"], 2)
        self.assertEqual(response.data["votes_cast"], 0)
        self.assertFalse(response.data["has_current_user_voted"])
        self.assertFalse(response.data["all_voted"])

    def test_vote_status_with_votes(self):
        """Vote status after some votes cast."""
        SessionVote.objects.create(
            session=self.session, participant=self.p1, suspect_chosen="Eddie"
        )
        self.client.force_authenticate(user=self.user1)
        response = self.client.get(f"/api/sessions/{self.session.id}/vote-status/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["votes_cast"], 1)
        self.assertTrue(response.data["has_current_user_voted"])
        self.assertFalse(response.data["all_voted"])

    def test_vote_status_all_voted(self):
        """Vote status when all have voted."""
        SessionVote.objects.create(
            session=self.session, participant=self.p1, suspect_chosen="Eddie"
        )
        SessionVote.objects.create(
            session=self.session, participant=self.p2, suspect_chosen="Mickey"
        )
        self.client.force_authenticate(user=self.user1)
        response = self.client.get(f"/api/sessions/{self.session.id}/vote-status/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["all_voted"])


from unittest.mock import patch, MagicMock


class AllVotedBroadcastTests(APITestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            username="host", email="host@example.com", password="pass123"
        )
        self.user2 = User.objects.create_user(
            username="player2", email="p2@example.com", password="pass123"
        )
        self.user3 = User.objects.create_user(
            username="player3", email="p3@example.com", password="pass123"
        )

        self.session = Session.objects.create(
            title="Test Murder Mystery",
            context=SessionContext.MURDER_MYSTERY,
            state=SessionState.CONCLUSION,
            min_size=3,
            max_size=3,
            host=self.user1,
        )
        self.p1 = SessionParticipant.objects.create(
            session=self.session, user=self.user1, role=ParticipantRole.HOST
        )
        self.p2 = SessionParticipant.objects.create(
            session=self.session, user=self.user2, role=ParticipantRole.PARTICIPANT
        )
        self.p3 = SessionParticipant.objects.create(
            session=self.session, user=self.user3, role=ParticipantRole.PARTICIPANT
        )
        # Pre-vote 2 participants
        SessionVote.objects.create(
            session=self.session, participant=self.p1, suspect_chosen="Eddie"
        )
        SessionVote.objects.create(
            session=self.session, participant=self.p2, suspect_chosen="Mickey"
        )

    @patch("apps.sessions.views._broadcast_session_event")
    def test_all_voted_broadcast_on_last_vote(self, mock_broadcast):
        """ALL_VOTED is broadcast when last vote is cast."""
        self.client.force_authenticate(user=self.user3)
        response = self.client.post(
            f"/api/sessions/{self.session.id}/vote/",
            {"suspect": "Eddie"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Should have 2 broadcasts: VOTE_CAST and ALL_VOTED
        self.assertEqual(mock_broadcast.call_count, 2)

        # Second call should be ALL_VOTED
        all_voted_call = mock_broadcast.call_args_list[1]
        self.assertEqual(all_voted_call[1]["event_type"], "ALL_VOTED")

        payload = all_voted_call[1]["payload"]
        self.assertEqual(len(payload["results"]), 3)
        self.assertEqual(payload["guilty"], "Eddie")
        self.assertEqual(payload["success_rate"], 66)  # 2/3
        self.assertEqual(payload["closing_in_seconds"], 15)


class CloseSessionEndpointTests(APITestCase):
    def setUp(self):
        self.host = User.objects.create_user(
            username="host", email="host@example.com", password="pass123"
        )
        self.player = User.objects.create_user(
            username="player", email="player@example.com", password="pass123"
        )

        self.session = Session.objects.create(
            title="Test Murder Mystery",
            context=SessionContext.MURDER_MYSTERY,
            state=SessionState.CONCLUSION,
            min_size=3,
            max_size=3,
            host=self.host,
        )
        self.p_host = SessionParticipant.objects.create(
            session=self.session, user=self.host, role=ParticipantRole.HOST
        )
        self.p_player = SessionParticipant.objects.create(
            session=self.session, user=self.player, role=ParticipantRole.PARTICIPANT
        )

    def test_close_not_host(self):
        """Non-host cannot close session."""
        # Everyone voted
        SessionVote.objects.create(
            session=self.session, participant=self.p_host, suspect_chosen="Eddie"
        )
        SessionVote.objects.create(
            session=self.session, participant=self.p_player, suspect_chosen="Eddie"
        )

        self.client.force_authenticate(user=self.player)
        response = self.client.post(f"/api/sessions/{self.session.id}/close/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_close_not_all_voted(self):
        """Cannot close if not all voted."""
        # Only host voted
        SessionVote.objects.create(
            session=self.session, participant=self.p_host, suspect_chosen="Eddie"
        )

        self.client.force_authenticate(user=self.host)
        response = self.client.post(f"/api/sessions/{self.session.id}/close/")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    @patch("apps.sessions.views.close_session")
    @patch("apps.sessions.views._broadcast_session_event")
    def test_close_success(self, mock_broadcast, mock_close):
        """Host can close session after all voted."""
        # Setup mock
        mock_close.return_value = self.session
        self.session.state = SessionState.CLOSED

        # Everyone voted
        SessionVote.objects.create(
            session=self.session, participant=self.p_host, suspect_chosen="Eddie"
        )
        SessionVote.objects.create(
            session=self.session, participant=self.p_player, suspect_chosen="Eddie"
        )

        self.client.force_authenticate(user=self.host)
        response = self.client.post(f"/api/sessions/{self.session.id}/close/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        mock_close.assert_called_once()
