from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime
import random

from django.core.cache import cache

from .state import ModerationState
from .service import HardModerationAction, SUMMARY_TURNS_INTERVAL


NO_PUSH_MESSAGES = [
    "Se qualcuno vuole intervenire, può parlare ora o condividere una breve considerazione.",
    "C'è un momento di silenzio. Se qualcuno ha un pensiero da condividere, questo è un buon momento.",
    "Se qualcuno desidera aggiungere qualcosa alla discussione, può prendere la parola.",
    "La discussione è in pausa. Chi vuole intervenire può farlo ora.",
]

READY_TO_CONCLUDE_MESSAGES = [
    "{nome} è pronto a concludere. Se hai capito con certezza di chi si tratta, premi anche tu 'pronto alla conclusione' per terminare la sessione.",
    "{nome} ha indicato di essere pronto alla conclusione. Quando anche tu avrai raggiunto una certezza, premi il pulsante per concludere.",
    "{nome} si è dichiarato pronto a concludere. Se hai già individuato il colpevole, puoi premere 'pronto alla conclusione'.",
    "{nome} è pronto. Ricorda: quando sei sicuro di chi si tratta, premi 'pronto alla conclusione' per avviare la fase finale.",
]

READY_TO_CONCLUDE_LAST_ONE_MESSAGES = [
    "{nome} è pronto a concludere. Ora manca solo un partecipante per avviare la fase finale.",
    "{nome} si è dichiarato pronto. Manca solo una persona: se hai raggiunto una certezza, premi 'pronto alla conclusione'.",
    "{nome} è pronto. Quasi tutti hanno deciso: manca solo un voto per concludere la sessione.",
]

READY_TO_CONCLUDE_ALL_READY_MESSAGES = [
    "Tutti i partecipanti sono pronti. Possiamo avviarci alla fase di conclusione.",
    "Tutti hanno deciso. Possiamo avviarci alla fase di conclusione.",
    "Siete tutti pronti. Possiamo avviarci alla fase di conclusione.",
]

# Varianti messaggio per trigger INACTIVE_USER (Livello 2: voce, 10 min)
INACTIVE_VOICE_MESSAGES = [
    "{nome}, se vuoi condividere un'idea, questo è un buon momento per intervenire.",
    "{nome}, non ti abbiamo ancora sentito. Se hai qualcosa da aggiungere, puoi parlare ora.",
    "{nome}, c'è qualcosa che vorresti condividere con il gruppo?",
    "{nome}, se hai un pensiero sulla discussione, sentiti libero di intervenire.",
]

# Messaggio per INACTIVE_USER Livello 1: notifica testuale privata (5 min)
INACTIVE_TEXT_MESSAGE ="Non intervieni da un po'. Se vuoi condividere qualcosa, questo è un buon momento."


@dataclass
class StaticMessage:
    """Messaggio statico da pronunciare/mostrare."""
    text: str
    use_tts: bool = True  # True = TTS audio, False = solo testo WebSocket
    trigger_type: Optional[str] = None  # Tipo trigger per identificazione frontend (es. TIMER_25)
    target_user_id: Optional[int] = None  # Per messaggi privati: ID utente destinatario
    target_user_name: Optional[str] = None  # Per messaggi privati: nome utente per display


@dataclass
class ReadyToConcludeResult:
    """Risultato della generazione del messaggio ready_to_conclude."""
    message: StaticMessage
    trigger_conclusion: bool  # Se True, dopo il TTS si transiziona a CONCLUSION


def generate_ready_to_conclude_message(
    user_name: str,
    ready_count: int,
    total_count: int,
) -> ReadyToConcludeResult:
    """
    Genera il messaggio per quando un utente clicca 'pronto a concludere'.

    Args:
        user_name: Nome dell'utente che ha cliccato
        ready_count: Numero di utenti già pronti (incluso questo)
        total_count: Numero totale di partecipanti

    Returns:
        ReadyToConcludeResult con messaggio e flag trigger_conclusion
    """
    trigger_conclusion = False

    # Caso "tutti pronti": ready_count == total_count
    if ready_count == total_count:
        template = random.choice(READY_TO_CONCLUDE_ALL_READY_MESSAGES)
        text = template
        trigger_conclusion = True
    # Caso "manca solo uno": ready_count == total_count - 1
    elif ready_count == total_count - 1:
        template = random.choice(READY_TO_CONCLUDE_LAST_ONE_MESSAGES)
        text = template.format(nome=user_name)
    else:
        template = random.choice(READY_TO_CONCLUDE_MESSAGES)
        text = template.format(nome=user_name)

    return ReadyToConcludeResult(
        message=StaticMessage(text=text, use_tts=True),
        trigger_conclusion=trigger_conclusion,
    )


# Import dominio turni per i trigger statici
from apps.turns.services import (
    TurnState,
    TURN_STATE_HUMAN_SPEAKING,
    TURN_STATE_AI_SPEAKING,
    TURN_STATE_AI_INTRODUCING,
)

# Import stato timer moderazione
from .timers_state import (
    load_timers_state,
    save_timers_state,
    NO_PUSH_THRESHOLD,
    TIMER_25_THRESHOLD,
    TIMER_30_THRESHOLD,
    INACTIVE_USER_THRESHOLD,
    INACTIVE_TEXT_THRESHOLD,
    MAX_VOICE_SOLICITS_PER_USER,
)


@dataclass
class TriggerEvaluationResult:
    """
    Risultato della valutazione dei trigger di moderazione
    per una determinata sessione in una determinata finestra.
    """
    hard_action: HardModerationAction
    static_messages_to_speak: List[StaticMessage]
    should_transition_to_conclusion: bool = False  # segnala cambio fase a CONCLUSION


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
    from datetime import datetime  # import locale per evitare circular

    hard_action = HardModerationAction.NONE
    static_messages: list[StaticMessage] = []
    should_transition_to_conclusion = False

    # 1) Trigger hard: riassunto ogni N turni umani (FORCED_SUMMARY)
    if _should_force_summary(moderation_state):
        hard_action = HardModerationAction.FORCED_SUMMARY

    # NOTE: Trigger FORCED_CONCLUSION rimosso - ora eseguito immediatamente alla
    # transizione di sessione via _execute_forced_conclusion() in ws_consumer.py

    # 2) Trigger meccanici legati allo stato corrente
    static_messages.extend(
        _collect_static_messages_for_current_state(
            session_id=session_id,
            user_id=user_id,
            session_phase=session_phase,
        )
    )

    # 4) Controllo timer 30 min (solo in fase ACTIVE)
    if session_phase == "ACTIVE":
        timers_state = load_timers_state(session_id)
        if timers_state.session_started_at is not None:
            elapsed = datetime.utcnow() - timers_state.session_started_at
            if elapsed >= TIMER_30_THRESHOLD:
                # Aggiungi messaggio solo se non già notificato (TTS)
                if not timers_state.timer_30_notified:
                    static_messages.append(StaticMessage(
                        text="Il tempo della discussione è terminato. "
                             "Potete avviarvi verso la conclusione.",
                        use_tts=True,
                    ))
                    timers_state.timer_30_notified = True
                    save_timers_state(session_id, timers_state)

                # Segnala il cambio di fase (sempre, anche se già notificato)
                should_transition_to_conclusion = True

    return TriggerEvaluationResult(
        hard_action=hard_action,
        static_messages_to_speak=static_messages,
        should_transition_to_conclusion=should_transition_to_conclusion,
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
    hard_action = HardModerationAction.NONE

    if _someone_is_currently_speaking(session_id=session_id):
        # Sessione "occupata": nessun messaggio ora, si riprova al prossimo ping.
        return TriggerEvaluationResult(
            hard_action=hard_action,
            static_messages_to_speak=[],
            should_transition_to_conclusion=False,
        )

    # Se nessuno sta parlando, è possibile emettere direttamente messaggi fissi.
    static_messages, should_transition = _collect_time_based_static_messages(
        session_id=session_id,
        session_phase=session_phase,
    )

    return TriggerEvaluationResult(
        hard_action=hard_action,
        static_messages_to_speak=static_messages,
        should_transition_to_conclusion=should_transition,
    )


def _should_force_summary(state: ModerationState) -> bool:
    """
    Determina se scatta il trigger hard di riassunto intermedio.
    Dal punto di vista del trigger, il controllo è banale:
    si usa il contatore dei turni umani dall'ultimo riassunto.
    """
    return state.human_turns_since_last_summary + 1 >= SUMMARY_TURNS_INTERVAL


def _collect_static_messages_for_current_state(
    *,
    session_id: int | str,
    user_id: int | str,
    session_phase: str,
) -> list[StaticMessage]:
    """
    Raccoglie i messaggi fissi da pronunciare nella finestra post-turno.
    """
    messages: list[StaticMessage] = []

    # 1) Prenotazione intervento: annunciare chi ha la priorità di parola (SOLO TESTO)
    reserved_speaker_name = _get_next_reserved_speaker_name(session_id=session_id)
    if reserved_speaker_name is not None:
        messages.append(StaticMessage(
            text=f"Ora la parola va a {reserved_speaker_name}, che aveva prenotato.",
            use_tts=False,  # Solo testo, no TTS
        ))

    # NOTE: Il trigger "pronti alla conclusione" è stato spostato in SessionReadyToConcludeView
    # per scattare al click del bottone invece che a fine turno.

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
    Verifica, tramite lo stato dei turni, se c'è un HUMAN_SPEAKING, AI_SPEAKING o AI_INTRODUCING attivo.
    """
    key = f"turns:{session_id}"
    stored = cache.get(key)

    if not isinstance(stored, TurnState):
        return False

    return stored.state in (TURN_STATE_HUMAN_SPEAKING, TURN_STATE_AI_SPEAKING, TURN_STATE_AI_INTRODUCING)


def _collect_time_based_static_messages(
    *,
    session_id: int | str,
    session_phase: str,
) -> tuple[list[StaticMessage], bool]:
    """
    Raccoglie i messaggi fissi da generare in base ai soli controlli a tempo,
    nel caso in cui la sessione sia libera (nessuno sta parlando).

    Returns:
        Tuple of (messages, should_transition_to_conclusion)
    """
    # Import locali per evitare problemi in fase di bootstrap
    from apps.sessions.models import SessionParticipant, SessionState as SessionStateEnum

    messages: list[StaticMessage] = []
    should_transition_to_conclusion = False
    state = load_timers_state(session_id)
    now = datetime.utcnow()

    # 1) NO PUSH (silenzio prolungato nella sessione) - TTS, solo in fase ACTIVE
    if session_phase == SessionStateEnum.ACTIVE:
        if state.last_any_activity_at is not None and not state.no_push_notified:
            if now - state.last_any_activity_at >= NO_PUSH_THRESHOLD:
                messages.append(StaticMessage(
                    text=random.choice(NO_PUSH_MESSAGES),
                    use_tts=True,
                ))
                state.no_push_notified = True

    # 2) TIMER 25'/30' – solo in fase ACTIVE
    if session_phase == SessionStateEnum.ACTIVE and state.session_started_at is not None:
        elapsed = now - state.session_started_at

        # TIMER 25 - Solo testo (non interrompente)
        if (not state.timer_25_notified) and elapsed >= TIMER_25_THRESHOLD:
            messages.append(StaticMessage(
                text="Mancano circa cinque minuti alla fine della discussione.",
                use_tts=False,  # Solo testo
                trigger_type="TIMER_25",  # Per frontend: avvia timer visivo
            ))
            state.timer_25_notified = True

        # TIMER 30 - TTS (annuncio importante) + transizione
        if (not state.timer_30_notified) and elapsed >= TIMER_30_THRESHOLD:
            messages.append(StaticMessage(
                text="Il tempo della discussione è terminato. Potete avviarvi verso la conclusione.",
                use_tts=True,
            ))
            state.timer_30_notified = True

        # Segnala il cambio di fase (sempre, anche se già notificato)
        if elapsed >= TIMER_30_THRESHOLD:
            should_transition_to_conclusion = True

    # 3) UTENTE INATTIVO - Due livelli di notifica
    if session_phase == SessionStateEnum.ACTIVE and state.session_started_at is not None:
        participants = (
            SessionParticipant.objects
            .filter(session_id=session_id)
            .select_related("user")
        )

        for p in participants:
            user_id_str = str(p.user_id)

            # Tempo di riferimento per Livello 1 (testo):
            # ultimo text solicit > ultimo voice solicit > ultimo turno > inizio sessione
            last_text_solicit = state.last_text_solicit_at.get(user_id_str)
            last_voice_solicit = state.last_voice_solicit_at.get(user_id_str)
            last_spoke = state.last_user_speak_at.get(user_id_str)

            if last_text_solicit is not None:
                reference_time_text = last_text_solicit
            elif last_voice_solicit is not None:
                reference_time_text = last_voice_solicit
            elif last_spoke is not None:
                reference_time_text = last_spoke
            else:
                reference_time_text = state.session_started_at

            if reference_time_text is None:
                continue

            elapsed_text = now - reference_time_text

            # Livello 1: Avviso testuale privato (5 min, ma non oltre 10 min)
            if INACTIVE_TEXT_THRESHOLD <= elapsed_text < INACTIVE_USER_THRESHOLD:
                display_name = getattr(p.user, "display_name", None) or p.user.get_username()
                messages.append(StaticMessage(
                    text=INACTIVE_TEXT_MESSAGE,
                    use_tts=False,
                    trigger_type="INACTIVE_USER_TEXT",
                    target_user_id=p.user_id,
                    target_user_name=display_name,
                ))
                state.last_text_solicit_at[user_id_str] = now
                # Un solo utente per ciclo
                break

            # Livello 2: Sollecito vocale pubblico (10 min, max 2 per utente)
            # Tempo di riferimento per Livello 2 (voce):
            # ultimo voice solicit > ultimo turno > inizio sessione
            if last_voice_solicit is not None:
                reference_time_voice = last_voice_solicit
            elif last_spoke is not None:
                reference_time_voice = last_spoke
            else:
                reference_time_voice = state.session_started_at

            if reference_time_voice is None:
                continue

            elapsed_voice = now - reference_time_voice

            # Controlla limite solleciti vocali
            voice_count = state.voice_solicits_count.get(user_id_str, 0)
            if voice_count >= MAX_VOICE_SOLICITS_PER_USER:
                continue

            if elapsed_voice >= INACTIVE_USER_THRESHOLD:
                display_name = getattr(p.user, "display_name", None) or p.user.get_username()
                messages.append(StaticMessage(
                    text=random.choice(INACTIVE_VOICE_MESSAGES).format(nome=display_name),
                    use_tts=True,
                    trigger_type="INACTIVE_USER_VOICE",
                    target_user_id=p.user_id,
                    target_user_name=display_name,
                ))
                # Aggiorna contatore e timestamp
                state.voice_solicits_count[user_id_str] = voice_count + 1
                state.last_voice_solicit_at[user_id_str] = now
                # Un solo utente per ciclo
                break

    # Salvataggio stato timer aggiornato
    save_timers_state(session_id, state)

    return messages, should_transition_to_conclusion