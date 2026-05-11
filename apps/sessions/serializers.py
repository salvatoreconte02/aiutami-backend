from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Optional

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.tasks.registry import get_task, TaskNotFound

from .models import (
    Invitation,
    ParticipantRole,
    Session,
    SessionEvent,
    SessionEventType,
    SessionState,
    SessionParticipant,
)


def _build_invite_url(request, token: str) -> str:
    """Costruisce URL di invito con token."""
    if not token:
        return ""
    base = request.build_absolute_uri("/")[:-1] if request else ""
    return f"{base}?invite={token}" if base else f"?invite={token}"




class SessionCreateSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    state = serializers.CharField(read_only=True)
    participants_count = serializers.IntegerField(read_only=True)
    host = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Session
        fields = (
            "id",
            "title",
            "context",
            "state",
            "min_size",
            "max_size",
            "host",
            "participants_count",
            "moderator_enabled",
        )
        extra_kwargs = {
            "min_size": {"required": False},
            "max_size": {"required": False},
            "moderator_enabled": {"required": False},
        }

    def get_host(self, obj: Session):
        return {"id": obj.host_id}

    def validate(self, attrs):
        user = self.context["request"].user

        # L'utente non può creare una sessione se è già membro
        # di una sessione non-chiusa (LOBBY / INDIVIDUAL_RANKING / ACTIVE / CONCLUSION).
        active_states = {
            SessionState.LOBBY,
            SessionState.INDIVIDUAL_RANKING,
            SessionState.ACTIVE,
            SessionState.CONCLUSION,
        }

        already_in_active = (
            Session.objects.filter(
                participants__user=user,
                state__in=active_states,
            ).exists()
        )

        if already_in_active:
            raise serializers.ValidationError(
                "Non puoi creare una nuova sessione mentre partecipi ad una sessione già attiva."
            )

        context = attrs.get("context")

        # Validazione contro il registry dei task plugin.
        try:
            task = get_task(context)
        except TaskNotFound:
            raise serializers.ValidationError(
                {"context": f"Task '{context}' non registrato."}
            )

        if task.fixed_size:
            # Task a capienza fissa (es. Murder Mystery): forziamo i valori
            # corretti anche se il client non li ha passati.
            attrs["min_size"] = task.min_participants
            attrs["max_size"] = task.max_participants
        else:
            # Task con range variabile: min/max obbligatori.
            if "min_size" not in attrs or "max_size" not in attrs:
                raise serializers.ValidationError(
                    "Per questo task sono richiesti min_size e max_size."
                )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        user = self.context["request"].user
        session = Session(host=user, **validated_data)
        try:
            session.full_clean()
        except Exception as e:
            from django.core.exceptions import ValidationError as DjangoVE

            if isinstance(e, DjangoVE):
                raise serializers.ValidationError(
                    getattr(e, "message_dict", None)
                    or getattr(e, "messages", None)
                    or str(e)
                )
            raise
        session.save()
        SessionParticipant.objects.create(
            session=session, user=user, role=ParticipantRole.HOST
        )
        SessionEvent.objects.create(
            session=session,
            type=SessionEventType.CREATED,
            actor=user,
            payload={
                "context": session.context,
                "min_size": session.min_size,
                "max_size": session.max_size,
            },
        )
        return session


class SessionDetailSerializer(serializers.ModelSerializer):
    participants_count = serializers.IntegerField(read_only=True)
    me = serializers.SerializerMethodField()
    host = serializers.SerializerMethodField()
    invite_url = serializers.SerializerMethodField()
    report_available = serializers.SerializerMethodField()
    votes_summary = serializers.SerializerMethodField()

    class Meta:
        model = Session
        fields = (
            "id",
            "title",
            "context",
            "state",
            "min_size",
            "max_size",
            "host",
            "participants_count",
            "me",
            "invite_url",
            "created_at",
            "started_at",
            "conclusion_at",
            "ended_at",
            "report_available",
            "votes_summary",
            "moderator_enabled",
        )
        read_only_fields = fields

    def get_host(self, obj: Session) -> Dict[str, Any]:
        return {"id": obj.host_id}

    def get_me(self, obj: Session) -> Optional[Dict[str, Any]]:
        request = self.context.get("request")
        user = request.user if request else None
        if not user:
            return None
        sp = obj.participants.filter(user_id=user.id).only("role").first()
        if not sp:
            return None
        return {"role": sp.role}

    def get_invite_url(self, obj: Session) -> str:
        """
        Espone il link d'invito al chiamante se e solo se è membro (HOST o PARTICIPANT).
        Se non esistono inviti, ritorna stringa vuota.
        """
        request = self.context.get("request")
        user = request.user if request else None
        if not user:
            return ""
        is_member = obj.participants.filter(user_id=user.id).exists()
        if not is_member:
            return ""
        inv = obj.invitations.order_by("-created_at").only("token").first()
        return _build_invite_url(request, inv.token) if inv else ""

    def get_report_available(self, obj: Session) -> bool:
        return obj.state == SessionState.CLOSED

    def get_votes_summary(self, obj: Session) -> Optional[Dict[str, Any]]:
        if obj.state != SessionState.CLOSED:
            return None
        task = get_task(obj.context)
        return task.submission_summary(obj)


# Session transitions
class SessionStartSerializer(serializers.Serializer):
    """LOBBY -> ACTIVE"""

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        session: Session = self.instance
        user = self.context["request"].user
        if session.host_id != user.id:
            raise serializers.ValidationError("Solo l'host può avviare la sessione.")
        if session.state != SessionState.LOBBY:
            raise serializers.ValidationError("La sessione non è in stato LOBBY.")
        # Minimo partecipanti raggiunto
        if session.participants_count < session.min_size:
            raise serializers.ValidationError("Numero minimo di partecipanti non raggiunto.")
        return attrs

    @transaction.atomic
    def save(self, **kwargs: Any) -> Session:
        session: Session = self.instance
        session.start()
        session.full_clean()

        if session.state == SessionState.INDIVIDUAL_RANKING:
            session.save(update_fields=["state", "individual_ranking_started_at"])
            task = get_task(session.context)
            deadline = session.individual_ranking_started_at + timedelta(
                seconds=task.individual_ranking_duration_seconds()
            )
            SessionEvent.objects.create(
                session=session,
                type=SessionEventType.STARTED,
                actor=self.context["request"].user,
                payload={
                    "phase": "INDIVIDUAL_RANKING",
                    "individual_ranking_started_at": session.individual_ranking_started_at.isoformat(),
                    "phase_deadline_at": deadline.isoformat(),
                },
            )
        else:
            session.save(update_fields=["state", "started_at"])
            SessionEvent.objects.create(
                session=session,
                type=SessionEventType.STARTED,
                actor=self.context["request"].user,
                payload={"started_at": timezone.now().isoformat()},
            )
        return session


# Invitation: create link
class InvitationCreateSerializer(serializers.Serializer):
    """Genera un token invito riutilizzabile."""

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        session: Session = self.instance
        user = self.context["request"].user
        if session.host_id != user.id:
            raise serializers.ValidationError("Solo l'host può creare inviti.")
        if session.state != SessionState.LOBBY:
            raise serializers.ValidationError("Inviti disponibili solo in LOBBY.")
        return attrs

    @transaction.atomic
    def save(self, **kwargs: Any) -> Dict[str, Any]:
        session: Session = self.instance
        inv = Invitation.objects.create(session=session)
        request = self.context.get("request")
        url = _build_invite_url(request, inv.token)
        SessionEvent.objects.create(
            session=session,
            type=SessionEventType.INVITE_CREATED,
            actor=self.context["request"].user,
            payload={"token": inv.token},
        )
        return {"token": inv.token, "url": url}


# Join via token
class JoinByTokenSerializer(serializers.Serializer):
    token = serializers.CharField()

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        token = attrs.get("token")
        try:
            invitation = Invitation.objects.select_related("session").get(token=token)
        except Invitation.DoesNotExist:
            raise serializers.ValidationError("Token invito non valido.")

        session = invitation.session
        user = self.context["request"].user

        # 0) Caso rejoin: l'utente è già SessionParticipant di QUESTA sessione.
        # Permettiamo il rientro idempotente in qualunque stato non terminale
        # (INDIVIDUAL_RANKING, ACTIVE, CONCLUSION) — uso reale: l'app del
        # partecipante crasha o il telefono cambia rete e lui riapre il link
        # di invito dal Whatsapp. Senza questo bypass, il check sotto "stato
        # non LOBBY" blocca il rientro e l'utente resta fuori per il resto
        # della sessione.
        existing = SessionParticipant.objects.filter(
            session=session, user=user
        ).first()
        if existing is not None:
            if session.state == SessionState.CLOSED:
                raise serializers.ValidationError("La sessione è chiusa.")
            self._session = session
            self._invitation = invitation
            self._existing_participant = existing
            return attrs

        # 1) La sessione target deve essere LOBBY (solo per nuovi utenti)
        if session.state != SessionState.LOBBY:
            raise serializers.ValidationError("La sessione non è in stato LOBBY.")

        # 2) l'utente non può essere in un'altra sessione non chiusa
        # (LOBBY, INDIVIDUAL_RANKING, ACTIVE, CONCLUSION). Il caso rejoin
        # sulla stessa sessione è già stato gestito sopra.
        if SessionParticipant.objects.filter(
            user=user,
            session__state__in=[
                SessionState.LOBBY,
                SessionState.INDIVIDUAL_RANKING,
                SessionState.ACTIVE,
                SessionState.CONCLUSION,
            ],
        ).exists():
            raise serializers.ValidationError(
                "L'utente è già impegnato in un'altra sessione non chiusa."
            )

        # 3) Capienza della lobby
        if session.participants_count >= session.max_size:
            raise serializers.ValidationError("Sessione piena.")

        self._session = session
        self._invitation = invitation
        return attrs

    @transaction.atomic
    def create(self, validated_data: Dict[str, Any]) -> SessionParticipant:
        # Rejoin idempotente: utente già SessionParticipant — riusa l'oggetto
        # senza creare nuovi record né emettere un nuovo JOINED event.
        existing = getattr(self, "_existing_participant", None)
        if existing is not None:
            return existing

        session: Session = self._session
        user = self.context["request"].user
        sp = SessionParticipant.objects.create(
            session=session, user=user, role=ParticipantRole.PARTICIPANT
        )
        SessionEvent.objects.create(
            session=session,
            type=SessionEventType.JOINED,
            actor=user,
            payload={"participants_count": session.participants_count},
        )
        return sp

    def to_representation(self, instance: SessionParticipant) -> Dict[str, Any]:
        session = instance.session
        return {
            "session": {
                "id": str(session.id),
                "title": session.title,
                "state": session.state,
                "min_size": session.min_size,
                "max_size": session.max_size,
                "participants_count": session.participants_count,
            },
            "me": {"role": instance.role},
        }


# Read-only lists
class ParticipantItemSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()

    class Meta:
        model = SessionParticipant
        fields = ("user", "role", "joined_at", "ready_to_conclude")
        read_only_fields = fields

    def get_user(self, obj: SessionParticipant) -> Dict[str, Any]:
        u = obj.user
        return {
            "id": u.id,
            "username": u.username,
            "first_name": u.first_name,
            "last_name": u.last_name,
        }


class ParticipantsListSerializer(serializers.ListSerializer):
    child = ParticipantItemSerializer()


class MySessionsListSerializer(serializers.ModelSerializer):
    participants_count = serializers.IntegerField(read_only=True)
    role = serializers.SerializerMethodField()
    invite_url = serializers.SerializerMethodField()

    class Meta:
        model = Session
        fields = (
            "id",
            "title",
            "state",
            "min_size",
            "max_size",
            "participants_count",
            "role",
            "invite_url",
            "created_at",
            "started_at",
        )
        read_only_fields = fields

    def get_role(self, obj: Session) -> Optional[str]:
        user = self.context["request"].user
        sp = obj.participants.only("role").filter(user_id=user.id).first()
        return sp.role if sp else None

    def get_invite_url(self, obj: Session) -> str:
        """
        In “Le mie sessioni”, il chiamante è per definizione membro.
        Se esiste un invito, esporre il link; altrimenti stringa vuota.
        """
        request = self.context.get("request")
        inv = obj.invitations.order_by("-created_at").only("token").first()
        return _build_invite_url(request, inv.token) if inv else ""