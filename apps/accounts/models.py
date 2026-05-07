from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    """Estende django.contrib.auth.User con i campi specifici del progetto.

    Per ora contiene solo il timestamp di accettazione dell'informativa
    privacy/GDPR — Art. 7(1) GDPR richiede al Titolare di poter dimostrare
    il consenso. Vedi docs/plans/2026-05-07-informativa-privacy-aiutami.md.

    Pattern OneToOne perché non possiamo modificare il modello User di
    Django senza una migration distruttiva.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    consent_accepted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp di accettazione dell'informativa privacy/GDPR. "
                  "NULL per account creati prima dell'introduzione del flow "
                  "di consenso (backward-compat).",
    )

    class Meta:
        db_table = "user_profile"

    def __str__(self) -> str:
        return f"Profile({self.user.username})"
