from __future__ import annotations

from typing import Any, Dict, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .models import (
    Invitation,
    ParticipantRole,
    Session,
    SessionContext,
    SessionEvent,
    SessionEventType,
    SessionState,
    SessionParticipant,
)


# -------------------------------------------------
# Helper per costruire l'URL di invito (?invite=...)
# -------------------------------------------------
def _build_invite_url(request, token: str) -> str:
    if not token:
        return ""
    base = request.build_absolute_uri("/")[:-1] if request else ""
    return f"{base}?invite={token}" if base else f"?invite={token}"


# -------------------------
#  Session: create & detail
# -------------------------

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
        )
        extra_kwargs = {
            "min_size": {"required": False},
            "max_size": {"required": False},
        }

    def get_host(self, obj: Session):
        return {"id": obj.host_id}

    def validate(self, attrs):
        context = attrs.get("context")
        # Caso Murder Mystery: forzare 3/3 anche se non passati
        if context == SessionContext.MURDER_MYSTERY:
            attrs["min_size"] = 3
            attrs["max_size"] = 3
        else:
            # Altri contesti: richiedere esplicitamente min/max se non presenti
            if "min_size" not in attrs or "max_size" not in attrs:
                raise serializers.ValidationError(
                    "Per questo contesto sono richiesti min_size e max_size."
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
        # Host come participant
        SessionParticipant.objects.create(
            session=session, user=user, role=ParticipantRole.HOST
        )
        # Evento di creazione
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
        )
        read_only_fields = fields

    def get_host(self, obj: Session) -> Dict[str, Any]:
        return {"id": obj.host_id}

    def get_me(self, obj: Session) -> Optional[Dict[str, Any]]:
        user = self.context["request"].user
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


# -------------------------
#  Session transitions
# -------------------------

class SessionStartSerializer(serializers.Serializer):
    """LOBBY -> ACTIVE"""

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        session: Session = self.instance
        user = self.context["request"].user
        if session.host_id != user.id:
            raise serializers.ValidationError("Solo l'host può avviare la sessione.")
        if session.state != SessionState.LOBBY:
            raise serializers.ValidationError("La sessione non è in stato LOBBY.")
        # Capienza richiesta raggiunta (MVP: avvio a capienza piena)
        if session.participants_count != session.max_size:
            raise serializers.ValidationError("Capienza richiesta non raggiunta.")
        return attrs

    @transaction.atomic
    def save(self, **kwargs: Any) -> Session:
        session: Session = self.instance
        session.start()
        session.full_clean()
        session.save(update_fields=["state", "started_at"])
        SessionEvent.objects.create(
            session=session,
            type=SessionEventType.STARTED,
            actor=self.context["request"].user,
            payload={"started_at": timezone.now().isoformat()},
        )
        return session


# -------------------------
#  Invitation: create link
# -------------------------

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


# -------------------------
#  Join via token
# -------------------------

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

        if session.state != SessionState.LOBBY:
            raise serializers.ValidationError("La sessione non è in stato LOBBY.")
        # Utente già partecipante?
        if SessionParticipant.objects.filter(session=session, user=user).exists():
            raise serializers.ValidationError("Utente già parte della sessione.")
        # Capienza
        if session.participants_count >= session.max_size:
            raise serializers.ValidationError("Sessione piena.")

        self._session = session
        self._invitation = invitation
        return attrs

    @transaction.atomic
    def create(self, validated_data: Dict[str, Any]) -> SessionParticipant:
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


# -------------------------
#  Read-only lists
# -------------------------

class ParticipantItemSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()

    class Meta:
        model = SessionParticipant
        fields = ("user", "role", "joined_at")
        read_only_fields = fields

    def get_user(self, obj: SessionParticipant) -> Dict[str, Any]:
        # Ritorna informazioni pubbliche sul partecipante.
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