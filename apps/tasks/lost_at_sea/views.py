"""
Viste API per Lost at Sea: ranking di gruppo e stato submission.
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

from .config import LOST_AT_SEA_ITEMS
from .models import LostAtSeaRanking


class LostAtSeaRankingView(APIView):
    """
    PUT  /api/tasks/lost-at-sea/sessions/{session_id}/ranking/
        Crea o aggiorna il ranking di gruppo (solo host, ACTIVE o CONCLUSION).

    GET  /api/tasks/lost-at-sea/sessions/{session_id}/ranking/
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
            ranking = LostAtSeaRanking.objects.get(session=session)
            return Response({
                "ranked_items": ranking.ranked_items,
                "is_final": ranking.is_final,
                "updated_at": ranking.updated_at.isoformat(),
            })
        except LostAtSeaRanking.DoesNotExist:
            return Response({
                "ranked_items": None,
                "is_final": False,
                "updated_at": None,
            })

    def put(self, request, session_id: str):
        session = get_object_or_404(Session, pk=session_id)

        if session.state not in (SessionState.ACTIVE, SessionState.CONCLUSION):
            return Response(
                {"detail": "Il ranking puo essere modificato solo durante ACTIVE o CONCLUSION."},
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

        if len(ranked_items) != len(LOST_AT_SEA_ITEMS):
            return Response(
                {"detail": f"Il ranking deve contenere esattamente {len(LOST_AT_SEA_ITEMS)} oggetti."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if set(ranked_items) != set(LOST_AT_SEA_ITEMS):
            invalid = set(ranked_items) - set(LOST_AT_SEA_ITEMS)
            missing = set(LOST_AT_SEA_ITEMS) - set(ranked_items)
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
        ranking, created = LostAtSeaRanking.objects.update_or_create(
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


class LostAtSeaRankingStatusView(APIView):
    """
    GET /api/tasks/lost-at-sea/sessions/{session_id}/ranking-status/
    Ritorna lo stato del ranking di gruppo.
    """

    permission_classes = [permissions.IsAuthenticated, IsSessionMember]

    def get(self, request, session_id: str):
        session = get_object_or_404(Session, pk=session_id)
        self.check_object_permissions(request, session)

        try:
            ranking = LostAtSeaRanking.objects.get(session=session)
            has_ranking = True
            is_final = ranking.is_final
        except LostAtSeaRanking.DoesNotExist:
            has_ranking = False
            is_final = False

        return Response({
            "has_ranking": has_ranking,
            "is_final": is_final,
            "session_state": session.state,
        })


class LostAtSeaRankingSubmitView(APIView):
    """
    POST /api/tasks/lost-at-sea/sessions/{session_id}/ranking/submit/
    Conferma il ranking come definitivo (solo host, solo in CONCLUSION).
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, session_id: str):
        session = get_object_or_404(Session, pk=session_id)

        if session.state != SessionState.CONCLUSION:
            return Response(
                {"detail": "Il ranking puo essere confermato solo in fase CONCLUSION."},
                status=status.HTTP_409_CONFLICT,
            )

        # Solo l'host
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
                {"detail": "Solo l'host puo confermare il ranking di gruppo."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Il ranking deve esistere
        try:
            ranking = LostAtSeaRanking.objects.get(session=session)
        except LostAtSeaRanking.DoesNotExist:
            return Response(
                {"detail": "Nessun ranking da confermare. Componi prima il ranking."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if ranking.is_final:
            return Response(
                {"detail": "Il ranking e gia stato confermato."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ranking.is_final = True
        ranking.save(update_fields=["is_final"])

        _broadcast_session_event(
            session_id=str(session.id),
            event_type="RANKING_SUBMITTED",
            payload={
                "ranked_items": ranking.ranked_items,
                "submitted_by": request.user.id,
            },
        )

        return Response({
            "success": True,
            "ranked_items": ranking.ranked_items,
            "is_final": True,
        })
