from dataclasses import dataclass
from typing import List, Optional

from .state import load_moderation_state
from .service import (
    ModerationService,
    ModerationResult,
    HardModerationAction,
)
from .triggers import (
    evaluate_triggers_on_human_turn_end,
    TriggerEvaluationResult,
    StaticMessage,
)


@dataclass
class FullModerationDecision:
    """
    Risultato completo della moderazione alla fine di un turno umano.

    Contiene:
    - static_messages_to_speak: lista di StaticMessage (con flag use_tts)
    - ai_should_speak: se il moderatore AI deve parlare
    - ai_message: contenuto eventuale del messaggio AI
    - hard_action: NONE / FORCED_CONCLUSION
    - should_transition_to_conclusion: se la sessione deve passare a CONCLUSION
    """
    static_messages_to_speak: List[StaticMessage]
    ai_should_speak: bool
    ai_message: Optional[str]
    hard_action: HardModerationAction
    should_transition_to_conclusion: bool = False


class ModerationOrchestrator:
    """
    Punto di ingresso unico per la moderazione alla fine di un turno umano.

    Sequenza gestita:
      1. Carica lo stato corrente di moderazione
      2. Valuta i trigger post–turno (hard + statici)
      3. Chiama ModerationService per la parte LLM
      4. Restituisce una FullModerationDecision
    """

    @classmethod
    def handle_human_turn_end(
        cls,
        *,
        session_id: int | str,
        user_id: int | str,
        last_turn_text: str,
        session_phase: str,          # es. "ACTIVE", "CONCLUSION"
        speaker_name: Optional[str] = None,
    ) -> FullModerationDecision:
        """
        Deve essere chiamato subito dopo che un turno umano è
        terminato, durante la finestra di moderazione (microfoni chiusi).
        """
        # Risolvi task_key dalla sessione per propagarlo ai servizi LLM
        task_key = None
        try:
            from apps.sessions.models import Session
            task_key = Session.objects.values_list("context", flat=True).get(id=session_id)
        except Exception:
            pass  # Nei test unitari la sessione potrebbe non esistere nel DB

        # 1) Carica stato moderazione
        moderation_state = load_moderation_state(session_id)

        # 2) Trigger post-turno (hard action + messaggi statici)
        trigger_result: TriggerEvaluationResult = evaluate_triggers_on_human_turn_end(
            session_id=session_id,
            user_id=user_id,
            session_phase=session_phase,
            moderation_state=moderation_state,
        )

        # 3) Chiama ModerationService per la parte LLM
        moderation_result: ModerationResult = ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=user_id,
            last_turn_text=last_turn_text,
            session_phase=session_phase,
            hard_action=trigger_result.hard_action,
            speaker_name=speaker_name,
            task_key=task_key,
        )

        return FullModerationDecision(
            static_messages_to_speak=trigger_result.static_messages_to_speak,
            ai_should_speak=moderation_result.ai_should_speak,
            ai_message=moderation_result.ai_message,
            hard_action=trigger_result.hard_action,
            should_transition_to_conclusion=trigger_result.should_transition_to_conclusion,
        )