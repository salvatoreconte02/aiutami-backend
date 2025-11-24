from __future__ import annotations

from typing import Optional

from django.shortcuts import get_object_or_404
from django.db.models import Q
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.conf import settings
from django.utils import timezone

from .models import Session, SessionParticipant, SessionState
from .serializers import (
    InvitationCreateSerializer,
    JoinByTokenSerializer,
    MySessionsListSerializer,
    ParticipantItemSerializer,
    ParticipantsListSerializer,
    SessionCreateSerializer,
    SessionDetailSerializer,
    SessionStartSerializer,
)
from .permissions import IsSessionMember


# ---------------------------
#  Sessions: create & detail
# ---------------------------

class SessionCreateView(generics.CreateAPIView):
    """
    POST /api/sessions/
    Crea una sessione direttamente in LOBBY; il chiamante diventa HOST.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SessionCreateSerializer


class SessionDetailView(generics.RetrieveAPIView):
    """
    GET /api/sessions/{session_id}/
    Dettaglio sessione visibile ai soli membri.
    """
    permission_classes = [permissions.IsAuthenticated, IsSessionMember]
    serializer_class = SessionDetailSerializer
    lookup_url_kwarg = "session_id"

    def get_queryset(self):
        # Limita il retrieve alle sessioni di cui l’utente è membro
        user = self.request.user
        return Session.objects.filter(participants__user=user).distinct()


# ---------------------------
#  Sessions: transitions
# ---------------------------

class SessionStartView(APIView):
    """
    POST /api/sessions/{session_id}/start/
    Transizione LOBBY -> ACTIVE (solo host; capienza raggiunta).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, session_id: str):
        session = get_object_or_404(Session, pk=session_id)
        serializer = SessionStartSerializer(
            instance=session,
            data={},
            context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        session = serializer.save()
        return Response(
            {
                "id": str(session.id),
                "state": session.state,
                "started_at": session.started_at,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------
#  Invitations
# ---------------------------

class InvitationCreateView(APIView):
    """
    POST /api/sessions/{session_id}/invitations/
    Crea un invito (token) riutilizzabile. Solo in LOBBY.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, session_id: str):
        session = get_object_or_404(Session, pk=session_id)
        serializer = InvitationCreateSerializer(
            instance=session,
            data={},
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.save()
        return Response(data, status=status.HTTP_200_OK)


class JoinByTokenView(generics.CreateAPIView):
    """
    POST /api/sessions/join_by_token/
    Entra in una sessione in LOBBY tramite token.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = JoinByTokenSerializer


# ---------------------------
#  Participants (read-only)
# ---------------------------

class ParticipantsListView(generics.ListAPIView):
    """
    GET /api/sessions/{session_id}/participants/
    Elenco dei partecipanti (solo membri).
    """
    permission_classes = [permissions.IsAuthenticated, IsSessionMember]
    serializer_class = ParticipantItemSerializer
    lookup_url_kwarg = "session_id"
    pagination_class = None

    def get_queryset(self):
        session = get_object_or_404(Session, pk=self.kwargs[self.lookup_url_kwarg])
        # object-level permission
        self.check_object_permissions(self.request, session)
        return (
            SessionParticipant.objects
            .filter(session=session)
            .select_related("user")
            .order_by("joined_at")
        )


# ---------------------------
#  My sessions (read-only)
# ---------------------------

class MySessionsListView(generics.ListAPIView):
    """
    GET /api/sessions/mine/?state=...
    Sessioni in cui l’utente è host o participant; filtro per stato opzionale.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = MySessionsListSerializer
    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        qs = Session.objects.filter(participants__user=user).distinct()

        state = self.request.query_params.get("state")
        if state:
            valid_states = {s for s, _ in SessionState.choices}
            if state in valid_states:
                qs = qs.filter(state=state)

        return qs.order_by("-created_at")

class SessionDebugForceCloseView(APIView):
    """
    Endpoint di debug (solo in DEBUG) per forzare una sessione in stato CLOSED.
    Serve solo per sviluppo/test frontend.

    POST /api/sessions/{id}/debug_force_close/
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, id):
        # Se non siamo in DEBUG, non esporre l'endpoint
        if not settings.DEBUG:
            return Response({"detail": "Not found."}, status=404)

        session = get_object_or_404(Session, id=id)

        # Opzionale ma consigliato: solo l'host può chiudere la propria sessione
        if session.host_id != request.user.id:
            return Response(
                {
                    "detail": "Solo l'host può forzare la chiusura in ambiente di sviluppo."
                },
                status=403,
            )

        # Se è già CLOSED non fa danni, ma si può evitare di riscrivere
        if session.state != SessionState.CLOSED:
            session.state = SessionState.CLOSED
            session.ended_at = timezone.now()
            session.save(update_fields=["state", "ended_at"])

        data = SessionDetailSerializer(session, context={"request": request}).data
        return Response(data)