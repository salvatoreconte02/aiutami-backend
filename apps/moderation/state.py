

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

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
    turns_per_participant: dict[str, int]  # {"speaker_name": count}
    interventions_log: list[dict]  # log di ogni intervento AI normal mode

    @classmethod
    def initial(
        cls, participants: Optional[list[str]] = None
    ) -> "ModerationState":
        turns = {name: 0 for name in participants} if participants else {}
        return cls(
            summary=DEFAULT_SUMMARY,
            ai_interventions_count=0,
            last_ai_intervention_at=None,
            conclusion_reason=None,
            forced_conclusion_done=False,
            turns_per_participant=turns,
            interventions_log=[],
        )


def _redis_key(session_id: int | str) -> str:
    return REDIS_KEY_TEMPLATE.format(session_id=session_id)


def _fetch_participant_names(session_id: int | str) -> list[str]:
    """
    Legge dalla tabella session_participant i nomi dei partecipanti della
    sessione, usando la stessa logica del turn consumer (display_name se
    presente, altrimenti username). Ritorna lista vuota se la sessione
    non esiste o l'accesso DB fallisce.
    """
    try:
        from apps.sessions.models import SessionParticipant

        participants = SessionParticipant.objects.filter(
            session_id=session_id
        ).select_related("user")
        return [
            getattr(p.user, "display_name", None) or p.user.get_username()
            for p in participants
        ]
    except Exception:
        return []


def load_moderation_state(session_id: int | str) -> ModerationState:
    """
    Carica lo stato di moderazione da Redis.
    Se non esiste, crea uno stato iniziale con turns_per_participant
    popolato con tutti i partecipanti della sessione a 0 (lookup DB).
    """
    key = _redis_key(session_id)
    data = cache.get(key)

    if not data:
        participants = _fetch_participant_names(session_id)
        state = ModerationState.initial(participants=participants)
        save_moderation_state(session_id, state)
        return state

    return ModerationState(
        summary=data.get("summary", DEFAULT_SUMMARY),
        ai_interventions_count=data.get("ai_interventions_count", 0),
        last_ai_intervention_at=data.get("last_ai_intervention_at"),
        conclusion_reason=data.get("conclusion_reason"),
        forced_conclusion_done=data.get("forced_conclusion_done", False),
        turns_per_participant=data.get("turns_per_participant", {}),
        interventions_log=data.get("interventions_log", []),
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
            "turns_per_participant": state.turns_per_participant,
            "interventions_log": state.interventions_log,
        },
        timeout=None,
    )