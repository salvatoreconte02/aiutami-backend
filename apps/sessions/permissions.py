from __future__ import annotations
from rest_framework.permissions import BasePermission, SAFE_METHODS

from .models import Session, SessionParticipant


class IsSessionMember(BasePermission):
    """
    Consente l’accesso solo ai membri della sessione (HOST o PARTICIPANT).
    Da usare su detail/participants.
    """

    def has_object_permission(self, request, view, obj: Session) -> bool:
        if request.user.is_anonymous:
            return False
        return SessionParticipant.objects.filter(session=obj, user=request.user).exists()
