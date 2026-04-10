from django.test import TestCase
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from rest_framework.test import APITestCase
from rest_framework import status

from apps.sessions.models import Session, SessionParticipant, SessionState, ParticipantRole
from apps.tasks.murder_mystery.models import SessionVote

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
            context="murder_mystery",
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
            context="murder_mystery",
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
            context="murder_mystery",
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
            f"/api/tasks/murder-mystery/sessions/{self.session.id}/vote/",
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
            f"/api/tasks/murder-mystery/sessions/{self.session.id}/vote/",
            {"suspect": "InvalidName"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_vote_duplicate(self):
        """Duplicate vote returns 400."""
        self.client.force_authenticate(user=self.user1)
        self.client.post(
            f"/api/tasks/murder-mystery/sessions/{self.session.id}/vote/",
            {"suspect": "Eddie"},
            format="json",
        )
        response = self.client.post(
            f"/api/tasks/murder-mystery/sessions/{self.session.id}/vote/",
            {"suspect": "Mickey"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_vote_not_participant(self):
        """Non-participant returns 403."""
        self.client.force_authenticate(user=self.outsider)
        response = self.client.post(
            f"/api/tasks/murder-mystery/sessions/{self.session.id}/vote/",
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
            f"/api/tasks/murder-mystery/sessions/{self.session.id}/vote/",
            {"suspect": "Eddie"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_vote_unauthenticated(self):
        """Unauthenticated request returns 401."""
        response = self.client.post(
            f"/api/tasks/murder-mystery/sessions/{self.session.id}/vote/",
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
            context="murder_mystery",
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
        response = self.client.get(f"/api/tasks/murder-mystery/sessions/{self.session.id}/vote-status/")
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
        response = self.client.get(f"/api/tasks/murder-mystery/sessions/{self.session.id}/vote-status/")
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
        response = self.client.get(f"/api/tasks/murder-mystery/sessions/{self.session.id}/vote-status/")
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
            context="murder_mystery",
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

    @patch("apps.tasks.murder_mystery.views._broadcast_session_event")
    def test_all_voted_broadcast_on_last_vote(self, mock_broadcast):
        """ALL_VOTED is broadcast when last vote is cast."""
        self.client.force_authenticate(user=self.user3)
        response = self.client.post(
            f"/api/tasks/murder-mystery/sessions/{self.session.id}/vote/",
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
            context="murder_mystery",
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


from django.core.cache import cache


class CloseSessionReportGenerationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user1 = User.objects.create_user(
            username="host", email="host@example.com", password="pass123"
        )
        self.user2 = User.objects.create_user(
            username="player", email="player@example.com", password="pass123"
        )

        self.session = Session.objects.create(
            title="Test Murder Mystery",
            context="murder_mystery",
            state=SessionState.CONCLUSION,
            min_size=3,
            max_size=3,
            host=self.user1,
            final_summary="Test discussion summary",
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

    def tearDown(self):
        cache.clear()

    @patch("apps.reports.llm_service.ReportLLMService.generate_report_text")
    def test_close_session_generates_report_text(self, mock_llm):
        """close_session should generate report_text via LLM."""
        mock_llm.return_value = "Generated report text"

        from apps.sessions.services import close_session
        session = close_session(str(self.session.id))

        mock_llm.assert_called_once()
        self.assertEqual(session.report_text, "Generated report text")
        self.assertEqual(session.state, SessionState.CLOSED)

    @patch("apps.reports.llm_service.ReportLLMService.generate_report_text")
    def test_close_session_report_data_includes_votes(self, mock_llm):
        """Report generation data should include vote information."""
        mock_llm.return_value = "Report"

        from apps.sessions.services import close_session
        close_session(str(self.session.id))

        # Inspect the call arguments
        call_args = mock_llm.call_args[0][0]  # First positional arg (data dict)
        self.assertIn("votes", call_args)
        self.assertEqual(len(call_args["votes"]), 2)
        self.assertEqual(call_args["guilty"], "Eddie")


class SessionDetailSerializerVotesTests(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            username="host", email="host@example.com", password="pass123"
        )
        self.user2 = User.objects.create_user(
            username="player", email="player@example.com", password="pass123"
        )

        self.session = Session.objects.create(
            title="Test Murder Mystery",
            context="murder_mystery",
            state=SessionState.CLOSED,
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
        SessionVote.objects.create(
            session=self.session, participant=self.p1, suspect_chosen="Eddie"
        )
        SessionVote.objects.create(
            session=self.session, participant=self.p2, suspect_chosen="Mickey"
        )

    def test_report_available_true_when_closed(self):
        """report_available is True when session is CLOSED."""
        from apps.sessions.serializers import SessionDetailSerializer
        from rest_framework.test import APIRequestFactory

        factory = APIRequestFactory()
        request = factory.get('/')
        request.user = self.user1

        serializer = SessionDetailSerializer(self.session, context={'request': request})
        self.assertTrue(serializer.data['report_available'])

    def test_report_available_false_when_not_closed(self):
        """report_available is False when session is not CLOSED."""
        from apps.sessions.serializers import SessionDetailSerializer
        from rest_framework.test import APIRequestFactory

        self.session.state = SessionState.ACTIVE
        self.session.save()

        factory = APIRequestFactory()
        request = factory.get('/')
        request.user = self.user1

        serializer = SessionDetailSerializer(self.session, context={'request': request})
        self.assertFalse(serializer.data['report_available'])

    def test_votes_summary_present_when_closed(self):
        """votes_summary is present when session is CLOSED."""
        from apps.sessions.serializers import SessionDetailSerializer
        from rest_framework.test import APIRequestFactory

        factory = APIRequestFactory()
        request = factory.get('/')
        request.user = self.user1

        serializer = SessionDetailSerializer(self.session, context={'request': request})

        self.assertIn('votes_summary', serializer.data)
        votes_summary = serializer.data['votes_summary']
        self.assertEqual(len(votes_summary['results']), 2)
        self.assertEqual(votes_summary['guilty'], 'Eddie')
        self.assertEqual(votes_summary['success_rate'], 50)

    def test_votes_summary_none_when_not_closed(self):
        """votes_summary is None when session is not CLOSED."""
        from apps.sessions.serializers import SessionDetailSerializer
        from rest_framework.test import APIRequestFactory

        self.session.state = SessionState.ACTIVE
        self.session.save()

        factory = APIRequestFactory()
        request = factory.get('/')
        request.user = self.user1

        serializer = SessionDetailSerializer(self.session, context={'request': request})
        self.assertIsNone(serializer.data['votes_summary'])


class VotingFlowIntegrationTests(APITestCase):
    """End-to-end test of the voting flow."""

    def setUp(self):
        cache.clear()
        self.host = User.objects.create_user(
            username="host", email="host@example.com", password="pass123"
        )
        self.player2 = User.objects.create_user(
            username="player2", email="p2@example.com", password="pass123"
        )
        self.player3 = User.objects.create_user(
            username="player3", email="p3@example.com", password="pass123"
        )

        self.session = Session.objects.create(
            title="Integration Test Session",
            context="murder_mystery",
            state=SessionState.CONCLUSION,
            min_size=3,
            max_size=3,
            host=self.host,
            final_summary="Test summary from moderation",
        )
        self.p1 = SessionParticipant.objects.create(
            session=self.session, user=self.host, role=ParticipantRole.HOST
        )
        self.p2 = SessionParticipant.objects.create(
            session=self.session, user=self.player2, role=ParticipantRole.PARTICIPANT
        )
        self.p3 = SessionParticipant.objects.create(
            session=self.session, user=self.player3, role=ParticipantRole.PARTICIPANT
        )

    def tearDown(self):
        cache.clear()

    @patch("apps.tasks.murder_mystery.views._broadcast_session_event")
    @patch("apps.reports.llm_service.ReportLLMService.generate_report_text")
    def test_full_voting_flow(self, mock_llm, mock_broadcast):
        """Test complete flow: votes -> ALL_VOTED -> close -> download."""
        mock_llm.return_value = "LLM generated report text"

        # 1. First vote
        self.client.force_authenticate(user=self.host)
        response = self.client.post(
            f"/api/tasks/murder-mystery/sessions/{self.session.id}/vote/",
            {"suspect": "Eddie"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # 2. Second vote
        self.client.force_authenticate(user=self.player2)
        response = self.client.post(
            f"/api/tasks/murder-mystery/sessions/{self.session.id}/vote/",
            {"suspect": "Mickey"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # 3. Third vote (triggers ALL_VOTED)
        self.client.force_authenticate(user=self.player3)
        response = self.client.post(
            f"/api/tasks/murder-mystery/sessions/{self.session.id}/vote/",
            {"suspect": "Eddie"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify ALL_VOTED was broadcast
        all_voted_calls = [
            call for call in mock_broadcast.call_args_list
            if call[1].get("event_type") == "ALL_VOTED"
        ]
        self.assertEqual(len(all_voted_calls), 1)

        # 4. Host closes session
        self.client.force_authenticate(user=self.host)
        response = self.client.post(f"/api/sessions/{self.session.id}/close/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify session is CLOSED
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, SessionState.CLOSED)
        self.assertEqual(self.session.report_text, "LLM generated report text")

        # 5. Download report
        response = self.client.get(f"/api/sessions/{self.session.id}/report/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'application/pdf')

        # 6. Verify session detail includes votes_summary
        response = self.client.get(f"/api/sessions/{self.session.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['report_available'])
        self.assertIsNotNone(response.data['votes_summary'])
        self.assertEqual(response.data['votes_summary']['success_rate'], 66)
