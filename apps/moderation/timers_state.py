from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

import json

from django.core.cache import cache


# Chiave base per lo stato dei timer di moderazione in Redis/cache
TIMERS_STATE_KEY_TEMPLATE = "moderation:timers:{session_id}"


@dataclass
class ModerationTimersState:
    """
    Stato dei timer di moderazione per una singola sessione.

    Viene usato per implementare i trigger a tempo:
    - NO PUSH (silenzio)
    - UTENTE INATTIVO
    - TIMER SESSIONE (25'/30')
    """

    # Timestamp di riferimento
    session_started_at: Optional[datetime] = None
    last_any_activity_at: Optional[datetime] = None  # ultimo evento "qualcuno fa qualcosa"
    # ultimo turno parlato per utente (user_id -> datetime)
    last_user_speak_at: Dict[str, datetime] = field(default_factory=dict)

    # Flag per non ripetere notifiche all'infinito
    no_push_notified: bool = False
    timer_25_notified: bool = False
    timer_30_notified: bool = False

    # Utenti per cui è già stato fatto l'avviso di "inattivo"
    inactive_notified_user_ids: List[str] = field(default_factory=list)

    @classmethod
    def initial(cls) -> "ModerationTimersState":
        """
        Stato iniziale di default: nessun timer ancora attivo.
        """
        return cls()

    # ------------------------------------------------------------------
    # Serializzazione / deserializzazione
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """
        Serializza lo stato in un dict JSON-compatibile (datetime -> isoformat).
        """
        data = asdict(self)

        def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
            return dt.isoformat() if dt is not None else None

        data["session_started_at"] = _dt_to_str(self.session_started_at)
        data["last_any_activity_at"] = _dt_to_str(self.last_any_activity_at)

        # last_user_speak_at: dict[str, datetime] -> dict[str, str]
        data["last_user_speak_at"] = {
            user_id: _dt_to_str(dt) for user_id, dt in self.last_user_speak_at.items()
        }

        return data

    @classmethod
    def from_dict(cls, data: dict) -> "ModerationTimersState":
        """
        Deserializza lo stato da un dict JSON-compatibile (isoformat -> datetime).
        """
        def _str_to_dt(s: Optional[str]) -> Optional[datetime]:
            if not s:
                return None
            try:
                return datetime.fromisoformat(s)
            except ValueError:
                return None

        session_started_at = _str_to_dt(data.get("session_started_at"))
        last_any_activity_at = _str_to_dt(data.get("last_any_activity_at"))

        raw_last_user_speak_at: dict[str, Any] = data.get("last_user_speak_at", {}) or {}
        last_user_speak_at: dict[str, datetime] = {}
        for user_id, ts_str in raw_last_user_speak_at.items():
            dt = _str_to_dt(ts_str)
            if dt is not None:
                last_user_speak_at[user_id] = dt

        return cls(
            session_started_at=session_started_at,
            last_any_activity_at=last_any_activity_at,
            last_user_speak_at=last_user_speak_at,
            no_push_notified=bool(data.get("no_push_notified", False)),
            timer_25_notified=bool(data.get("timer_25_notified", False)),
            timer_30_notified=bool(data.get("timer_30_notified", False)),
            inactive_notified_user_ids=list(data.get("inactive_notified_user_ids", []) or []),
        )


# ----------------------------------------------------------------------
# Funzioni di accesso (load/save) su Redis / cache
# ----------------------------------------------------------------------


def _make_timers_key(session_id: int | str) -> str:
    return TIMERS_STATE_KEY_TEMPLATE.format(session_id=session_id)


def load_timers_state(session_id: int | str) -> ModerationTimersState:
    """
    Carica lo stato dei timer di moderazione per la sessione indicata.

    Se non esiste ancora nulla in cache/Redis, restituisce lo stato iniziale.
    """
    key = _make_timers_key(session_id)
    raw = cache.get(key)
    if raw is None:
        return ModerationTimersState.initial()

    # raw può essere già un dict o una stringa JSON, a seconda di come è stato salvato.
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return ModerationTimersState.initial()
    elif isinstance(raw, dict):
        data = raw
    else:
        # tipo inatteso: si riparte da zero
        return ModerationTimersState.initial()

    try:
        return ModerationTimersState.from_dict(data)
    except Exception:
        # fallback difensivo
        return ModerationTimersState.initial()


def save_timers_state(session_id: int | str, state: ModerationTimersState) -> None:
    """
    Salva lo stato dei timer di moderazione per la sessione indicata.
    """
    key = _make_timers_key(session_id)
    data = state.to_dict()
    cache.set(key, json.dumps(data, ensure_ascii=False))


# ----------------------------------------------------------------------
# Costanti soglia per i trigger a tempo
# ----------------------------------------------------------------------

NO_PUSH_THRESHOLD = timedelta(seconds=15)      # silenzio 15s
TIMER_25_THRESHOLD = timedelta(minutes=25)     # avviso 5 minuti rimanenti
TIMER_30_THRESHOLD = timedelta(minutes=30)     # fine discussione

# Soglia per UTENTE INATTIVO (messaggio vocale)
INACTIVE_USER_THRESHOLD = timedelta(minutes=10)


# ----------------------------------------------------------------------
# Funzioni di aggiornamento dei timer (da chiamare da turns/sessions)
# ----------------------------------------------------------------------

def mark_session_started(session_id: int | str, when: Optional[datetime] = None) -> None:
    """
    Imposta (o reimposta) l'istante di inizio sessione e l'ultima attività.

    Da chiamare quando la sessione entra in ACTIVE.
    """
    now = when or datetime.utcnow()
    state = load_timers_state(session_id)
    state.session_started_at = now
    state.last_any_activity_at = now
    save_timers_state(session_id, state)


def mark_any_activity(session_id: int | str, when: Optional[datetime] = None) -> None:
    """
    Aggiorna l'ultimo istante in cui "qualcuno ha fatto qualcosa" nella sessione:
    - inizio/fine turno umano,
    - inizio/fine turno AI,
    - altri eventi significativi.

    Da usare per il trigger NO PUSH.
    """
    now = when or datetime.utcnow()
    state = load_timers_state(session_id)
    state.last_any_activity_at = now
    save_timers_state(session_id, state)


def mark_user_spoke(
    session_id: int | str,
    user_id: int | str,
    when: Optional[datetime] = None,
) -> None:
    """
    Aggiorna l'ultimo istante in cui un certo utente ha parlato.

    Utile per il trigger UTENTE INATTIVO (che si potrà implementare in seguito).
    """
    now = when or datetime.utcnow()
    state = load_timers_state(session_id)
    state.last_any_activity_at = now
    state.last_user_speak_at[str(user_id)] = now
    save_timers_state(session_id, state)