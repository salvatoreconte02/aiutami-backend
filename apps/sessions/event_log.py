"""
Persistenza dell'event log della discussione (DiscussionEvent).

Pattern: write-through asincrono. Il caller (es. ModerationService) chiama
`persist_event_async(...)` come fire-and-forget — la latenza percepita
dalla sessione live è ~zero perché la scrittura DB avviene in background.
Se la persistenza fallisce, logghiamo e proseguiamo (i dati restano in
Redis come fallback per le successive 24h).

Schema atteso di `metadata` per event_type:

    HUMAN_TURN
        {
            "duration_s": float,
            "turn_started_at": "ISO-8601 string" | None,
            "summary_after_this_turn": str,         # running summary post-turn
            "empty_transcription": bool,            # True se content == ""
        }

    AI_INTERVENTION
        {
            "reason": str,                          # monopolization|exclusion|...|all_ok
            "score": float,                         # 0.0-1.0
            "was_played": bool,                     # True se TTS effettivamente parlato
            "block_reason": str | None,             # cooldown|min_score|min_time_not_reached|not_active_phase
            "block_detail": str | None,             # human-readable detail (opzionale)
            "summary_at_decision": str,             # summary che il LLM ha visto
            "mode": str,                            # normal|forced_conclusion
        }

    SYSTEM
        {
            "phase": str,                           # opzionale, contesto
            ...                                     # libero, dipende dall'evento
        }
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from asgiref.sync import sync_to_async
from django.core.cache import cache
from django.db import transaction

logger = logging.getLogger(__name__)


SEQUENCE_KEY_TEMPLATE = "session:{session_id}:event_seq"


def _next_sequence_number(session_id) -> int:
    """Atomic increment del counter per la sessione.

    Usa il backend Redis di Django cache (django-redis): supporta INCR
    atomic. La chiave inizia a 0 dopo il primo incr → ritorna 1.
    """
    key = SEQUENCE_KEY_TEMPLATE.format(session_id=session_id)
    try:
        # django-redis espone .incr() atomic via il client Redis sottostante
        return cache.incr(key)
    except ValueError:
        # La chiave non esiste ancora: la inizializziamo e incrementiamo
        cache.set(key, 0, timeout=None)
        return cache.incr(key)


def _resolve_speaker_user_id(speaker_name: Optional[str], session_id) -> Optional[int]:
    """
    Risolve un display_name/username a user_id all'interno dei partecipanti
    della sessione. Ritorna None se non trovato (legittimo per system events
    o per AI_MODERATOR pseudo-speaker).
    """
    if not speaker_name:
        return None
    if speaker_name == "__AI_MODERATOR__":
        return None
    try:
        from apps.sessions.models import SessionParticipant

        # Match contro lo stesso display_name che il moderatore avrebbe
        # usato per identificare il partecipante (first_name → username).
        from apps.accounts.utils import display_name_for_user

        candidates = SessionParticipant.objects.filter(
            session_id=session_id
        ).select_related("user")
        for p in candidates:
            if display_name_for_user(p.user) == speaker_name:
                return p.user_id
    except Exception:
        logger.exception(
            "[EVENT_LOG][SPEAKER_RESOLVE_FAIL] session=%s speaker=%s",
            session_id, speaker_name
        )
    return None


def _create_event_sync(
    session_id,
    event_type: str,
    speaker_name: Optional[str],
    content: str,
    metadata: dict,
) -> None:
    """Sync core. Chiamato da persist_event_async via sync_to_async.

    Wrappato in transaction.atomic() per intercettare IntegrityError (es.
    session_id invalido) immediatamente, senza far propagare il problema
    al commit della transazione esterna.
    """
    from apps.sessions.models import DiscussionEvent

    seq = _next_sequence_number(session_id)
    speaker_id = _resolve_speaker_user_id(speaker_name, session_id)
    with transaction.atomic():
        DiscussionEvent.objects.create(
            session_id=session_id,
            sequence_number=seq,
            event_type=event_type,
            speaker_id=speaker_id,
            content=content or "",
            metadata=metadata or {},
        )


async def persist_event_async(
    *,
    session_id,
    event_type: str,
    speaker_name: Optional[str] = None,
    content: str = "",
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Fire-and-forget persist (chiamato da contesto async).

    Va lanciato con `asyncio.create_task(persist_event_async(...))`. Non
    bloccare il caller — se fallisce, logghiamo e continuiamo. La sessione
    live non si rompe.
    """
    try:
        await sync_to_async(_create_event_sync, thread_sensitive=False)(
            session_id, event_type, speaker_name, content, metadata or {}
        )
    except Exception as e:
        logger.warning(
            "[EVENT_LOG][PERSIST_FAIL] session=%s type=%s err=%s",
            session_id, event_type, e,
        )


def persist_event_sync(
    *,
    session_id,
    event_type: str,
    speaker_name: Optional[str] = None,
    content: str = "",
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Versione sincrona, per call site che NON sono async (es. test, signals).

    Stessa semantica error-safe: log + continue se fallisce.
    """
    try:
        _create_event_sync(session_id, event_type, speaker_name, content, metadata or {})
    except Exception as e:
        logger.warning(
            "[EVENT_LOG][PERSIST_FAIL] session=%s type=%s err=%s",
            session_id, event_type, e,
        )


def reset_sequence_counter(session_id) -> None:
    """Cancella il counter Redis di una sessione (chiamato dal cleanup)."""
    key = SEQUENCE_KEY_TEMPLATE.format(session_id=session_id)
    try:
        cache.delete(key)
    except Exception:
        logger.exception("[EVENT_LOG][SEQ_CLEANUP_FAIL] session=%s", session_id)
