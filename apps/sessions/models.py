from __future__ import annotations

import uuid
import secrets
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class SessionState(models.TextChoices):
    LOBBY = "LOBBY", "Lobby"
    INDIVIDUAL_RANKING = "INDIVIDUAL_RANKING", "Individual ranking"
    ACTIVE = "ACTIVE", "Active"
    CONCLUSION = "CONCLUSION", "Conclusion"
    CLOSED = "CLOSED", "Closed"


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


# Costanti MM e modello SessionVote spostati in apps/tasks/murder_mystery/models.py
# (Step 6 del refactor task-pluggable). La tabella DB resta la stessa.


class Session(models.Model):
    """
    Contenitore della stanza vocale e del suo ciclo di vita.
    Regole chiave:
      - Stati: LOBBY -> ACTIVE -> CONCLUSION -> CLOSED
      - Join consentito solo in LOBBY
      - Capienza non superabile
      - Capienza validata tramite TaskDefinition (min/max_participants, fixed_size)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Metadati
    title = models.CharField(max_length=200)
    # Step 2 refactor task-pluggable: il valore è una chiave del registry
    # in apps/tasks/registry.py (es. "murder_mystery"). Validato in clean().
    context = models.CharField(max_length=64)
    state = models.CharField(
        max_length=32, choices=SessionState.choices, default=SessionState.LOBBY
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
    individual_ranking_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp di inizio fase INDIVIDUAL_RANKING. NULL per "
                  "sessioni senza questa fase. Usato per calcolo timer 8 min.",
    )
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
    report_data = models.JSONField(
        null=True,
        blank=True,
        default=None,
        help_text="Dati strutturati del report (partecipazione, Gini, etc.)"
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

        # Validazione del context contro il registry dei task.
        # Import lazy per evitare cicli di import al boot.
        from apps.tasks.registry import get_task, TaskNotFound

        try:
            task = get_task(self.context)
        except TaskNotFound as exc:
            raise ValidationError(
                f"Context '{self.context}' non è un task registrato."
            ) from exc

        if task.fixed_size:
            if (
                self.min_size != task.min_participants
                or self.max_size != task.max_participants
            ):
                raise ValidationError(
                    f"Per il task {task.display_name}, min_size e max_size "
                    f"devono essere {task.min_participants}."
                )
        else:
            if self.min_size < task.min_participants:
                raise ValidationError(
                    f"min_size per {task.display_name} deve essere >= {task.min_participants}."
                )
            if self.max_size > task.max_participants:
                raise ValidationError(
                    f"max_size per {task.display_name} deve essere <= {task.max_participants}."
                )

    @property
    def participants_count(self) -> int:
        # Include l'host (creato come participant con ruolo HOST)
        return self.participants.count()

    def start(self):
        # Transizione LOBBY -> INDIVIDUAL_RANKING (per task survival) o ACTIVE.
        if self.state != SessionState.LOBBY:
            raise ValidationError("La sessione non è in stato LOBBY.")
        if self.participants_count < self.min_size:
            raise ValidationError("Numero minimo di partecipanti non raggiunto.")

        from apps.tasks.registry import get_task
        task = get_task(self.context)

        if task.requires_individual_ranking_phase():
            self.state = SessionState.INDIVIDUAL_RANKING
            self.individual_ranking_started_at = timezone.now()
            # started_at resta NULL: verrà impostato quando si transita ad ACTIVE
            # in _finalize_individual_ranking_phase()
        else:
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


class DiscussionEventType(models.TextChoices):
    """Tipi di evento registrati nell'event log della discussione.

    Distinto da SessionEventType (sopra) che traccia transizioni di stato
    macro della sessione (CREATED, JOINED, STARTED, ...). DiscussionEvent
    cattura invece la sequenza turn-by-turn di una sessione attiva, per
    analisi empirica a freddo.
    """
    HUMAN_TURN = "human_turn", "Human turn"
    AI_INTERVENTION = "ai_intervention", "AI intervention"
    SYSTEM = "system", "System event"


class DiscussionEvent(models.Model):
    """Event log immutabile della discussione (turni umani + interventi AI).

    Pattern event sourcing: una riga per ogni evento, ordinato via
    `sequence_number` (atomic counter Redis-backed, vedi event_log.py).
    Permette di ricostruire la timeline esatta di una sessione a freddo
    per analisi empirica della tesi (Synergy gain, intervention patterns,
    summary evolution debugging).

    I dati cumulativi e gli aggregati continuano a vivere in
    `Session.report_data`; questa tabella tiene il dato GREZZO turn-by-turn.
    """

    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(
        Session, on_delete=models.CASCADE, related_name="discussion_events"
    )
    sequence_number = models.PositiveBigIntegerField(
        help_text="Counter monotono per sessione, atomic via Redis INCR. "
                  "Garantisce ordering robusto anche con timestamp identici."
    )
    timestamp = models.DateTimeField(
        default=timezone.now,
        help_text="UTC con microsecondi, momento di registrazione dell'evento."
    )
    event_type = models.CharField(
        max_length=32, choices=DiscussionEventType.choices
    )
    speaker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="discussion_events_as_speaker",
        help_text="Per HUMAN_TURN: chi ha parlato. Per AI_INTERVENTION: "
                  "lo speaker del turno PRECEDENTE che ha innescato la "
                  "decisione del moderatore. NULL per SYSTEM events."
    )
    content = models.TextField(
        blank=True,
        default="",
        help_text="HUMAN_TURN: trascrizione del turno (può essere vuota se "
                  "ASR non ha trascritto nulla). AI_INTERVENTION: messaggio "
                  "del moderatore (vuoto se reason=all_ok o intervento bloccato "
                  "senza testo). SYSTEM: descrizione human-readable."
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Campi specifici per event_type. Vedi event_log.py per "
                  "lo schema atteso di ciascun tipo."
    )

    class Meta:
        db_table = "session_discussion_event"
        ordering = ["session", "sequence_number"]
        indexes = [
            models.Index(fields=["session", "sequence_number"]),
            models.Index(fields=["session", "event_type"]),
            models.Index(fields=["session", "timestamp"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "sequence_number"],
                name="uniq_discussion_event_seq_per_session",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"DiscussionEvent[{self.session_id}/{self.sequence_number}] "
            f"{self.event_type}"
        )
