from __future__ import annotations

import uuid
import secrets
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class SessionState(models.TextChoices):
    LOBBY = "LOBBY", "Lobby"
    ACTIVE = "ACTIVE", "Active"
    CONCLUSION = "CONCLUSION", "Conclusion"
    CLOSED = "CLOSED", "Closed"


class SessionContext(models.TextChoices):
    MURDER_MYSTERY = "MURDER_MYSTERY", "Murder Mystery"
    THERAPY = "THERAPEUTIC", "Contesto terapeutico"
    WORK = "WORKPLACE", "Contesto lavorativo"
    ACADEMIC = "ACADEMIC", "Contesto accademico"


class ParticipantRole(models.TextChoices):
    HOST = "HOST", "Host"
    PARTICIPANT = "PARTICIPANT", "Participant"


class SessionEventType(models.TextChoices):
    CREATED = "CREATED", "Created"
    INVITE_CREATED = "INVITE_CREATED", "Invite created"
    JOINED = "JOINED", "Joined"
    STARTED = "STARTED", "Started"
    CONCLUSION_AUTO = "CONCLUSION_AUTO", "Conclusion (auto)"
    CLOSED_AUTO = "CLOSED_AUTO", "Closed (auto)"


# Hardcoded suspects for Murder Mystery MVP
MURDER_MYSTERY_SUSPECTS = ["Eddie", "Mickey", "Billy"]
MURDER_MYSTERY_GUILTY = "Eddie"


class Session(models.Model):
    """
    Contenitore della stanza vocale e del suo ciclo di vita.
    Regole chiave (MVP):
      - Stati: LOBBY -> ACTIVE -> CONCLUSION -> CLOSED
      - Join consentito solo in LOBBY
      - Capienza non superabile
      - Murder Mystery: min_size=max_size=3 (obbligatorio)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Metadati
    title = models.CharField(max_length=200)
    context = models.CharField(max_length=32, choices=SessionContext.choices)
    state = models.CharField(
        max_length=16, choices=SessionState.choices, default=SessionState.LOBBY
    )

    # Capienza
    min_size = models.PositiveSmallIntegerField()
    max_size = models.PositiveSmallIntegerField()

    # Host
    host = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,  # non si elimina accidentalmente l'host
        related_name="hosted_sessions",
    )

    # Timeline
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    conclusion_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    final_summary = models.TextField(
        blank=True,
        null=True,
        help_text="Summary finale della sessione dal moderatore AI"
    )
    report_text = models.TextField(
        blank=True,
        default="",
        help_text="Testo del report generato da LLM alla chiusura"
    )

    class Meta:
        db_table = "session"
        indexes = [
            models.Index(fields=["state"]),
            models.Index(fields=["host", "state"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.title} [{self.state}]"

    def clean(self):
        # Vincoli generali
        if self.max_size < 2:
            raise ValidationError("max_size deve essere >= 2.")
        if self.min_size > self.max_size:
            raise ValidationError("min_size non può superare max_size.")

        # Regola di contesto (Murder Mystery => 3/3 fissi)
        if self.context == SessionContext.MURDER_MYSTERY:
            if self.min_size != 3 or self.max_size != 3:
                raise ValidationError(
                    "Per il contesto Murder Mystery, min_size e max_size devono essere 3."
                )

    @property
    def participants_count(self) -> int:
        # Include l'host (creato come participant con ruolo HOST)
        return self.participants.count()

    def start(self):
        # Transizione LOBBY -> ACTIVE (capienza richiesta raggiunta)
        if self.state != SessionState.LOBBY:
            raise ValidationError("La sessione non è in stato LOBBY.")
        if self.participants_count < self.min_size or self.participants_count < self.max_size:
            # Per Murder Mystery (3/3) va raggiunta la capienza; per altri contesti
            # si può personalizzare. In MVP: avvio al raggiungimento della capienza.
            if self.participants_count != self.max_size:
                raise ValidationError("Capienza richiesta non raggiunta.")
        self.state = SessionState.ACTIVE
        self.started_at = timezone.now()

    # Le transizioni successive (ACTIVE -> CONCLUSION -> CLOSED) sono automatiche
    # e saranno gestite dal servizio applicativo (non nel model).


class SessionParticipant(models.Model):
    """
    Legame utente–sessione e ruolo.
    L'HOST viene inserito al momento della creazione della sessione.
    """

    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(
        Session, on_delete=models.CASCADE, related_name="participants"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="session_memberships"
    )
    role = models.CharField(
        max_length=16, choices=ParticipantRole.choices, default=ParticipantRole.PARTICIPANT
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    ready_to_conclude = models.BooleanField(default=False)

    class Meta:
        db_table = "session_participant"
        unique_together = ("session", "user")
        indexes = [
            models.Index(fields=["session"]),
            models.Index(fields=["session", "role"]),
        ]
        ordering = ["joined_at"]

    def __str__(self) -> str:
        return f"{self.user_id} in {self.session_id} ({self.role})"


def _generate_token() -> str:
    # Token opaco e URL-safe
    return secrets.token_urlsafe(32)


class Invitation(models.Model):
    """
    Token di invito riutilizzabile (nessun max_uses/scadenza in MVP).
    L'esito del join dipende da stato e capienza della sessione.
    """

    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(
        Session, on_delete=models.CASCADE, related_name="invitations"
    )
    token = models.CharField(max_length=255, unique=True, default=_generate_token)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "invitation"
        indexes = [
            models.Index(fields=["session"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Invitation({self.session_id})"


class SessionEvent(models.Model):
    """
    Audit minimo delle azioni/transizioni significative.
    actor può essere NULL per eventi generati dal sistema (automatici).
    """

    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(
        Session, on_delete=models.CASCADE, related_name="events"
    )
    type = models.CharField(max_length=32, choices=SessionEventType.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="session_events",
    )
    payload = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "session_event"
        indexes = [
            models.Index(fields=["session"]),
            models.Index(fields=["type"]),
        ]
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.session_id} - {self.type}"


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