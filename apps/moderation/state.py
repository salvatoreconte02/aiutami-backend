

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

from django.core.cache import cache


REDIS_KEY_TEMPLATE = "moderation:{session_id}"
DEFAULT_SUMMARY = (
    "La discussione è appena iniziata e non sono ancora emersi punti principali."
)


@dataclass
class ModerationState:
    """
    Stato di moderazione per una singola sessione.
    Vive in Redis e viene aggiornato ad ogni turno umano.
    """
    summary: str
    ai_interventions_count: int
    last_ai_intervention_at: Optional[datetime]
    conclusion_reason: Optional[str]  # "timer_expired" or "all_participants_ready"
    forced_conclusion_done: bool  # True dopo il primo FORCED_CONCLUSION
    speaking_time_per_participant: dict[str, float]  # {"name": cumulative_seconds}
    interventions_log: list[dict]  # log di ogni intervento AI normal mode
    session_started_at: Optional[datetime]  # per calcolo elapsed_seconds
    current_turn_started_at: Optional[datetime]  # timestamp inizio turno corrente

    @classmethod
    def initial(
        cls,
        participants: Optional[list[str]] = None,
        session_started_at: Optional[datetime] = None,
    ) -> "ModerationState":
        speaking_time = (
            {name: 0.0 for name in participants} if participants else {}
        )
        return cls(
            summary=DEFAULT_SUMMARY,
            ai_interventions_count=0,
            last_ai_intervention_at=None,
            conclusion_reason=None,
            forced_conclusion_done=False,
            speaking_time_per_participant=speaking_time,
            interventions_log=[],
            session_started_at=session_started_at,
            current_turn_started_at=None,
        )


def _redis_key(session_id: int | str) -> str:
    return REDIS_KEY_TEMPLATE.format(session_id=session_id)


def last_intervention_for_reason(
    state: ModerationState, reason: str
) -> Optional[dict]:
    """
    Scansiona interventions_log all'indietro e ritorna la prima entry
    con reason matching, oppure None. Le entry hanno campo `ts` ISO string.
    """
    for entry in reversed(state.interventions_log):
        if entry.get("reason") == reason:
            return entry
    return None


def _fetch_session_meta(
    session_id: int | str,
) -> Tuple[list[str], Optional[datetime]]:
    """
    Legge dalla DB sessione e partecipanti. Ritorna (names, started_at).
    Usa apps.accounts.utils.display_name_for_user per il naming dei
    partecipanti (first_name → username). Fallback graceful a ([], None)
    se l'accesso fallisce.
    """
    try:
        from apps.sessions.models import Session, SessionParticipant
        from apps.accounts.utils import display_name_for_user

        session = Session.objects.only("started_at").get(id=session_id)
        participants = SessionParticipant.objects.filter(
            session_id=session_id
        ).select_related("user")
        names = [display_name_for_user(p.user) for p in participants]
        # Django ORM ritorna datetime tz-aware (USE_TZ=True). Tutti gli
        # altri timestamp moderation sono naive (datetime.utcnow). Strippa
        # la tz per coerenza ed evitare TypeError in sottrazioni.
        started_at = session.started_at
        if started_at is not None and started_at.tzinfo is not None:
            started_at = started_at.replace(tzinfo=None)
        return names, started_at
    except Exception:
        return [], None


def load_moderation_state(session_id: int | str) -> ModerationState:
    """
    Carica lo stato di moderazione da Redis.
    Se non esiste, crea uno stato iniziale con speaking_time_per_participant
    popolato con tutti i partecipanti della sessione a 0 (lookup DB) e
    session_started_at impostato dal Session model.
    """
    key = _redis_key(session_id)
    data = cache.get(key)

    if not data:
        names, started_at = _fetch_session_meta(session_id)
        state = ModerationState.initial(
            participants=names, session_started_at=started_at
        )
        save_moderation_state(session_id, state)
        return state

    return ModerationState(
        summary=data.get("summary", DEFAULT_SUMMARY),
        ai_interventions_count=data.get("ai_interventions_count", 0),
        last_ai_intervention_at=data.get("last_ai_intervention_at"),
        conclusion_reason=data.get("conclusion_reason"),
        forced_conclusion_done=data.get("forced_conclusion_done", False),
        speaking_time_per_participant=data.get(
            "speaking_time_per_participant", {}
        ),
        interventions_log=data.get("interventions_log", []),
        session_started_at=data.get("session_started_at"),
        current_turn_started_at=data.get("current_turn_started_at"),
    )


def save_moderation_state(session_id: int | str, state: ModerationState) -> None:
    """
    Salva lo stato di moderazione in Redis.
    """
    key = _redis_key(session_id)
    cache.set(
        key,
        {
            "summary": state.summary,
            "ai_interventions_count": state.ai_interventions_count,
            "last_ai_intervention_at": state.last_ai_intervention_at,
            "conclusion_reason": state.conclusion_reason,
            "forced_conclusion_done": state.forced_conclusion_done,
            "speaking_time_per_participant": state.speaking_time_per_participant,
            "interventions_log": state.interventions_log,
            "session_started_at": state.session_started_at,
            "current_turn_started_at": state.current_turn_started_at,
        },
        timeout=None,
    )
