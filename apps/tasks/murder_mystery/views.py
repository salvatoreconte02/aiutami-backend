"""
Viste API per Murder Mystery: voto colpevole e stato votazione.

Step 6 del refactor task-pluggable: spostate da apps/sessions/views.py.
"""

from django.shortcuts import get_object_or_404

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.sessions.models import Session, SessionParticipant, SessionState
from apps.sessions.views import _broadcast_session_event
from apps.sessions.permissions import IsSessionMember

from .models import SessionVote, MURDER_MYSTERY_SUSPECTS, MURDER_MYSTERY_GUILTY


class SessionVoteView(APIView):
    """
    POST /api/tasks/murder-mystery/sessions/{session_id}/vote/
    Registra il voto del partecipante per il colpevole (Murder Mystery).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, session_id: str):
        session = get_object_or_404(Session, pk=session_id)

        if session.state != SessionState.CONCLUSION:
            return Response(
                {"detail": "La sessione non è in fase di votazione."},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            participant = SessionParticipant.objects.get(
                session=session, user=request.user
            )
        except SessionParticipant.DoesNotExist:
            return Response(
                {"detail": "Non sei un partecipante di questa sessione."},
                status=status.HTTP_403_FORBIDDEN,
            )

        suspect = request.data.get("suspect")
        if suspect not in MURDER_MYSTERY_SUSPECTS:
            return Response(
                {"detail": f"Sospetto non valido. Scegli tra: {', '.join(MURDER_MYSTERY_SUSPECTS)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if SessionVote.objects.filter(session=session, participant=participant).exists():
            return Response(
                {"detail": "Hai già votato."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        SessionVote.objects.create(
            session=session,
            participant=participant,
            suspect_chosen=suspect,
        )

        total_participants = SessionParticipant.objects.filter(session=session).count()
        votes_cast = SessionVote.objects.filter(session=session).count()

        _broadcast_session_event(
            session_id=str(session.id),
            event_type="VOTE_CAST",
            payload={"user_id": request.user.id},
        )

        if votes_cast == total_participants:
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

        return Response(
            {
                "success": True,
                "votes_cast": votes_cast,
                "total_participants": total_participants,
            },
            status=status.HTTP_201_CREATED,
        )


class SessionVoteStatusView(APIView):
    """
    GET /api/tasks/murder-mystery/sessions/{session_id}/vote-status/
    Ritorna lo stato attuale della votazione.
    """
    permission_classes = [permissions.IsAuthenticated, IsSessionMember]

    def get(self, request, session_id: str):
        session = get_object_or_404(Session, pk=session_id)
        self.check_object_permissions(request, session)

        total_participants = SessionParticipant.objects.filter(session=session).count()
        votes_cast = SessionVote.objects.filter(session=session).count()

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
