"""
Gestisce lo stato runtime delle sessioni ASR attive.
Oggi: memorizzato in-process (dict globale).
Futuro: sostituibile con Redis mantenendo l'interfaccia.
"""

from typing import Dict, Optional
from .types import AsrSessionKey, AsrSessionState

_SESSIONS: Dict[AsrSessionKey, AsrSessionState] = {}


def get_or_create_session(key: AsrSessionKey) -> AsrSessionState:
    if key not in _SESSIONS:
        _SESSIONS[key] = AsrSessionState(key=key)
    return _SESSIONS[key]


def get_session(key: AsrSessionKey) -> Optional[AsrSessionState]:
    return _SESSIONS.get(key)


def remove_session(key: AsrSessionKey) -> None:
    if key in _SESSIONS:
        del _SESSIONS[key]


def list_active_sessions():
    return list(_SESSIONS.values())