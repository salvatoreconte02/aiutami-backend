from django.conf import settings
from django.db import models


class ASRTranscript(models.Model):
    # UUID della sessione (stringa)
    session_id = models.CharField(max_length=64, db_index=True)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="asr_transcripts",
    )

    # testo riconosciuto da Azure Speech
    text = models.TextField()

    # per ora sempre True, predisposto per trascrizioni parziali
    is_final = models.BooleanField(default=True)

    # metadati extra (JSON)
    raw_metadata = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"ASRTranscript(session={self.session_id}, user={self.user_id})"