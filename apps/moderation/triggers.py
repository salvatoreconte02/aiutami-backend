from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

from django.core.cache import cache

from .state import ModerationState
from .service import HardModerationAction, SUMMARY_TURNS_INTERVAL

# Import dominio turni per i trigger statici
from apps.turns.services import (
    TurnState,
    TURN_STATE_HUMAN_SPEAKING,
    TURN_STATE_AI_SPEAKING,
)

# Import stato timer moderazione
from .timers_state import (
    load_timers_state,
    save_timers_state,
    NO_PUSH_THRESHOLD,
    TIMER_25_THRESHOLD,
    TIMER_30_THRESHOLD,
    INACTIVE_USER_THRESHOLD,
)


@dataclass
class TriggerEvaluationResult:
    """
    Risultato della valutazione dei trigger di moderazione
    per una determinata sessione in una determinata finestra.
    """
    hard_action: HardModerationAction
    static_messages_to_speak: List[str]


def evaluate_triggers_on_human_turn_end(
    *,
    session_id: int | str,
    user_id: int | str,
    session_phase: str,            # es. "ACTIVE", "CONCLUSION"
    moderation_state: ModerationState,
) -> TriggerEvaluationResult:
    """
    Valuta tutti i trigger che hanno senso alla fine di un turno umano.

    - Deve essere chiamata DOPO che il turno umano è stato chiuso
      e PRIMA di chiamare il servizio LLM.

    - Non chiama l'LLM: decide solo hard_action e messaggi fissi.
    """
    hard_action = HardModerationAction.NONE
    static_messages: list[str] = []

    # 1) Trigger hard: riassunto ogni N turni umani (FORCED_SUMMARY)
    if _should_force_summary(moderation_state):
        hard_action = HardModerationAction.FORCED_SUMMARY

    # 2) Trigger hard: fase di conclusione (FORCED_CONCLUSION)
    if _should_force_conclusion(session_id=session_id, session_phase=session_phase):
        hard_action = HardModerationAction.FORCED_CONCLUSION

    # 3) Trigger meccanici legati allo stato corrente
    static_messages.extend(
        _collect_static_messages_for_current_state(
            session_id=session_id,
            user_id=user_id,
            session_phase=session_phase,
        )
    )

    return TriggerEvaluationResult(
        hard_action=hard_action,
        static_messages_to_speak=static_messages,
    )


def evaluate_time_based_triggers(
    *,
    session_id: int | str,
    session_phase: str,
) -> TriggerEvaluationResult:
    """
    Valuta i trigger puramente temporali (NO PUSH, UTENTE INATTIVO, TIMER SESSIONE)
    indipendentemente dalla fine di un turno umano.

    - NON deve far parlare il moderatore sopra qualcuno che sta parlando:
      se in questo momento c'è HUMAN_SPEAKING o AI_SPEAKING, non viene
      emesso alcun messaggio (sarà valutato al prossimo 'ping' quando
      la sessione sarà di nuovo libera).
    """
    static_messages: list[str] = []
    hard_action = HardModerationAction.NONE

    if _someone_is_currently_speaking(session_id=session_id):
        # Sessione "occupata": nessun messaggio ora, si riprova al prossimo ping.
        return TriggerEvaluationResult(
            hard_action=hard_action,
            static_messages_to_speak=[],
        )

    # Se nessuno sta parlando, è possibile emettere direttamente messaggi fissi.
    static_messages.extend(
        _collect_time_based_static_messages(session_id=session_id, session_phase=session_phase)
    )

    return TriggerEvaluationResult(
        hard_action=hard_action,
        static_messages_to_speak=static_messages,
    )


# ---------------------------------------------------------------------------
# Funzioni di supporto
# ---------------------------------------------------------------------------

def _should_force_summary(state: ModerationState) -> bool:
    """
    Determina se scatta il trigger hard di riassunto intermedio.
    Dal punto di vista del trigger, il controllo è banale:
    si usa il contatore dei turni umani dall'ultimo riassunto.
    """
    return state.human_turns_since_last_summary + 1 >= SUMMARY_TURNS_INTERVAL


def _should_force_conclusion(
    *,
    session_id: int | str,
    session_phase: str,
) -> bool:
    """
    Determina se scatta il trigger hard di conclusione.

    Condizione unica:
    - la sessione deve essere già in fase "CONCLUSION".
    """
    if session_phase != "CONCLUSION":
        return False

    # TODO: opzionale - verificare se la conclusione è già stata fatta,
    # per non ripetere più volte il riassunto finale.
    return True


def _collect_static_messages_for_current_state(
    *,
    session_id: int | str,
    user_id: int | str,
    session_phase: str,
) -> list[str]:
    """
    Raccoglie i messaggi fissi da pronunciare nella finestra post-turno.
    """
    messages: list[str] = []

    # 1) Prenotazione intervento: annunciare chi ha la priorità di parola
    reserved_speaker_name = _get_next_reserved_speaker_name(session_id=session_id)
    if reserved_speaker_name is not None:
        messages.append(
            f"Ora la parola va a {reserved_speaker_name}, che aveva prenotato."
        )

    # 2) Pronti alla conclusione: annunciare quanti sono pronti (in fase ACTIVE)
    ready_count, total_count = _get_ready_to_conclude_status(session_id=session_id)
    if session_phase == "ACTIVE" and total_count > 0 and 0 < ready_count < total_count:
        messages.append(
            f"{ready_count} partecipanti su {total_count} sono pronti a concludere."
        )

    return messages


def _get_next_reserved_speaker_name(
    *,
    session_id: int | str,
) -> Optional[str]:
    """
    Restituisce il nome (display name) del prossimo utente che ha una prenotazione
    attiva per parlare nella sessione indicata, se esiste.
    """
    # Import lazy del modello utente
    from django.contrib.auth import get_user_model

    key = f"turns:{session_id}"
    stored = cache.get(key)

    if not isinstance(stored, TurnState):
        return None

    user_id = stored.reservation_user_id
    if not user_id:
        return None

    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return None

    display_name = getattr(user, "display_name", None) or user.get_username()
    return display_name


def _get_ready_to_conclude_status(
    *,
    session_id: int | str,
) -> tuple[int, int]:
    """
    Restituisce (ready_count, total_count) per la sessione indicata:
    - ready_count: quanti partecipanti hanno premuto "pronto alla conclusione";
    - total_count: quanti partecipanti totali ha la sessione.
    """
    # Import locale per evitare AppRegistryNotReady
    from apps.sessions.models import SessionParticipant

    qs = SessionParticipant.objects.filter(session_id=session_id)
    total_count = qs.count()
    ready_count = qs.filter(ready_to_conclude=True).count()
    return ready_count, total_count


def _someone_is_currently_speaking(session_id: int | str) -> bool:
    """
    Verifica, tramite lo stato dei turni, se c'è un HUMAN_SPEAKING o AI_SPEAKING attivo.
    """
    key = f"turns:{session_id}"
    stored = cache.get(key)

    if not isinstance(stored, TurnState):
        return False

    return stored.state in (TURN_STATE_HUMAN_SPEAKING, TURN_STATE_AI_SPEAKING)


def _collect_time_based_static_messages(
    *,
    session_id: int | str,
    session_phase: str,
) -> list[str]:
    """
    Raccoglie i messaggi fissi da generare in base ai soli controlli a tempo,
    nel caso in cui la sessione sia libera (nessuno sta parlando).
    """
    # Import locali per evitare problemi in fase di bootstrap
    from apps.sessions.models import SessionParticipant, SessionState as SessionStateEnum

    messages: list[str] = []
    state = load_timers_state(session_id)
    now = datetime.utcnow()

    # 1) NO PUSH (silenzio prolungato nella sessione)
    if state.last_any_activity_at is not None and not state.no_push_notified:
        if now - state.last_any_activity_at >= NO_PUSH_THRESHOLD:
            messages.append(
                "Se qualcuno vuole intervenire, può parlare ora o condividere una breve considerazione."
            )
            state.no_push_notified = True

    # 2) TIMER 25'/30' – solo in fase ACTIVE
    if session_phase == SessionStateEnum.ACTIVE and state.session_started_at is not None:
        elapsed = now - state.session_started_at

        if (not state.timer_25_notified) and elapsed >= TIMER_25_THRESHOLD:
            messages.append("Mancano circa cinque minuti alla fine della discussione.")
            state.timer_25_notified = True

        if (not state.timer_30_notified) and elapsed >= TIMER_30_THRESHOLD:
            messages.append(
                "Il tempo della discussione è terminato. Potete avviarvi verso la conclusione."
            )
            state.timer_30_notified = True

    # 3) UTENTE INATTIVO
    if session_phase == SessionStateEnum.ACTIVE:
        participants = (
            SessionParticipant.objects
            .filter(session_id=session_id)
            .select_related("user")
        )

        for p in participants:
            user_id_str = str(p.user_id)

            if user_id_str in state.inactive_notified_user_ids:
                continue

            last_spoke = state.last_user_speak_at.get(user_id_str)

            # Mai parlato, oppure troppo tempo senza parlare
            if last_spoke is None or (now - last_spoke) >= INACTIVE_USER_THRESHOLD:
                display_name = getattr(p.user, "display_name", None) or p.user.get_username()
                messages.append(
                    f"{display_name}, se vuoi condividere un'idea, questo è un buon momento per intervenire."
                )
                state.inactive_notified_user_ids.append(user_id_str)
                # Per l'MVP si notifica al massimo un utente per ping
                break

    # Salvataggio stato timer aggiornato
    save_timers_state(session_id, state)

    return messages