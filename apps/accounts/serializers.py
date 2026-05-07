from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .models import UserProfile


class UserSerializer(serializers.ModelSerializer):
    consent_accepted_at = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "consent_accepted_at",
        ]

    def get_consent_accepted_at(self, obj: User):
        """Ritorna il timestamp di consenso dal profilo associato.

        NULL per account legacy senza profilo (es. account creati prima
        dell'introduzione del flow di consenso GDPR).
        """
        profile = getattr(obj, "profile", None)
        if profile is None:
            return None
        return profile.consent_accepted_at


class SignupSerializer(serializers.ModelSerializer):
    """Registrazione + raccolta del consenso GDPR in un singolo POST.

    Art. 7(1) GDPR: il Titolare deve poter dimostrare il consenso. Per
    questo `consent_accepted=True` è obbligatorio: il backend rifiuta la
    creazione dell'utente se il consenso manca o è False, e registra il
    timestamp in UserProfile.consent_accepted_at.
    """

    password = serializers.CharField(write_only=True, min_length=8)
    consent_accepted = serializers.BooleanField(write_only=True, required=True)

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "password",
            "first_name",
            "last_name",
            "consent_accepted",
        ]

    def validate_consent_accepted(self, value: bool) -> bool:
        if value is not True:
            raise serializers.ValidationError(
                "Devi accettare l'informativa privacy per registrarti."
            )
        return value

    @transaction.atomic
    def create(self, validated_data):
        password = validated_data.pop("password")
        validated_data.pop("consent_accepted")  # consumato dalla validazione
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        UserProfile.objects.create(user=user, consent_accepted_at=timezone.now())
        return user
