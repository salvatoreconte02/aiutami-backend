# apps/asr/models.py

from django.conf import settings
from django.db import models


class ASRTranscript(models.Model):
    # ID della sessione così come la usi nel worker (stringa UUID)
    session_id = models.CharField(max_length=64, db_index=True)

    # Utente Django collegato alla trascrizione
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="asr_transcripts",
    )

    # Testo trascritto (tipicamente "final" da Azure)
    text = models.TextField()

    # Flag per eventuali trascrizioni non definitive (per ora sempre True)
    is_final = models.BooleanField(default=True)

    # Eventuale metadato grezzo (JSON) se vuoi salvare info aggiuntive in futuro
    raw_metadata = models.JSONField(blank=True, null=True)

    # Timestamp creazione
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"ASRTranscript(session={self.session_id}, user={self.user_id})"