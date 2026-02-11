"""
Modulo per il messaggio introduttivo del moderatore AI a inizio sessione.
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
    Formatta i nomi dei partecipanti per il messaggio intro.
    Per 3 nomi: "Marco, Giulia e Luca"
    Per altri casi: separati da virgola
    """
    if len(names) == 3:
        return f"{names[0]}, {names[1]} e {names[2]}"
    return ", ".join(names)


def set_intro_pending(session_id: str) -> None:
    """Segna che una sessione ha un messaggio intro pendente."""
    cache.set(f"session:intro_pending:{session_id}", True, timeout=300)


def clear_intro_pending(session_id: str) -> None:
    """Rimuove il flag intro pendente."""
    cache.delete(f"session:intro_pending:{session_id}")


def has_intro_pending(session_id: str) -> bool:
    """Verifica se una sessione ha un messaggio intro pendente."""
    return cache.get(f"session:intro_pending:{session_id}") is True


def generate_intro_message(session_id: str) -> str:
    """
    Genera il messaggio intro con i nomi dei partecipanti.

    Args:
        session_id: ID della sessione (stringa UUID)

    Returns:
        Il messaggio intro formattato con i nomi dei partecipanti
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
