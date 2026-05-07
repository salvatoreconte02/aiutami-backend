"""Tests del flow di consenso GDPR alla registrazione.

Per Art. 7(1) GDPR il Titolare deve poter dimostrare il consenso del
partecipante. Quindi:
- signup richiede consent_accepted=True nel body
- al successo viene creato un UserProfile con consent_accepted_at = now()
- GET /api/accounts/me/ ritorna il timestamp di consenso

Vedi docs/plans/2026-05-07-informativa-privacy-aiutami.md.
"""

from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status


class SignupConsentTests(TestCase):
    """POST /api/accounts/signup/ richiede consent_accepted=True."""

    def setUp(self):
        self.client = APIClient()

    def test_signup_without_consent_field_returns_400(self):
        """Body senza il campo consent_accepted → 400."""
        response = self.client.post(
            "/api/accounts/signup/",
            {
                "username": "alice",
                "email": "alice@e.com",
                "password": "passw0rd!",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Nessun utente creato
        self.assertFalse(User.objects.filter(username="alice").exists())

    def test_signup_with_consent_false_returns_400(self):
        """Body con consent_accepted=False → 400 (consenso esplicito richiesto)."""
        response = self.client.post(
            "/api/accounts/signup/",
            {
                "username": "bob",
                "email": "bob@e.com",
                "password": "passw0rd!",
                "consent_accepted": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(User.objects.filter(username="bob").exists())

    def test_signup_with_consent_true_creates_user_and_profile(self):
        """Body con consent_accepted=True → 201, User + UserProfile creati,
        consent_accepted_at valorizzato a now()."""
        from django.utils import timezone
        before = timezone.now()
        response = self.client.post(
            "/api/accounts/signup/",
            {
                "username": "carol",
                "email": "carol@e.com",
                "password": "passw0rd!",
                "consent_accepted": True,
            },
            format="json",
        )
        after = timezone.now()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(username="carol")
        # Profile esiste con timestamp valido
        from apps.accounts.models import UserProfile
        profile = UserProfile.objects.get(user=user)
        self.assertIsNotNone(profile.consent_accepted_at)
        self.assertGreaterEqual(profile.consent_accepted_at, before)
        self.assertLessEqual(profile.consent_accepted_at, after)


class MeEndpointConsentTests(TestCase):
    """GET /api/accounts/me/ espone consent_accepted_at."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="dave", email="dave@e.com", password="passw0rd!"
        )

    def test_me_returns_consent_accepted_at_null_if_no_profile(self):
        """Utente legacy senza profilo → consent_accepted_at è null
        (backward-compat per account creati prima di questa feature)."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/accounts/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("consent_accepted_at", response.data)
        self.assertIsNone(response.data["consent_accepted_at"])

    def test_me_returns_consent_accepted_at_timestamp_when_present(self):
        """Utente con profilo + consenso → /me/ ritorna il timestamp."""
        from django.utils import timezone
        from apps.accounts.models import UserProfile
        ts = timezone.now()
        UserProfile.objects.create(user=self.user, consent_accepted_at=ts)

        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/accounts/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data["consent_accepted_at"])
