from __future__ import annotations

from typing import Optional

from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.conf import settings
from django.utils import timezone

from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

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

# 🔹 import per i timer di moderazione
from apps.moderation.timers_state import mark_session_started


# -------------------------------------------------------------------
#  Helper per broadcast WebSocket delle sessioni
# -------------------------------------------------------------------

def _broadcast_session_event(session_id: str, event_type: str, payload: dict) -> None:
    """
    Invia un evento di sessione in broadcast al gruppo WebSocket
    'sessions_<session_id>'.

    L'handler in SessionsConsumer si aspetta:
      - type: "session.event"
      - event_type: stringa logica (es. "STATE_CHANGED")
      - payload: dizionario serializzabile in JSON
    """
    channel_layer = get_channel_layer()
    if not channel_layer:
        return

    async_to_sync(channel_layer.group_send)(
        f"sessions_{session_id}",
        {
            "type": "sessions.event",   # deve corrispondere al metodo session_event del consumer
            "event_type": event_type,
            "payload": payload,
        },
    )


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
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        session = serializer.save()

        # 🔹 La sessione è appena entrata in ACTIVE:
        #    si inizializzano i timer di moderazione (NO PUSH, TIMER 25'/30').
        mark_session_started(session_id=session.id)

        # Payload completo della sessione dopo la transizione
        detail_data = SessionDetailSerializer(
            session,
            context={"request": request},
        ).data

        # Broadcast WS: la sessione ha cambiato stato (es. LOBBY -> ACTIVE)
        _broadcast_session_event(
            session_id=str(session.id),
            event_type="STATE_CHANGED",
            payload=detail_data,
        )

        return Response(detail_data, status=status.HTTP_200_OK)


class SessionReadyToConcludeView(APIView):
    """
    POST /api/sessions/{session_id}/ready_to_conclude/
    Permette al partecipante corrente di indicare se è pronto (o meno) alla conclusione.

    Body esemplificativo:
    {
        "ready": true
    }
    """
    permission_classes = [permissions.IsAuthenticated, IsSessionMember]

    def post(self, request, session_id: str):
        # Recupera la sessione e verifica che l'utente sia membro
        session = get_object_or_404(Session, pk=session_id)
        self.check_object_permissions(request, session)

        # Lettura del flag "ready" dal body; default True se non specificato
        ready = request.data.get("ready", True)
        ready = bool(ready)

        # Aggiorna il record SessionParticipant dell'utente corrente
        participant = get_object_or_404(
            SessionParticipant,
            session=session,
            user=request.user,
        )
        if participant.ready_to_conclude != ready:
            participant.ready_to_conclude = ready
            participant.save(update_fields=["ready_to_conclude"])

        # Ricalcolo dei conteggi "pronti / totali"
        qs = SessionParticipant.objects.filter(session=session)
        total_count = qs.count()
        ready_count = qs.filter(ready_to_conclude=True).count()

        # Se tutti sono pronti e la sessione è ancora ACTIVE,
        # si porta lo stato in CONCLUSION.
        if (
            session.state == SessionState.ACTIVE
            and total_count > 0
            and ready_count == total_count
        ):
            session.state = SessionState.CONCLUSION
            session.conclusion_at = timezone.now()
            session.save(update_fields=["state", "conclusion_at"])

        # Serializza lo stato aggiornato della sessione
        detail_data = SessionDetailSerializer(
            session,
            context={"request": request},
        ).data

        # Broadcast WS: la sessione (o il conteggio "pronti") è cambiato
        _broadcast_session_event(
            session_id=str(session.id),
            event_type="STATE_CHANGED",
            payload=detail_data,
        )

        return Response(detail_data, status=status.HTTP_200_OK)


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

    def perform_create(self, serializer):
        """
        Dopo aver aggiunto il partecipante alla sessione,
        invia in broadcast lo stato aggiornato della sessione
        a tutti i client WebSocket collegati a /ws/sessions/<session_id>/.
        """
        # Salvataggio effettivo (crea SessionParticipant o equivalente)
        instance = serializer.save()

        # La sessione è stata valorizzata nel serializer (es. in validate)
        session = serializer._session

        # Stato aggiornato (partecipants_count, ecc.)
        session.refresh_from_db()

        detail_data = SessionDetailSerializer(
            session,
            context={"request": self.request},
        ).data

        # Broadcast WS: stato sessione aggiornato (nuovo partecipante in lobby)
        _broadcast_session_event(
            session_id=str(session.id),
            event_type="STATE_CHANGED",
            payload=detail_data,
        )

        return instance


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

        # Solo l'host può chiudere la propria sessione (anche in debug)
        if session.host_id != request.user.id:
            return Response(
                {
                    "detail": "Solo l'host può forzare la chiusura in ambiente di sviluppo."
                },
                status=403,
            )

        # Aggiornamento stato -> CLOSED
        if session.state != SessionState.CLOSED:
            session.state = SessionState.CLOSED
            session.ended_at = timezone.now()
            session.save(update_fields=["state", "ended_at"])

        detail_data = SessionDetailSerializer(
            session,
            context={"request": request},
        ).data

        # Broadcast WS: la sessione è stata chiusa forzatamente (debug)
        _broadcast_session_event(
            session_id=str(session.id),
            event_type="STATE_CHANGED",
            payload=detail_data,
        )

        return Response(detail_data)