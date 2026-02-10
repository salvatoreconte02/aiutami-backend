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

from .models import Session, SessionParticipant, SessionState, SessionVote, MURDER_MYSTERY_SUSPECTS, MURDER_MYSTERY_GUILTY
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
            user_name = getattr(request.user, "display_name", None) or request.user.get_username()
            result = generate_ready_to_conclude_message(user_name, ready_count, total_count)
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


class SessionVoteView(APIView):
    """
    POST /api/sessions/{session_id}/vote/
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
    GET /api/sessions/{session_id}/vote-status/
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

        total_participants = SessionParticipant.objects.filter(session=session).count()
        votes_cast = SessionVote.objects.filter(session=session).count()

        if votes_cast < total_participants:
            return Response(
                {"detail": "Non tutti i partecipanti hanno ancora votato."},
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