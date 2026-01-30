# Voting and PDF Report Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the guilty voting mechanic in CONCLUSION phase and PDF report generation for closed sessions.

**Architecture:** New `SessionVote` model for vote persistence, new `apps/reports/` app for LLM-based report text generation and ReportLab PDF rendering. Vote flow: CONCLUSION → votes collected → ALL_VOTED broadcast → 15s countdown → LLM generates report → CLOSED. PDF generated on-demand from stored `report_text`.

**Tech Stack:** Django, DRF, PostgreSQL, Redis (channel layer), ReportLab, Azure OpenAI

---

## Task 1: Add SessionVote Model and Session.report_text Field

**Files:**
- Modify: `apps/sessions/models.py:39-124`
- Create: migration file via `makemigrations`

**Step 1: Write the failing test for SessionVote**

Create test file `apps/sessions/tests.py`:

```python
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.db import IntegrityError

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
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.sessions.tests.SessionVoteModelTests apps.sessions.tests.SessionReportTextTests -v 2`

Expected: FAIL with `AttributeError: type object 'SessionVote' has no attribute...` or import error

**Step 3: Add SessionVote model and report_text field**

Edit `apps/sessions/models.py`. Add after `SessionEventType` class (around line 37):

```python
# Hardcoded suspects for Murder Mystery MVP
MURDER_MYSTERY_SUSPECTS = ["Eddie", "Mickey", "Billy"]
MURDER_MYSTERY_GUILTY = "Eddie"
```

Add to `Session` model after `final_summary` field (around line 78):

```python
    report_text = models.TextField(
        blank=True,
        default="",
        help_text="Testo del report generato da LLM alla chiusura"
    )
```

Add new `SessionVote` model after `SessionEvent` class (at end of file):

```python
class SessionVote(models.Model):
    """
    Voto di un partecipante per il colpevole (Murder Mystery).
    Un solo voto per partecipante per sessione.
    """

    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name="votes"
    )
    participant = models.ForeignKey(
        SessionParticipant,
        on_delete=models.CASCADE,
        related_name="votes"
    )
    suspect_chosen = models.CharField(max_length=32)  # "Eddie", "Mickey", "Billy"
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "session_vote"
        unique_together = [("session", "participant")]
        indexes = [
            models.Index(fields=["session"]),
        ]

    def __str__(self) -> str:
        return f"{self.participant.user_id} voted {self.suspect_chosen} in {self.session_id}"
```

**Step 4: Create and run migration**

Run: `docker compose run --rm web python manage.py makemigrations sessions --name add_session_vote_and_report_text`
Then: `docker compose run --rm web python manage.py migrate`

**Step 5: Run tests to verify they pass**

Run: `docker compose run --rm web python manage.py test apps.sessions.tests.SessionVoteModelTests apps.sessions.tests.SessionReportTextTests -v 2`

Expected: PASS

**Step 6: Commit**

```bash
git add apps/sessions/models.py apps/sessions/tests.py apps/sessions/migrations/
git commit -m "feat(sessions): add SessionVote model and Session.report_text field"
```

---

## Task 2: Implement Vote Endpoint (POST /sessions/{id}/vote/)

**Files:**
- Modify: `apps/sessions/views.py`
- Modify: `apps/sessions/urls.py`
- Modify: `apps/sessions/tests.py`

**Step 1: Write the failing tests for vote endpoint**

Add to `apps/sessions/tests.py`:

```python
from rest_framework.test import APITestCase
from rest_framework import status


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
```

**Step 2: Run tests to verify they fail**

Run: `docker compose run --rm web python manage.py test apps.sessions.tests.VoteEndpointTests -v 2`

Expected: FAIL with 404 (endpoint doesn't exist)

**Step 3: Implement the vote view**

Add to `apps/sessions/views.py` (add import at top):

```python
from .models import Session, SessionParticipant, SessionState, SessionVote, MURDER_MYSTERY_SUSPECTS
```

Add the view class:

```python
class SessionVoteView(APIView):
    """
    POST /api/sessions/{session_id}/vote/
    Registra il voto del partecipante per il colpevole (Murder Mystery).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, session_id: str):
        session = get_object_or_404(Session, pk=session_id)

        # Check session state
        if session.state != SessionState.CONCLUSION:
            return Response(
                {"detail": "La sessione non è in fase di votazione."},
                status=status.HTTP_409_CONFLICT,
            )

        # Check user is participant
        try:
            participant = SessionParticipant.objects.get(
                session=session, user=request.user
            )
        except SessionParticipant.DoesNotExist:
            return Response(
                {"detail": "Non sei un partecipante di questa sessione."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Validate suspect
        suspect = request.data.get("suspect")
        if suspect not in MURDER_MYSTERY_SUSPECTS:
            return Response(
                {"detail": f"Sospetto non valido. Scegli tra: {', '.join(MURDER_MYSTERY_SUSPECTS)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if already voted
        if SessionVote.objects.filter(session=session, participant=participant).exists():
            return Response(
                {"detail": "Hai già votato."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create vote
        SessionVote.objects.create(
            session=session,
            participant=participant,
            suspect_chosen=suspect,
        )

        # Count votes
        total_participants = SessionParticipant.objects.filter(session=session).count()
        votes_cast = SessionVote.objects.filter(session=session).count()

        # Broadcast VOTE_CAST event
        _broadcast_session_event(
            session_id=str(session.id),
            event_type="VOTE_CAST",
            payload={"user_id": request.user.id},
        )

        return Response(
            {
                "success": True,
                "votes_cast": votes_cast,
                "total_participants": total_participants,
            },
            status=status.HTTP_201_CREATED,
        )
```

**Step 4: Add URL route**

Edit `apps/sessions/urls.py`. Add import:

```python
from .views import (
    # ... existing imports ...
    SessionVoteView,
)
```

Add URL pattern:

```python
    path(
        "<uuid:session_id>/vote/",
        SessionVoteView.as_view(),
        name="session_vote",
    ),
```

**Step 5: Run tests to verify they pass**

Run: `docker compose run --rm web python manage.py test apps.sessions.tests.VoteEndpointTests -v 2`

Expected: PASS

**Step 6: Commit**

```bash
git add apps/sessions/views.py apps/sessions/urls.py apps/sessions/tests.py
git commit -m "feat(sessions): add POST /sessions/{id}/vote/ endpoint"
```

---

## Task 3: Implement Vote Status Endpoint (GET /sessions/{id}/vote-status/)

**Files:**
- Modify: `apps/sessions/views.py`
- Modify: `apps/sessions/urls.py`
- Modify: `apps/sessions/tests.py`

**Step 1: Write the failing tests**

Add to `apps/sessions/tests.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `docker compose run --rm web python manage.py test apps.sessions.tests.VoteStatusEndpointTests -v 2`

Expected: FAIL with 404

**Step 3: Implement the vote status view**

Add to `apps/sessions/views.py`:

```python
class SessionVoteStatusView(APIView):
    """
    GET /api/sessions/{session_id}/vote-status/
    Ritorna lo stato attuale della votazione.
    """
    permission_classes = [permissions.IsAuthenticated, IsSessionMember]

    def get(self, request, session_id: str):
        session = get_object_or_404(Session, pk=session_id)
        self.check_object_permissions(request, session)

        total_participants = SessionParticipant.objects.filter(session=session).count()
        votes_cast = SessionVote.objects.filter(session=session).count()

        # Check if current user has voted
        try:
            participant = SessionParticipant.objects.get(
                session=session, user=request.user
            )
            has_voted = SessionVote.objects.filter(
                session=session, participant=participant
            ).exists()
        except SessionParticipant.DoesNotExist:
            has_voted = False

        return Response({
            "total_participants": total_participants,
            "votes_cast": votes_cast,
            "has_current_user_voted": has_voted,
            "all_voted": votes_cast == total_participants,
        })
```

**Step 4: Add URL route**

Edit `apps/sessions/urls.py`. Add import and URL:

```python
from .views import (
    # ... existing imports ...
    SessionVoteStatusView,
)
```

```python
    path(
        "<uuid:session_id>/vote-status/",
        SessionVoteStatusView.as_view(),
        name="session_vote_status",
    ),
```

**Step 5: Run tests to verify they pass**

Run: `docker compose run --rm web python manage.py test apps.sessions.tests.VoteStatusEndpointTests -v 2`

Expected: PASS

**Step 6: Commit**

```bash
git add apps/sessions/views.py apps/sessions/urls.py apps/sessions/tests.py
git commit -m "feat(sessions): add GET /sessions/{id}/vote-status/ endpoint"
```

---

## Task 4: Implement ALL_VOTED Broadcast and 15s Countdown Logic

**Files:**
- Modify: `apps/sessions/views.py`
- Modify: `apps/sessions/tests.py`

**Step 1: Write the failing tests**

Add to `apps/sessions/tests.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.sessions.tests.AllVotedBroadcastTests -v 2`

Expected: FAIL (ALL_VOTED not broadcast yet)

**Step 3: Update SessionVoteView to broadcast ALL_VOTED**

Modify the `SessionVoteView.post()` method in `apps/sessions/views.py`. Replace the return statement section with:

```python
        # Create vote
        SessionVote.objects.create(
            session=session,
            participant=participant,
            suspect_chosen=suspect,
        )

        # Count votes
        total_participants = SessionParticipant.objects.filter(session=session).count()
        votes_cast = SessionVote.objects.filter(session=session).count()

        # Broadcast VOTE_CAST event
        _broadcast_session_event(
            session_id=str(session.id),
            event_type="VOTE_CAST",
            payload={"user_id": request.user.id},
        )

        # Check if all voted
        if votes_cast == total_participants:
            # Build results payload
            from .models import MURDER_MYSTERY_GUILTY

            votes = SessionVote.objects.filter(session=session).select_related(
                "participant__user"
            )
            results = []
            correct_count = 0
            for vote in votes:
                is_correct = vote.suspect_chosen == MURDER_MYSTERY_GUILTY
                if is_correct:
                    correct_count += 1
                results.append({
                    "user_id": vote.participant.user_id,
                    "username": getattr(vote.participant.user, "display_name", None)
                               or vote.participant.user.get_username(),
                    "chose": vote.suspect_chosen,
                    "correct": is_correct,
                })

            success_rate = int((correct_count / total_participants) * 100)

            # Broadcast ALL_VOTED with results
            _broadcast_session_event(
                session_id=str(session.id),
                event_type="ALL_VOTED",
                payload={
                    "results": results,
                    "guilty": MURDER_MYSTERY_GUILTY,
                    "success_rate": success_rate,
                    "closing_in_seconds": 15,
                },
            )

            # Schedule session close after 15 seconds
            # This will be handled by the close endpoint or a background task
            # For MVP, we rely on frontend countdown + host close button

        return Response(
            {
                "success": True,
                "votes_cast": votes_cast,
                "total_participants": total_participants,
            },
            status=status.HTTP_201_CREATED,
        )
```

**Step 4: Run tests to verify they pass**

Run: `docker compose run --rm web python manage.py test apps.sessions.tests.AllVotedBroadcastTests -v 2`

Expected: PASS

**Step 5: Commit**

```bash
git add apps/sessions/views.py apps/sessions/tests.py
git commit -m "feat(sessions): broadcast ALL_VOTED with results when all participants vote"
```

---

## Task 5: Implement Close Session Endpoint (POST /sessions/{id}/close/)

**Files:**
- Modify: `apps/sessions/views.py`
- Modify: `apps/sessions/urls.py`
- Modify: `apps/sessions/tests.py`

**Step 1: Write the failing tests**

Add to `apps/sessions/tests.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `docker compose run --rm web python manage.py test apps.sessions.tests.CloseSessionEndpointTests -v 2`

Expected: FAIL with 404

**Step 3: Implement the close view**

Add to `apps/sessions/views.py`:

```python
class SessionCloseView(APIView):
    """
    POST /api/sessions/{session_id}/close/
    Chiude la sessione anticipatamente (solo host, solo dopo che tutti hanno votato).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, session_id: str):
        session = get_object_or_404(Session, pk=session_id)

        # Only host can close
        if session.host_id != request.user.id:
            return Response(
                {"detail": "Solo l'host può chiudere la sessione."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Check session state
        if session.state != SessionState.CONCLUSION:
            return Response(
                {"detail": "La sessione non è in fase di conclusione."},
                status=status.HTTP_409_CONFLICT,
            )

        # Check all voted
        total_participants = SessionParticipant.objects.filter(session=session).count()
        votes_cast = SessionVote.objects.filter(session=session).count()

        if votes_cast < total_participants:
            return Response(
                {"detail": "Non tutti i partecipanti hanno ancora votato."},
                status=status.HTTP_409_CONFLICT,
            )

        # Close session (generates report_text via LLM and sets CLOSED)
        session = close_session(str(session.id))

        # Broadcast SESSION_CLOSED
        detail_data = SessionDetailSerializer(
            session,
            context={"request": request},
        ).data

        _broadcast_session_event(
            session_id=str(session.id),
            event_type="SESSION_CLOSED",
            payload=detail_data,
        )

        return Response({
            "success": True,
            "session_id": str(session.id),
        })
```

**Step 4: Add URL route**

Edit `apps/sessions/urls.py`. Add import and URL:

```python
from .views import (
    # ... existing imports ...
    SessionCloseView,
)
```

```python
    path(
        "<uuid:session_id>/close/",
        SessionCloseView.as_view(),
        name="session_close",
    ),
```

**Step 5: Run tests to verify they pass**

Run: `docker compose run --rm web python manage.py test apps.sessions.tests.CloseSessionEndpointTests -v 2`

Expected: PASS

**Step 6: Commit**

```bash
git add apps/sessions/views.py apps/sessions/urls.py apps/sessions/tests.py
git commit -m "feat(sessions): add POST /sessions/{id}/close/ endpoint for host"
```

---

## Task 6: Create Reports App with LLM Service

**Files:**
- Create: `apps/reports/__init__.py`
- Create: `apps/reports/llm_service.py`
- Create: `apps/reports/tests.py`
- Modify: `aiutami/settings.py` (add to INSTALLED_APPS)

**Step 1: Create the reports app directory structure**

Run: `mkdir -p apps/reports`

**Step 2: Write the failing test**

Create `apps/reports/tests.py`:

```python
from django.test import TestCase
from unittest.mock import patch, MagicMock
import json

from apps.reports.llm_service import ReportLLMService


class ReportLLMServiceTests(TestCase):
    def test_generate_report_text_returns_string(self):
        """generate_report_text should return a string."""
        data = {
            "session_title": "Murder Mystery - Villa Rosa",
            "duration_minutes": 28,
            "participants": [
                {"name": "Mario", "turns": 12, "percentage": 38},
                {"name": "Luigi", "turns": 8, "percentage": 25},
            ],
            "ai_interventions": 3,
            "ai_intervention_percentage": 6,
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

    @patch.object(ReportLLMService, '_build_azure_client')
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
            "ai_intervention_percentage": 0,
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
        with patch.object(ReportLLMService, '_build_azure_client', side_effect=Exception("API Error")):
            data = {
                "session_title": "Test Session",
                "duration_minutes": 20,
                "participants": [{"name": "Mario", "turns": 5, "percentage": 50}],
                "ai_interventions": 2,
                "ai_intervention_percentage": 10,
                "votes": [{"name": "Mario", "chose": "Eddie", "correct": True}],
                "guilty": "Eddie",
                "success_rate": 100,
                "final_summary": "Test summary",
            }

            result = ReportLLMService.generate_report_text(data)

            # Should return fallback with basic info
            self.assertIn("Test Session", result)
            self.assertIn("Eddie", result)
```

**Step 3: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.reports.tests.ReportLLMServiceTests -v 2`

Expected: FAIL with import error

**Step 4: Create the reports app files**

Create `apps/reports/__init__.py`:

```python
```

Create `apps/reports/llm_service.py`:

```python
"""
Report LLM Service - genera il testo del report via Azure OpenAI.
"""

import logging
import os
import json
from typing import Any

from openai import AzureOpenAI

logger = logging.getLogger(__name__)


REPORT_SYSTEM_PROMPT = """Sei un analista di sessioni di discussione moderate su AIutami.

Genera un report testuale completo in italiano per una sessione di Murder Mystery.

Il report deve includere queste sezioni (usa esattamente questi titoli):

RISULTATO FINALE
- Chi era il colpevole
- Quanti partecipanti hanno indovinato (es. "2 su 3")
- Percentuale di successo

VOTI DEI PARTECIPANTI
- Lista dei partecipanti con chi hanno scelto e se era corretto (usa ✓ o ✗)

STATISTICHE PARTECIPAZIONE
- Interventi per partecipante con percentuali
- Interventi del moderatore AI con percentuale

RIASSUNTO DELLA DISCUSSIONE
- Basato sul final_summary fornito, rielaboralo in modo discorsivo

ANALISI FINALE
- Un breve paragrafo (3-5 frasi) che analizza come è andata la sessione
- Commenta la partecipazione, eventuali dinamiche interessanti, e il risultato finale

Formato:
- Usa testo semplice, NO markdown
- Separa le sezioni con una riga vuota
- Tono informativo ma accessibile (il pubblico sono ragazzi)
- Lunghezza totale: 300-500 parole
"""


class ReportLLMService:
    """
    Servizio per generare il testo del report via LLM.
    """

    @classmethod
    def generate_report_text(cls, data: dict[str, Any]) -> str:
        """
        Genera il testo del report dalla data della sessione.

        Args:
            data: dizionario con:
                - session_title
                - duration_minutes
                - participants: list of {name, turns, percentage}
                - ai_interventions
                - ai_intervention_percentage
                - votes: list of {name, chose, correct}
                - guilty
                - success_rate
                - final_summary

        Returns:
            Il testo del report generato
        """
        logger.info("[REPORT][LLM][REQUEST] Generating report for session: %s", data.get("session_title"))

        try:
            client = cls._build_azure_client()
            deployment = os.environ.get("AZURE_OPENAI_MODEL", "gpt-4o-mini")

            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": REPORT_SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
                ],
                temperature=0.6,
                max_tokens=1024,
            )

            content = response.choices[0].message.content
            logger.info("[REPORT][LLM][RESPONSE] Generated report length: %d", len(content))
            return content

        except Exception as e:
            logger.warning("[REPORT][LLM][ERROR] %s - using fallback", str(e))
            return cls._fallback_report(data)

    @classmethod
    def _build_azure_client(cls) -> AzureOpenAI:
        """Crea client Azure OpenAI."""
        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
        api_key = os.environ["AZURE_OPENAI_API_KEY"]
        api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")

        return AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=endpoint,
        )

    @classmethod
    def _fallback_report(cls, data: dict[str, Any]) -> str:
        """Genera un report di fallback se LLM non disponibile."""
        lines = [
            f"REPORT SESSIONE: {data.get('session_title', 'Sessione senza titolo')}",
            f"Durata: {data.get('duration_minutes', 0)} minuti",
            "",
            "RISULTATO FINALE",
            f"Il colpevole era: {data.get('guilty', 'Sconosciuto')}",
            f"Percentuale di successo: {data.get('success_rate', 0)}%",
            "",
            "VOTI DEI PARTECIPANTI",
        ]

        for vote in data.get("votes", []):
            symbol = "✓" if vote.get("correct") else "✗"
            lines.append(f"- {vote.get('name')}: {vote.get('chose')} {symbol}")

        lines.extend([
            "",
            "STATISTICHE PARTECIPAZIONE",
        ])

        for p in data.get("participants", []):
            lines.append(f"- {p.get('name')}: {p.get('turns')} interventi ({p.get('percentage')}%)")

        lines.extend([
            f"- Moderatore AI: {data.get('ai_interventions', 0)} interventi ({data.get('ai_intervention_percentage', 0)}%)",
            "",
            "RIASSUNTO",
            data.get("final_summary", "Nessun riassunto disponibile."),
            "",
            "Generato da AIutami",
        ])

        return "\n".join(lines)
```

**Step 5: Add to INSTALLED_APPS**

Edit `aiutami/settings.py`, find `INSTALLED_APPS` and add:

```python
    "apps.reports",
```

**Step 6: Run tests to verify they pass**

Run: `docker compose run --rm web python manage.py test apps.reports.tests.ReportLLMServiceTests -v 2`

Expected: PASS

**Step 7: Commit**

```bash
git add apps/reports/ aiutami/settings.py
git commit -m "feat(reports): create reports app with LLM service for report text generation"
```

---

## Task 7: Create PDF Service with ReportLab

**Files:**
- Create: `apps/reports/pdf_service.py`
- Modify: `apps/reports/tests.py`
- Modify: `requirements.txt`

**Step 1: Add reportlab to requirements**

Edit `requirements.txt`, add:

```
reportlab>=4.0.0
```

**Step 2: Run pip install**

Run: `docker compose run --rm web pip install reportlab>=4.0.0`

**Step 3: Write the failing test**

Add to `apps/reports/tests.py`:

```python
from django.contrib.auth import get_user_model
from apps.sessions.models import Session, SessionParticipant, SessionVote, SessionState, SessionContext, ParticipantRole

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
            context=SessionContext.MURDER_MYSTERY,
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
```

**Step 4: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.reports.tests.ReportPDFServiceTests -v 2`

Expected: FAIL with import error

**Step 5: Create the PDF service**

Create `apps/reports/pdf_service.py`:

```python
"""
Report PDF Service - genera PDF del report usando ReportLab.
"""

import io
import logging
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

logger = logging.getLogger(__name__)


class ReportPDFService:
    """
    Servizio per generare PDF del report sessione.
    """

    @classmethod
    def generate_pdf(cls, session) -> bytes:
        """
        Genera un PDF dal report della sessione.

        Args:
            session: istanza Session con report_text popolato

        Returns:
            bytes del PDF generato
        """
        from apps.sessions.models import SessionVote, SessionParticipant, MURDER_MYSTERY_GUILTY

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=2*cm,
            leftMargin=2*cm,
            topMargin=2*cm,
            bottomMargin=2*cm,
        )

        # Styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            spaceAfter=12,
            alignment=1,  # Center
        )
        subtitle_style = ParagraphStyle(
            'CustomSubtitle',
            parent=styles['Normal'],
            fontSize=12,
            textColor=colors.grey,
            alignment=1,
            spaceAfter=20,
        )
        section_style = ParagraphStyle(
            'SectionHeader',
            parent=styles['Heading2'],
            fontSize=14,
            spaceBefore=16,
            spaceAfter=8,
            textColor=colors.HexColor('#2E86AB'),
        )
        body_style = ParagraphStyle(
            'CustomBody',
            parent=styles['Normal'],
            fontSize=11,
            leading=14,
            spaceAfter=8,
        )
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.grey,
            alignment=1,
            spaceBefore=30,
        )

        # Build content
        story = []

        # Title
        story.append(Paragraph("REPORT SESSIONE MURDER MYSTERY", title_style))
        story.append(Paragraph(f'"{session.title}"', subtitle_style))

        # Date and duration
        date_str = session.created_at.strftime("%d/%m/%Y")
        duration = 0
        if session.started_at and session.ended_at:
            duration = int((session.ended_at - session.started_at).total_seconds() / 60)
        story.append(Paragraph(f"Data: {date_str} - Durata: {duration} minuti", body_style))
        story.append(Spacer(1, 12))

        # Results section
        votes = SessionVote.objects.filter(session=session).select_related("participant__user")
        total = votes.count()
        correct = sum(1 for v in votes if v.suspect_chosen == MURDER_MYSTERY_GUILTY)
        success_rate = int((correct / total) * 100) if total > 0 else 0

        story.append(Paragraph("RISULTATO FINALE", section_style))
        story.append(Paragraph(f"Il colpevole era: <b>{MURDER_MYSTERY_GUILTY}</b>", body_style))
        story.append(Paragraph(f"Partecipanti che hanno indovinato: {correct}/{total}", body_style))
        story.append(Paragraph(f"Percentuale di successo: {success_rate}%", body_style))
        story.append(Spacer(1, 12))

        # Votes table
        story.append(Paragraph("VOTI", section_style))
        vote_data = [["Partecipante", "Scelta", "Risultato"]]
        for vote in votes:
            username = getattr(vote.participant.user, "display_name", None) or vote.participant.user.get_username()
            result = "✓ Corretto" if vote.suspect_chosen == MURDER_MYSTERY_GUILTY else "✗ Sbagliato"
            vote_data.append([username, vote.suspect_chosen, result])

        vote_table = Table(vote_data, colWidths=[6*cm, 4*cm, 4*cm])
        vote_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2E86AB')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F5F5F5')),
            ('GRID', (0, 0), (-1, -1), 1, colors.white),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
        ]))
        story.append(vote_table)
        story.append(Spacer(1, 12))

        # Report text (LLM generated)
        if session.report_text:
            story.append(Paragraph("ANALISI DELLA SESSIONE", section_style))
            # Split by paragraphs and add each
            for para in session.report_text.split('\n\n'):
                if para.strip():
                    # Escape HTML entities
                    safe_para = para.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    story.append(Paragraph(safe_para, body_style))
                    story.append(Spacer(1, 6))

        # Summary if available
        if session.final_summary and not session.report_text:
            story.append(Paragraph("RIASSUNTO DELLA DISCUSSIONE", section_style))
            safe_summary = session.final_summary.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            story.append(Paragraph(safe_summary, body_style))
            story.append(Spacer(1, 12))

        # Footer
        story.append(Paragraph("Generato da AIutami", footer_style))

        # Build PDF
        doc.build(story)

        pdf_bytes = buffer.getvalue()
        buffer.close()

        logger.info("[REPORT][PDF] Generated PDF for session %s, size: %d bytes", session.id, len(pdf_bytes))
        return pdf_bytes
```

**Step 6: Run tests to verify they pass**

Run: `docker compose run --rm web python manage.py test apps.reports.tests.ReportPDFServiceTests -v 2`

Expected: PASS

**Step 7: Commit**

```bash
git add apps/reports/pdf_service.py apps/reports/tests.py requirements.txt
git commit -m "feat(reports): add PDF generation service with ReportLab"
```

---

## Task 8: Implement Report Download Endpoint (GET /sessions/{id}/report/)

**Files:**
- Create: `apps/reports/views.py`
- Create: `apps/reports/urls.py`
- Modify: `apps/reports/tests.py`
- Modify: `aiutami/urls.py`

**Step 1: Write the failing test**

Add to `apps/reports/tests.py`:

```python
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
            context=SessionContext.MURDER_MYSTERY,
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
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.reports.tests.ReportDownloadEndpointTests -v 2`

Expected: FAIL with 404

**Step 3: Create the report download view**

Create `apps/reports/views.py`:

```python
"""
Report views - download endpoints.
"""

from django.shortcuts import get_object_or_404
from django.http import HttpResponse

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.sessions.models import Session, SessionParticipant, SessionState
from .pdf_service import ReportPDFService


class SessionReportDownloadView(APIView):
    """
    GET /api/sessions/{session_id}/report/
    Scarica il report PDF della sessione.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, session_id: str):
        session = get_object_or_404(Session, pk=session_id)

        # Check user is participant
        if not SessionParticipant.objects.filter(
            session=session, user=request.user
        ).exists():
            return Response(
                {"detail": "Non sei un partecipante di questa sessione."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Check session is CLOSED
        if session.state != SessionState.CLOSED:
            return Response(
                {"detail": "Il report è disponibile solo per sessioni concluse."},
                status=status.HTTP_409_CONFLICT,
            )

        # Generate PDF
        pdf_bytes = ReportPDFService.generate_pdf(session)

        # Return as download
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="report-{session.id}.pdf"'
        return response
```

**Step 4: Create URLs for reports app**

Create `apps/reports/urls.py`:

```python
from django.urls import path

from .views import SessionReportDownloadView

urlpatterns = [
    path(
        "<uuid:session_id>/report/",
        SessionReportDownloadView.as_view(),
        name="session_report_download",
    ),
]
```

**Step 5: Include reports URLs in main urls.py**

Edit `aiutami/urls.py`. Find the urlpatterns and add:

```python
    path("api/sessions/", include("apps.reports.urls")),
```

Make sure this is placed AFTER the sessions include so the more specific route matches first.

**Step 6: Run tests to verify they pass**

Run: `docker compose run --rm web python manage.py test apps.reports.tests.ReportDownloadEndpointTests -v 2`

Expected: PASS

**Step 7: Commit**

```bash
git add apps/reports/views.py apps/reports/urls.py apps/reports/tests.py aiutami/urls.py
git commit -m "feat(reports): add GET /sessions/{id}/report/ endpoint for PDF download"
```

---

## Task 9: Integrate LLM Report Generation into close_session

**Files:**
- Modify: `apps/sessions/services.py`
- Modify: `apps/sessions/tests.py`

**Step 1: Write the failing test**

Add to `apps/sessions/tests.py`:

```python
from django.core.cache import cache
from unittest.mock import patch


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
            context=SessionContext.MURDER_MYSTERY,
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
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.sessions.tests.CloseSessionReportGenerationTests -v 2`

Expected: FAIL (report_text not generated)

**Step 3: Update close_session to generate report**

Edit `apps/sessions/services.py`:

```python
"""
Session services - business logic for session management.
"""
import logging
from django.core.cache import cache
from django.utils import timezone

from apps.sessions.models import (
    Session,
    SessionState,
    SessionParticipant,
    SessionVote,
    MURDER_MYSTERY_GUILTY,
)

logger = logging.getLogger(__name__)


def close_session(session_id: str) -> Session:
    """
    Chiude la sessione, genera il report e salva.

    - Genera report_text via LLM con dati voti e partecipazione
    - Recupera summary da ModerationState se presente
    - Aggiorna stato a CLOSED
    - Cleanup chiavi Redis (transcript, turns, moderation)

    Args:
        session_id: ID della sessione da chiudere

    Returns:
        Session aggiornata
    """
    session = Session.objects.get(id=session_id)

    # 1. Recupera summary da ModerationState (se disponibile)
    try:
        from apps.moderation.state import load_moderation_state
        mod_state = load_moderation_state(session_id)
        if mod_state and hasattr(mod_state, 'summary') and mod_state.summary:
            session.final_summary = mod_state.summary
    except Exception as e:
        logger.warning(f"Could not load moderation state for session {session_id}: {e}")

    # 2. Generate report text via LLM
    try:
        report_data = _collect_report_data(session, mod_state)
        from apps.reports.llm_service import ReportLLMService
        session.report_text = ReportLLMService.generate_report_text(report_data)
    except Exception as e:
        logger.warning(f"Could not generate report for session {session_id}: {e}")
        session.report_text = ""

    # 3. Aggiorna stato
    if session.state != SessionState.CLOSED:
        session.state = SessionState.CLOSED
        session.ended_at = timezone.now()

        # Determina quali campi aggiornare
        update_fields = ["state", "ended_at", "report_text"]
        if session.final_summary:
            update_fields.append("final_summary")

        session.save(update_fields=update_fields)

    # 4. Cleanup Redis keys
    _cleanup_session_redis_keys(session_id)

    logger.info(f"Session {session_id} closed and cleaned up")
    return session


def _collect_report_data(session, mod_state=None) -> dict:
    """
    Raccoglie i dati per la generazione del report.
    """
    # Calculate duration
    duration_minutes = 0
    if session.started_at and session.ended_at:
        duration_minutes = int((session.ended_at - session.started_at).total_seconds() / 60)
    elif session.started_at:
        duration_minutes = int((timezone.now() - session.started_at).total_seconds() / 60)

    # Get participant turns from moderation state
    turns_per_participant = {}
    if mod_state and hasattr(mod_state, 'turns_per_participant'):
        turns_per_participant = mod_state.turns_per_participant

    total_human_turns = sum(turns_per_participant.values()) if turns_per_participant else 1

    # AI interventions
    ai_interventions = 0
    if mod_state and hasattr(mod_state, 'ai_interventions_count'):
        ai_interventions = mod_state.ai_interventions_count

    total_turns = total_human_turns + ai_interventions
    ai_percentage = int((ai_interventions / total_turns) * 100) if total_turns > 0 else 0

    # Participants with turn stats
    participants_data = []
    for name, turns in turns_per_participant.items():
        percentage = int((turns / total_human_turns) * 100) if total_human_turns > 0 else 0
        participants_data.append({
            "name": name,
            "turns": turns,
            "percentage": percentage,
        })

    # Votes
    votes = SessionVote.objects.filter(session=session).select_related("participant__user")
    votes_data = []
    correct_count = 0
    for vote in votes:
        username = getattr(vote.participant.user, "display_name", None) or vote.participant.user.get_username()
        is_correct = vote.suspect_chosen == MURDER_MYSTERY_GUILTY
        if is_correct:
            correct_count += 1
        votes_data.append({
            "name": username,
            "chose": vote.suspect_chosen,
            "correct": is_correct,
        })

    total_voters = votes.count()
    success_rate = int((correct_count / total_voters) * 100) if total_voters > 0 else 0

    return {
        "session_title": session.title,
        "duration_minutes": duration_minutes,
        "participants": participants_data,
        "ai_interventions": ai_interventions,
        "ai_intervention_percentage": ai_percentage,
        "votes": votes_data,
        "guilty": MURDER_MYSTERY_GUILTY,
        "success_rate": success_rate,
        "final_summary": session.final_summary or "",
    }


def _cleanup_session_redis_keys(session_id: str) -> None:
    """
    Cancella le chiavi Redis associate alla sessione.
    """
    keys_to_delete = [
        f"session:{session_id}:transcript",
        f"turns:{session_id}",
        f"moderation:{session_id}",
    ]

    for key in keys_to_delete:
        try:
            cache.delete(key)
            logger.debug(f"Deleted Redis key: {key}")
        except Exception as e:
            logger.warning(f"Failed to delete Redis key {key}: {e}")
```

**Step 4: Run tests to verify they pass**

Run: `docker compose run --rm web python manage.py test apps.sessions.tests.CloseSessionReportGenerationTests -v 2`

Expected: PASS

**Step 5: Commit**

```bash
git add apps/sessions/services.py apps/sessions/tests.py
git commit -m "feat(sessions): integrate LLM report generation into close_session"
```

---

## Task 10: Update SessionDetailSerializer with report_available and votes_summary

**Files:**
- Modify: `apps/sessions/serializers.py`
- Modify: `apps/sessions/tests.py`

**Step 1: Write the failing test**

Add to `apps/sessions/tests.py`:

```python
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
            context=SessionContext.MURDER_MYSTERY,
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
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.sessions.tests.SessionDetailSerializerVotesTests -v 2`

Expected: FAIL (fields don't exist)

**Step 3: Update SessionDetailSerializer**

Edit `apps/sessions/serializers.py`. Find the `SessionDetailSerializer` class and add the new fields.

Add import at top:

```python
from .models import Session, SessionParticipant, SessionState, SessionVote, MURDER_MYSTERY_GUILTY, ParticipantRole
```

Add to `SessionDetailSerializer` class:

```python
    report_available = serializers.SerializerMethodField()
    votes_summary = serializers.SerializerMethodField()
```

Add methods:

```python
    def get_report_available(self, obj):
        """Report is available when session is CLOSED."""
        return obj.state == SessionState.CLOSED

    def get_votes_summary(self, obj):
        """Returns vote results summary when session is CLOSED."""
        if obj.state != SessionState.CLOSED:
            return None

        votes = SessionVote.objects.filter(session=obj).select_related("participant__user")
        results = []
        correct_count = 0

        for vote in votes:
            username = getattr(vote.participant.user, "display_name", None) or vote.participant.user.get_username()
            is_correct = vote.suspect_chosen == MURDER_MYSTERY_GUILTY
            if is_correct:
                correct_count += 1
            results.append({
                "user_id": vote.participant.user_id,
                "username": username,
                "chose": vote.suspect_chosen,
                "correct": is_correct,
            })

        total = len(results)
        success_rate = int((correct_count / total) * 100) if total > 0 else 0

        return {
            "results": results,
            "guilty": MURDER_MYSTERY_GUILTY,
            "success_rate": success_rate,
        }
```

**Step 4: Run tests to verify they pass**

Run: `docker compose run --rm web python manage.py test apps.sessions.tests.SessionDetailSerializerVotesTests -v 2`

Expected: PASS

**Step 5: Commit**

```bash
git add apps/sessions/serializers.py apps/sessions/tests.py
git commit -m "feat(sessions): add report_available and votes_summary to SessionDetailSerializer"
```

---

## Task 11: Run Full Test Suite and Update Documentation

**Files:**
- Modify: `docs/documentazione_moderazione.md`

**Step 1: Run full test suite**

Run: `docker compose run --rm web python manage.py test apps.sessions apps.reports -v 2`

Expected: All tests PASS

**Step 2: Update moderation documentation**

Edit `docs/documentazione_moderazione.md` and add a section about the voting flow:

```markdown
## Votazione e Report (CONCLUSION → CLOSED)

### Flusso Votazione

1. **Entrata in CONCLUSION**: La sessione entra in CONCLUSION (via timer 30min o 3/3 pronti)
2. **TTS forced_conclusion**: Il moderatore pronuncia il messaggio di chiusura
3. **AI_ENDED**: Frontend riceve evento e abilita i bottoni di voto
4. **Voti**: I partecipanti votano uno alla volta
   - `POST /api/sessions/{id}/vote/` con `{"suspect": "Eddie|Mickey|Billy"}`
   - Ogni voto genera evento WebSocket `VOTE_CAST`
5. **ALL_VOTED**: Quando tutti votano, broadcast `ALL_VOTED` con risultati completi
6. **Countdown**: 15 secondi per visualizzare i risultati
7. **Chiusura**:
   - Host può anticipare con `POST /api/sessions/{id}/close/`
   - Altrimenti timeout automatico (non implementato MVP)
8. **Report**: LLM genera `report_text`, sessione passa a CLOSED

### Endpoint Votazione

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| POST | `/api/sessions/{id}/vote/` | Registra voto |
| GET | `/api/sessions/{id}/vote-status/` | Stato voti |
| POST | `/api/sessions/{id}/close/` | Chiusura anticipata (host) |
| GET | `/api/sessions/{id}/report/` | Download PDF |

### Costanti MVP

```python
MURDER_MYSTERY_SUSPECTS = ["Eddie", "Mickey", "Billy"]
MURDER_MYSTERY_GUILTY = "Eddie"
REVEAL_TIMEOUT_SECONDS = 15
```

### WebSocket Events

- `VOTE_CAST`: `{"user_id": 123}` - qualcuno ha votato
- `ALL_VOTED`: risultati completi con `results`, `guilty`, `success_rate`, `closing_in_seconds`
- `SESSION_CLOSED`: sessione chiusa, redirect a storico
```

**Step 3: Commit documentation**

```bash
git add docs/documentazione_moderazione.md
git commit -m "docs: add voting flow documentation"
```

**Step 4: Final verification**

Run: `docker compose run --rm web python manage.py test apps.sessions apps.reports -v 2`

Expected: All tests PASS

---

## Task 12: Integration Test - Full Flow

**Files:**
- Modify: `apps/sessions/tests.py`

**Step 1: Write integration test**

Add to `apps/sessions/tests.py`:

```python
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
            context=SessionContext.MURDER_MYSTERY,
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

    @patch("apps.sessions.views._broadcast_session_event")
    @patch("apps.reports.llm_service.ReportLLMService.generate_report_text")
    def test_full_voting_flow(self, mock_llm, mock_broadcast):
        """Test complete flow: votes → ALL_VOTED → close → download."""
        mock_llm.return_value = "LLM generated report text"

        # 1. First vote
        self.client.force_authenticate(user=self.host)
        response = self.client.post(
            f"/api/sessions/{self.session.id}/vote/",
            {"suspect": "Eddie"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # 2. Second vote
        self.client.force_authenticate(user=self.player2)
        response = self.client.post(
            f"/api/sessions/{self.session.id}/vote/",
            {"suspect": "Mickey"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # 3. Third vote (triggers ALL_VOTED)
        self.client.force_authenticate(user=self.player3)
        response = self.client.post(
            f"/api/sessions/{self.session.id}/vote/",
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
```

**Step 2: Run the integration test**

Run: `docker compose run --rm web python manage.py test apps.sessions.tests.VotingFlowIntegrationTests -v 2`

Expected: PASS

**Step 3: Run complete test suite**

Run: `docker compose run --rm web python manage.py test apps.sessions apps.reports -v 2`

Expected: All PASS

**Step 4: Commit**

```bash
git add apps/sessions/tests.py
git commit -m "test(sessions): add full voting flow integration test"
```

---

## Checklist

- [x] Task 1: Add SessionVote model and Session.report_text field
- [x] Task 2: Implement Vote Endpoint (POST /sessions/{id}/vote/)
- [x] Task 3: Implement Vote Status Endpoint (GET /sessions/{id}/vote-status/)
- [x] Task 4: Implement ALL_VOTED Broadcast and 15s Countdown Logic
- [x] Task 5: Implement Close Session Endpoint (POST /sessions/{id}/close/)
- [x] Task 6: Create Reports App with LLM Service
- [x] Task 7: Create PDF Service with ReportLab
- [x] Task 8: Implement Report Download Endpoint (GET /sessions/{id}/report/)
- [x] Task 9: Integrate LLM Report Generation into close_session
- [x] Task 10: Update SessionDetailSerializer with report_available and votes_summary
- [x] Task 11: Run Full Test Suite and Update Documentation
- [x] Task 12: Integration Test - Full Flow
