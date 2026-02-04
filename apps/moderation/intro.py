"""
Intro message module for AI moderator introduction at session start.
"""
from django.core.cache import cache


INTRO_MESSAGE_TEMPLATE = (
    "Benvenuti {nomi}. Sono il moderatore e vi guiderò nella discussione. "
    "Per parlare, premete il pulsante microfono. Se qualcuno sta già parlando, potete prenotarvi. "
    "Ascoltate gli altri e argomentate le vostre ipotesi. Avrete a disposizione trenta minuti per confrontarvi. "
    "Quando avrete capito chi è il colpevole, premete 'Pronto alla conclusione'. "
    "Buona discussione!"
)


def format_participant_names(names: list[str]) -> str:
    """
    Format participant names for intro message.
    For 3 names: "Marco, Giulia e Luca"
    For other counts: comma-separated fallback
    """
    if len(names) == 3:
        return f"{names[0]}, {names[1]} e {names[2]}"
    return ", ".join(names)


def set_intro_pending(session_id: str) -> None:
    """Mark that a session has a pending intro message."""
    cache.set(f"session:intro_pending:{session_id}", True, timeout=300)


def clear_intro_pending(session_id: str) -> None:
    """Remove the pending intro flag."""
    cache.delete(f"session:intro_pending:{session_id}")


def has_intro_pending(session_id: str) -> bool:
    """Check if a session has a pending intro message."""
    return cache.get(f"session:intro_pending:{session_id}") is True


def generate_intro_message(session_id: str) -> str:
    """
    Generate the intro message with participant names.

    Args:
        session_id: The session ID (UUID string)

    Returns:
        The formatted intro message with participant names
    """
    from apps.sessions.models import SessionParticipant

    participants = SessionParticipant.objects.filter(
        session_id=session_id
    ).select_related("user")

    names = [
        p.user.first_name or p.user.get_username()
        for p in participants
    ]

    return INTRO_MESSAGE_TEMPLATE.format(nomi=format_participant_names(names))
