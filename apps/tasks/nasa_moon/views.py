"""
Viste API per NASA Moon Survival: ranking di gruppo e stato submission.
"""

from django.shortcuts import get_object_or_404

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.sessions.models import (
    Session,
    SessionParticipant,
    SessionState,
    ParticipantRole,
)
from apps.sessions.views import _broadcast_session_event
from apps.sessions.permissions import IsSessionMember

from .config import NASA_ITEMS
from .models import NasaRanking


class NasaRankingView(APIView):
    """
    PUT  /api/tasks/nasa-moon/sessions/{session_id}/ranking/
        Crea o aggiorna il ranking di gruppo (solo host, solo in ACTIVE).

    GET  /api/tasks/nasa-moon/sessions/{session_id}/ranking/
        Ritorna il ranking corrente (qualsiasi membro della sessione).
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, session_id: str):
        session = get_object_or_404(Session, pk=session_id)

        # Verifica membership
        if not SessionParticipant.objects.filter(
            session=session, user=request.user
        ).exists():
            return Response(
                {"detail": "Non sei un partecipante di questa sessione."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            ranking = NasaRanking.objects.get(session=session)
            return Response({
                "ranked_items": ranking.ranked_items,
                "updated_at": ranking.updated_at.isoformat(),
            })
        except NasaRanking.DoesNotExist:
            return Response({
                "ranked_items": None,
                "updated_at": None,
            })

    def put(self, request, session_id: str):
        session = get_object_or_404(Session, pk=session_id)

        if session.state != SessionState.ACTIVE:
            return Response(
                {"detail": "Il ranking puo essere modificato solo durante la discussione."},
                status=status.HTTP_409_CONFLICT,
            )

        # Solo l'host puo modificare il ranking
        try:
            participant = SessionParticipant.objects.get(
                session=session, user=request.user
            )
        except SessionParticipant.DoesNotExist:
            return Response(
                {"detail": "Non sei un partecipante di questa sessione."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if participant.role != ParticipantRole.HOST:
            return Response(
                {"detail": "Solo l'host puo modificare il ranking di gruppo."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Validazione ranking
        ranked_items = request.data.get("ranked_items")
        if not isinstance(ranked_items, list):
            return Response(
                {"detail": "ranked_items deve essere una lista."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(ranked_items) != len(NASA_ITEMS):
            return Response(
                {"detail": f"Il ranking deve contenere esattamente {len(NASA_ITEMS)} oggetti."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if set(ranked_items) != set(NASA_ITEMS):
            invalid = set(ranked_items) - set(NASA_ITEMS)
            missing = set(NASA_ITEMS) - set(ranked_items)
            detail = "Il ranking contiene oggetti non validi."
            if invalid:
                detail += f" Non riconosciuti: {sorted(invalid)}."
            if missing:
                detail += f" Mancanti: {sorted(missing)}."
            return Response(
                {"detail": detail},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(set(ranked_items)) != len(ranked_items):
            return Response(
                {"detail": "Il ranking contiene oggetti duplicati."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Upsert
        ranking, created = NasaRanking.objects.update_or_create(
            session=session,
            defaults={
                "submitted_by": participant,
                "ranked_items": ranked_items,
            },
        )

        # Broadcast a tutti i partecipanti
        _broadcast_session_event(
            session_id=str(session.id),
            event_type="RANKING_UPDATED",
            payload={
                "ranked_items": ranked_items,
                "updated_by": request.user.id,
            },
        )

        return Response(
            {
                "success": True,
                "ranked_items": ranking.ranked_items,
                "updated_at": ranking.updated_at.isoformat(),
            },
            status=status.HTTP_200_OK if not created else status.HTTP_201_CREATED,
        )


class NasaRankingStatusView(APIView):
    """
    GET /api/tasks/nasa-moon/sessions/{session_id}/ranking-status/
    Ritorna lo stato del ranking di gruppo.
    """

    permission_classes = [permissions.IsAuthenticated, IsSessionMember]

    def get(self, request, session_id: str):
        session = get_object_or_404(Session, pk=session_id)
        self.check_object_permissions(request, session)

        has_ranking = NasaRanking.objects.filter(session=session).exists()

        return Response({
            "has_ranking": has_ranking,
            "session_state": session.state,
        })
