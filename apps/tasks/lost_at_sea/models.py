"""
Modello LostAtSeaRanking per il task Lost at Sea.

Un solo ranking per sessione (consenso di gruppo), gestito dall'host.
L'host puo aggiornarlo durante la fase ACTIVE; in CONCLUSION viene congelato.
"""

from django.db import models


class LostAtSeaRanking(models.Model):
    """
    Ranking di gruppo dei 15 oggetti per la sopravvivenza in mare.
    Un solo ranking per sessione (OneToOne), aggiornabile dall'host.
    """

    id = models.BigAutoField(primary_key=True)
    session = models.OneToOneField(
        "ai_sessions.Session",
        on_delete=models.CASCADE,
        related_name="lost_at_sea_ranking",
    )
    submitted_by = models.ForeignKey(
        "ai_sessions.SessionParticipant",
        on_delete=models.CASCADE,
        related_name="lost_at_sea_rankings_submitted",
    )
    ranked_items = models.JSONField(
        help_text="Lista ordinata dei 15 oggetti (posizione 0 = piu importante)."
    )
    is_final = models.BooleanField(
        default=False,
        help_text="True quando l'host ha confermato il ranking in fase CONCLUSION."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "tasks"
        db_table = "tasks_lost_at_sea_ranking"

    def __str__(self) -> str:
        return f"LostAtSeaRanking for session {self.session_id}"


class LostAtSeaIndividualRanking(models.Model):
    """Ranking individuale pre-discussione di un partecipante.
    Una riga per (sessione, partecipante). Autosave su PUT, marcato
    is_submitted=True su POST submit esplicito o alla finalizzazione
    della fase INDIVIDUAL_RANKING.
    """

    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(
        "ai_sessions.Session",
        on_delete=models.CASCADE,
        related_name="lost_at_sea_individual_rankings",
    )
    participant = models.ForeignKey(
        "ai_sessions.SessionParticipant",
        on_delete=models.CASCADE,
        related_name="lost_at_sea_individual_rankings",
    )
    ranked_items = models.JSONField(
        help_text="Lista ordinata dei 15 oggetti (posizione 0 = più importante)."
    )
    is_submitted = models.BooleanField(
        default=False,
        help_text="True quando il partecipante ha confermato esplicitamente, "
                  "oppure quando la fase è stata finalizzata."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "tasks"
        db_table = "tasks_lost_at_sea_individual_ranking"
        constraints = [
            models.UniqueConstraint(
                fields=["session", "participant"],
                name="uniq_lost_at_sea_individual_ranking_per_participant",
            ),
        ]
        indexes = [
            models.Index(fields=["session", "is_submitted"]),
        ]

    def __str__(self) -> str:
        return (
            f"LostAtSeaIndividualRanking[{self.session_id}/{self.participant_id} "
            f"submitted={self.is_submitted}]"
        )
