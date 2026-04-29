"""
Modulo per il messaggio introduttivo del moderatore AI a inizio sessione.
"""
from django.core.cache import cache


# Scheletro task-agnostic. La frase `{tail}` viene iniettata dal
# TaskDefinition corrispondente al contesto della sessione
# (vedi step 4 di docs/plans/2026-04-08-task-pluggable-architecture.md).
INTRO_MESSAGE_TEMPLATE = (
    "Benvenuti {nomi}. Sono il moderatore e vi guiderò nella discussione. "
    "Per parlare, premete il pulsante microfono. Se qualcuno sta già parlando, potete prenotarvi. "
    "Ascoltate gli altri e argomentate le vostre ipotesi. Avrete a disposizione trenta minuti per confrontarvi. "
    "{tail} "
    "Buona discussione!"
)


def format_participant_names(names: list[str]) -> str:
    """
    Formatta i nomi dei partecipanti per il messaggio intro, generalizzato
    a N partecipanti qualunque:
      - 1 nome: "Marco"
      - 2 nomi: "Marco e Giulia"
      - 3+ nomi: "Marco, Giulia e Luca"
    """
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} e {names[-1]}"


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
    Genera il messaggio intro con i nomi dei partecipanti e la frase
    finale task-specifica.

    Args:
        session_id: ID della sessione (stringa UUID)

    Returns:
        Il messaggio intro formattato con i nomi dei partecipanti
    """
    from apps.sessions.models import Session, SessionParticipant
    from apps.tasks.registry import get_task

    participants = SessionParticipant.objects.filter(
        session_id=session_id
    ).select_related("user")

    names = [
        p.user.first_name or p.user.get_username()
        for p in participants
    ]

    session = Session.objects.get(id=session_id)
    task = get_task(session.context)

    # --- DEBUG: intro breve (~5s di TTS) per testing. ---
    # Per ripristinare l'intro completo (~2 min con scenario + ground rules),
    # commentare il return qui sotto e ri-attivare il blocco originale.
    return f"Benvenuti {format_participant_names(names)}. Buona discussione."

    # return INTRO_MESSAGE_TEMPLATE.format(
    #     nomi=format_participant_names(names),
    #     tail=task.intro_message_tail(),
    # )
