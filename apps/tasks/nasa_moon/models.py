"""
Modello NasaRanking per il task NASA Moon Survival.

Un solo ranking per sessione (consenso di gruppo), gestito dall'host.
L'host puo aggiornarlo durante la fase ACTIVE; in CONCLUSION viene congelato.
"""

from django.db import models


class NasaRanking(models.Model):
    """
    Ranking di gruppo dei 15 oggetti per la sopravvivenza sulla Luna.
    Un solo ranking per sessione (OneToOne), aggiornabile dall'host.
    """

    id = models.BigAutoField(primary_key=True)
    session = models.OneToOneField(
        "ai_sessions.Session",
        on_delete=models.CASCADE,
        related_name="nasa_ranking",
    )
    submitted_by = models.ForeignKey(
        "ai_sessions.SessionParticipant",
        on_delete=models.CASCADE,
        related_name="nasa_rankings_submitted",
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
        db_table = "tasks_nasa_ranking"

    def __str__(self) -> str:
        return f"NasaRanking for session {self.session_id}"
