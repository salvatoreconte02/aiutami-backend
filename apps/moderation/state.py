

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
    human_turns_since_last_summary: int
    ai_interventions_count: int
    last_ai_intervention_at: Optional[datetime]
    conclusion_reason: Optional[str]  # "timer_expired" or "all_participants_ready"
    forced_conclusion_done: bool  # True dopo il primo FORCED_CONCLUSION
    turns_per_participant: dict[str, int]  # {"speaker_name": count}
    interventions_log: list[dict]  # log di ogni intervento AI normal mode

    @classmethod
    def initial(cls) -> "ModerationState":
        return cls(
            summary=DEFAULT_SUMMARY,
            human_turns_since_last_summary=0,
            ai_interventions_count=0,
            last_ai_intervention_at=None,
            conclusion_reason=None,
            forced_conclusion_done=False,
            turns_per_participant={},
            interventions_log=[],
        )


def _redis_key(session_id: int | str) -> str:
    return REDIS_KEY_TEMPLATE.format(session_id=session_id)


def load_moderation_state(session_id: int | str) -> ModerationState:
    """
    Carica lo stato di moderazione da Redis.
    Se non esiste, crea e persiste uno stato iniziale.
    """
    key = _redis_key(session_id)
    data = cache.get(key)

    if not data:
        state = ModerationState.initial()
        save_moderation_state(session_id, state)
        return state

    return ModerationState(
        summary=data.get("summary", DEFAULT_SUMMARY),
        human_turns_since_last_summary=data.get(
            "human_turns_since_last_summary", 0
        ),
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
            "human_turns_since_last_summary": state.human_turns_since_last_summary,
            "ai_interventions_count": state.ai_interventions_count,
            "last_ai_intervention_at": state.last_ai_intervention_at,
            "conclusion_reason": state.conclusion_reason,
            "forced_conclusion_done": state.forced_conclusion_done,
            "turns_per_participant": state.turns_per_participant,
            "interventions_log": state.interventions_log,
        },
        timeout=None,
    )