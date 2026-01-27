"""
Session services - business logic for session management.
"""
import logging
from django.core.cache import cache
from django.utils import timezone

from apps.sessions.models import Session, SessionState

logger = logging.getLogger(__name__)


def close_session(session_id: str) -> Session:
    """
    Chiude la sessione e salva il summary.

    - Recupera summary da ModerationState se presente
    - Aggiorna stato a CLOSED
    - Cleanup chiavi Redis (transcript, turns, moderation)

    Args:
        session_id: ID della sessione da chiudere

    Returns:
        Session aggiornata
    """
    session = Session.objects.get(id=session_id)

    # 1. Recupera summary da ModerationState (se disponibile)
    try:
        from apps.moderation.state import load_moderation_state
        mod_state = load_moderation_state(session_id)
        if mod_state and hasattr(mod_state, 'summary') and mod_state.summary:
            session.final_summary = mod_state.summary
    except Exception as e:
        logger.warning(f"Could not load moderation state for session {session_id}: {e}")

    # 2. Aggiorna stato
    if session.state != SessionState.CLOSED:
        session.state = SessionState.CLOSED
        session.ended_at = timezone.now()

        # Determina quali campi aggiornare
        update_fields = ["state", "ended_at"]
        if session.final_summary:
            update_fields.append("final_summary")

        session.save(update_fields=update_fields)

    # 3. Cleanup Redis keys
    _cleanup_session_redis_keys(session_id)

    logger.info(f"Session {session_id} closed and cleaned up")
    return session


def _cleanup_session_redis_keys(session_id: str) -> None:
    """
    Cancella le chiavi Redis associate alla sessione.
    """
    keys_to_delete = [
        f"session:{session_id}:transcript",
        f"turns:{session_id}",
        f"moderation:{session_id}",
    ]

    for key in keys_to_delete:
        try:
            cache.delete(key)
            logger.debug(f"Deleted Redis key: {key}")
        except Exception as e:
            logger.warning(f"Failed to delete Redis key {key}: {e}")
