"""
Modello SessionVote e costanti Murder Mystery.

Step 6 del refactor task-pluggable: SessionVote e le costanti MM vivevano in
apps/sessions/models.py. Ora sono qui dentro il plugin MM. La tabella DB non
cambia grazie a Meta.app_label = "ai_sessions" e db_table = "session_vote".
"""

from django.db import models


# Sospettati e colpevole Murder Mystery
MURDER_MYSTERY_SUSPECTS = ["Eddie", "Mickey", "Billy"]
MURDER_MYSTERY_GUILTY = "Eddie"


class SessionVote(models.Model):
    """
    Voto di un partecipante per il colpevole (Murder Mystery).
    Un solo voto per partecipante per sessione.
    """

    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(
        "ai_sessions.Session",
        on_delete=models.CASCADE,
        related_name="votes",
    )
    participant = models.ForeignKey(
        "ai_sessions.SessionParticipant",
        on_delete=models.CASCADE,
        related_name="votes",
    )
    suspect_chosen = models.CharField(max_length=32)  # "Eddie", "Mickey", "Billy"
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Mantiene la tabella fisica sotto l'app ai_sessions: zero data migration.
        app_label = "ai_sessions"
        db_table = "session_vote"
        unique_together = [("session", "participant")]
        indexes = [
            models.Index(fields=["session"]),
        ]

    def __str__(self) -> str:
        return f"{self.participant.user_id} voted {self.suspect_chosen} in {self.session_id}"
