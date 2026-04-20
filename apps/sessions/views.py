from __future__ import annotations

from typing import Optional

from django.shortcuts import get_object_or_404
from django.conf import settings
from django.utils import timezone

from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import Session, SessionParticipant, SessionState
from .services import close_session
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

from apps.moderation.timers_state import mark_session_started
from apps.moderation.triggers import generate_ready_to_conclude_message
from apps.moderation.pending_messages import enqueue_message
from apps.turns.services import TurnManager
from apps.moderation.intro import set_intro_pending


# Helper per broadcast WebSocket delle sessioni
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


# Sessions: create & detail
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
        user = self.request.user
        return Session.objects.filter(participants__user=user).distinct()


# Sessions: transitions
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

        TurnManager.set_introducing(session_id=str(session.id))
        set_intro_pending(session_id=str(session.id))
        mark_session_started(session_id=session.id)

        detail_data = SessionDetailSerializer(
            session,
            context={"request": request},
        ).data

        _broadcast_session_event(
            session_id=str(session.id),
            event_type="STATE_CHANGED",
            payload=detail_data,
        )

        return Response(detail_data, status=status.HTTP_200_OK)


class SessionReadyToConcludeView(APIView):
    """
    POST /api/sessions/{session_id}/ready_to_conclude/
    Permette al partecipante corrente di indicare che è pronto alla conclusione.
    La deselezione (ready=False) non è permessa.

    Body esemplificativo:
    {
        "ready": true
    }
    """
    permission_classes = [permissions.IsAuthenticated, IsSessionMember]

    def post(self, request, session_id: str):
        session = get_object_or_404(Session, pk=session_id)
        self.check_object_permissions(request, session)

        ready = request.data.get("ready", True)
        ready = bool(ready)

        if not ready:
            return Response(
                {"error": "Non è possibile annullare la dichiarazione di essere pronti."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        participant = get_object_or_404(
            SessionParticipant,
            session=session,
            user=request.user,
        )

        if participant.ready_to_conclude:
            detail_data = SessionDetailSerializer(
                session,
                context={"request": request},
            ).data
            return Response(detail_data, status=status.HTTP_200_OK)

        participant.ready_to_conclude = True
        participant.save(update_fields=["ready_to_conclude"])

        qs = SessionParticipant.objects.filter(session=session)
        total_count = qs.count()
        ready_count = qs.filter(ready_to_conclude=True).count()

        # Messaggio accodato per evitare errori "No handler" su consumer WS
        if session.state == SessionState.ACTIVE:
            from apps.tasks.registry import get_task

            user_name = getattr(request.user, "display_name", None) or request.user.get_username()
            task = get_task(session.context)
            result = generate_ready_to_conclude_message(
                user_name,
                ready_count,
                total_count,
                task=task,
            )
            msg = result.message

            enqueue_message(
                session_id,
                msg.text,
                "READY_TO_CONCLUDE",
                trigger_conclusion=result.trigger_conclusion,
            )

        # Transizione a CONCLUSION avviene dopo TTS nel ws_consumer
        detail_data = SessionDetailSerializer(
            session,
            context={"request": request},
        ).data

        _broadcast_session_event(
            session_id=str(session.id),
            event_type="STATE_CHANGED",
            payload=detail_data,
        )

        return Response(detail_data, status=status.HTTP_200_OK)


# Invitations
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
        """Aggiunge partecipante e notifica via WebSocket."""
        instance = serializer.save()
        session = serializer._session
        session.refresh_from_db()

        detail_data = SessionDetailSerializer(
            session,
            context={"request": self.request},
        ).data

        _broadcast_session_event(
            session_id=str(session.id),
            event_type="STATE_CHANGED",
            payload=detail_data,
        )

        return instance


# Participants (read-only)
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
        self.check_object_permissions(self.request, session)
        return (
            SessionParticipant.objects
            .filter(session=session)
            .select_related("user")
            .order_by("joined_at")
        )


# My sessions (read-only)
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
        if not settings.DEBUG:
            return Response({"detail": "Not found."}, status=404)

        session = get_object_or_404(Session, id=id)

        if session.host_id != request.user.id:
            return Response(
                {
                    "detail": "Solo l'host può forzare la chiusura in ambiente di sviluppo."
                },
                status=403,
            )

        session = close_session(str(session.id))

        detail_data = SessionDetailSerializer(
            session,
            context={"request": request},
        ).data

        _broadcast_session_event(
            session_id=str(session.id),
            event_type="STATE_CHANGED",
            payload=detail_data,
        )

        return Response(detail_data)


class SessionCloseView(APIView):
    """
    POST /api/sessions/{session_id}/close/
    Chiude la sessione anticipatamente (solo host, solo dopo che tutti hanno votato).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, session_id: str):
        session = get_object_or_404(Session, pk=session_id)

        if session.host_id != request.user.id:
            return Response(
                {"detail": "Solo l'host può chiudere la sessione."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if session.state != SessionState.CONCLUSION:
            return Response(
                {"detail": "La sessione non è in fase di conclusione."},
                status=status.HTTP_409_CONFLICT,
            )

        from apps.tasks.registry import get_task
        task = get_task(session.context)
        if not task.all_submissions_received(session):
            return Response(
                {"detail": "Non tutti i partecipanti hanno completato la loro submission."},
                status=status.HTTP_409_CONFLICT,
            )

        session = close_session(str(session.id))

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