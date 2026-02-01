# apps/moderation/orchestrator.py

from dataclasses import dataclass
from typing import List, Optional

from .state import load_moderation_state, save_moderation_state, ModerationState
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
    - hard_action: NONE / FORCED_SUMMARY / FORCED_CONCLUSION
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

        # 1) Carica stato moderazione
        moderation_state = load_moderation_state(session_id)

        # 2) Trigger post-turno (hard action + messaggi statici)
        trigger_result: TriggerEvaluationResult = evaluate_triggers_on_human_turn_end(
            session_id=session_id,
            user_id=user_id,
            session_phase=session_phase,
            moderation_state=moderation_state,
        )

        # 3) Biforcazione in base al hard_action
        if trigger_result.hard_action == HardModerationAction.FORCED_SUMMARY:
            # FORCED_SUMMARY: usa metodo dedicato
            return cls._handle_forced_summary(
                session_id=session_id,
                last_turn_text=last_turn_text,
                speaker_name=speaker_name,
                moderation_state=moderation_state,
                trigger_result=trigger_result,
            )
        else:
            # Normal path: chiama handle_human_turn_ended
            moderation_result: ModerationResult = ModerationService.handle_human_turn_ended(
                session_id=session_id,
                user_id=user_id,
                last_turn_text=last_turn_text,
                session_phase=session_phase,
                hard_action=trigger_result.hard_action,
                speaker_name=speaker_name,
            )

            return FullModerationDecision(
                static_messages_to_speak=trigger_result.static_messages_to_speak,
                ai_should_speak=moderation_result.ai_should_speak,
                ai_message=moderation_result.ai_message,
                hard_action=trigger_result.hard_action,
                should_transition_to_conclusion=trigger_result.should_transition_to_conclusion,
            )

    @classmethod
    def _handle_forced_summary(
        cls,
        *,
        session_id: int | str,
        last_turn_text: str,
        speaker_name: Optional[str],
        moderation_state: ModerationState,
        trigger_result: TriggerEvaluationResult,
    ) -> FullModerationDecision:
        """
        Gestisce il path FORCED_SUMMARY separatamente.

        1. Incrementa turns_per_participant per lo speaker
        2. Chiama call_llm_for_summary
        3. Aggiorna summary
        4. Reset human_turns_since_last_summary a 0
        5. Salva stato
        """
        # Increment turn counter for the speaker
        if speaker_name:
            moderation_state.turns_per_participant[speaker_name] = (
                moderation_state.turns_per_participant.get(speaker_name, 0) + 1
            )

        # Calculate total turns
        total_turns = sum(moderation_state.turns_per_participant.values())

        # Call dedicated LLM
        llm_result = ModerationService.call_llm_for_summary(
            summary_in=moderation_state.summary,
            last_turn_text=last_turn_text,
            last_turn_speaker=speaker_name,
            participants_turns=moderation_state.turns_per_participant,
            total_turns=total_turns,
        )

        # Update state
        moderation_state.summary = llm_result["updated_summary"]
        moderation_state.human_turns_since_last_summary = 0  # Reset counter

        # Save state
        save_moderation_state(session_id, moderation_state)

        return FullModerationDecision(
            static_messages_to_speak=trigger_result.static_messages_to_speak,
            ai_should_speak=True,  # FORCED_SUMMARY always speaks
            ai_message=llm_result["message_to_say"],
            hard_action=HardModerationAction.FORCED_SUMMARY,
            should_transition_to_conclusion=trigger_result.should_transition_to_conclusion,
        )