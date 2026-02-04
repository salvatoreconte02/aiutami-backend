"""
Gestione coda messaggi TTS pendenti per sessione.

I messaggi che non possono essere riprodotti immediatamente (perché qualcuno
sta parlando) vengono accodati in Redis e riprodotti appena il turno torna IDLE.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List
import json

from django.core.cache import cache


# Chiave Redis: moderation:pending_messages:{session_id}
PENDING_MESSAGES_KEY_PREFIX = "moderation:pending_messages"
PENDING_MESSAGES_TTL = 60 * 60  # 1 hour


@dataclass
class PendingMessage:
    """Messaggio TTS in attesa di essere riprodotto."""
    text: str
    trigger_type: str
    created_at: datetime
    trigger_conclusion: bool = False  # Se True, dopo il TTS si transiziona a CONCLUSION


def enqueue_message(
    session_id: int | str,
    text: str,
    trigger_type: str,
    trigger_conclusion: bool = False,
) -> None:
    """
    Aggiunge un messaggio TTS alla coda dei messaggi pendenti per la sessione.

    Args:
        session_id: ID della sessione
        text: Testo del messaggio da pronunciare
        trigger_type: Tipo di trigger che ha generato il messaggio (es. NO_PUSH, TIMER_30)
        trigger_conclusion: Se True, dopo il TTS si transiziona a CONCLUSION
    """
    key = f"{PENDING_MESSAGES_KEY_PREFIX}:{session_id}"

    message_data = {
        "text": text,
        "trigger_type": trigger_type,
        "created_at": datetime.utcnow().isoformat(),
        "trigger_conclusion": trigger_conclusion,
    }

    # Django cache non ha rpush nativo, usiamo get/set
    existing = cache.get(key) or []

    # Se c'è già un messaggio con trigger_conclusion, non accodare nulla
    # La sessione sta per transizionare a CONCLUSION
    for raw in existing:
        try:
            data = json.loads(raw)
            if data.get("trigger_conclusion"):
                return  # Sessione in fase di conclusione, ignora nuovi messaggi
        except (json.JSONDecodeError, KeyError):
            continue

    # Evita duplicati: se esiste già un messaggio con lo stesso testo, skip
    for raw in existing:
        try:
            data = json.loads(raw)
            if data.get("text") == text:
                return  # Messaggio già in coda, non aggiungere duplicato
        except (json.JSONDecodeError, KeyError):
            continue

    existing.append(json.dumps(message_data))
    cache.set(key, existing, timeout=PENDING_MESSAGES_TTL)


def dequeue_all_messages(session_id: int | str) -> List[PendingMessage]:
    """
    Svuota la coda e ritorna tutti i messaggi pendenti per la sessione.

    Args:
        session_id: ID della sessione

    Returns:
        Lista di PendingMessage in ordine FIFO (primo inserito, primo estratto)
    """
    key = f"{PENDING_MESSAGES_KEY_PREFIX}:{session_id}"

    raw_messages = cache.get(key) or []
    cache.delete(key)

    messages = []
    for raw in raw_messages:
        try:
            data = json.loads(raw)
            messages.append(PendingMessage(
                text=data["text"],
                trigger_type=data["trigger_type"],
                created_at=datetime.fromisoformat(data["created_at"]),
                trigger_conclusion=data.get("trigger_conclusion", False),
            ))
        except (json.JSONDecodeError, KeyError):
            continue

    return messages


def has_pending_messages(session_id: int | str) -> bool:
    """
    Verifica se ci sono messaggi TTS pendenti per la sessione.

    Args:
        session_id: ID della sessione

    Returns:
        True se ci sono messaggi in coda, False altrimenti
    """
    key = f"{PENDING_MESSAGES_KEY_PREFIX}:{session_id}"
    existing = cache.get(key)
    return bool(existing)
