from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from django.core.cache import cache
from django.utils import timezone


# -------------------------------------------------------------------
#  Costanti di dominio (stati turno)
# -------------------------------------------------------------------

TURN_STATE_IDLE = "IDLE"
TURN_STATE_HUMAN_SPEAKING = "HUMAN_SPEAKING"
TURN_STATE_AI_SPEAKING = "AI_SPEAKING"
TURN_STATE_AI_INTRODUCING = "AI_INTRODUCING"

# Durata (concettuale) della finestra di priorità, in secondi
PRIORITY_WINDOW_SECONDS = 8


# -------------------------------------------------------------------
#  Modelli interni (non legati a Django REST o WebSocket)
# -------------------------------------------------------------------

@dataclass
class TurnState:
    """
    Stato logico dei turni per una sessione.
    """
    state: str = TURN_STATE_IDLE
    current_speaker_user_id: Optional[int] = None
    reservation_user_id: Optional[int] = None
    reservation_expires_at: Optional[datetime] = None

    # Flag di servizio: indica che il backend è in fase di moderazione
    # (valutazione trigger + eventuale intervento AI) e che quindi
    # non si accettano nuovi turni umani.
    moderation_in_progress: bool = False

    version: int = 1

    def to_dict(self) -> Dict[str, Any]:
        """
        Rappresentazione serializzabile per gli strati superiori (es. WebSocket).
        """
        return {
            "state": self.state,
            "current_speaker_user_id": self.current_speaker_user_id,
            "reservation_user_id": self.reservation_user_id,
            "reservation_expires_at": (
                self.reservation_expires_at.isoformat()
                if self.reservation_expires_at
                else None
            ),
            "moderation_in_progress": self.moderation_in_progress,
            "version": self.version,
        }


@dataclass
class TurnEvent:
    """
    Evento logico generato da una chiamata a TurnManager.

    Esempi di type:
      - "HUMAN_STARTED"
      - "HUMAN_ENDED"
      - "RESERVATION_SET"
      - "RESERVATION_EXPIRED"
      - "AI_STARTED"
      - "AI_ENDED"

    Sarà poi tradotto in messaggi WebSocket nel consumer.
    """
    type: str
    payload: Dict[str, Any]


@dataclass
class TurnResult:
    """
    Esito di una chiamata a TurnManager.

    success = True  -> operazione accettata, stato aggiornato.
    success = False -> operazione rifiutata; state contiene comunque lo stato attuale.
    """
    success: bool
    state: TurnState
    events: List[TurnEvent]
    error_code: Optional[str] = None
    error_detail: Optional[str] = None

    def to_state_dict(self) -> Dict[str, Any]:
        """
        Rappresentazione comoda per livelli superiori (es. WS),
        che combina lo stato con eventuali informazioni di errore.
        """
        data = self.state.to_dict()
        data["success"] = self.success
        if self.error_code is not None:
            data["error_code"] = self.error_code
            data["error_detail"] = self.error_detail
        return data


# -------------------------------------------------------------------
#  TurnManager
# -------------------------------------------------------------------

class TurnManager:
    """
    Servizio applicativo responsabile della gestione dei turni.

    Gli strati superiori (WebSocket consumer, eventuali viste REST) chiamano
    questi metodi passando session_id e user, e ricevono un TurnResult.
    """

    # ----------------------------
    #  Metodi pubblici principali
    # ----------------------------

    @classmethod
    def get_state(cls, session_id: str, user) -> TurnResult:
        """
        Ritorna lo stato corrente dei turni per una sessione,
        applicando se necessario la scadenza di una prenotazione.
        """
        state = cls._load_state(session_id)
        events: List[TurnEvent] = []

        expired_event = cls._expire_reservation_if_needed(state)
        if expired_event is not None:
            events.append(expired_event)
            cls._save_state(session_id, state)

        return TurnResult(success=True, state=state, events=events)

    @classmethod
    def get_state_only(cls, session_id: str) -> Optional[TurnState]:
        """
        Ritorna lo stato corrente dei turni senza wrappare in TurnResult.
        Usato per check veloci (es. in _trigger_loop).
        """
        return cls._load_state(session_id)

    @classmethod
    def request_speak(cls, session_id: str, user) -> TurnResult:
        """
        Richiesta di iniziare a parlare (toggle 'Parla').
        """
        state = cls._load_state(session_id)
        events: List[TurnEvent] = []

        # Se è in corso una fase di moderazione, non si accettano nuovi turni umani.
        if state.moderation_in_progress:
            return TurnResult(
                success=False,
                state=state,
                events=events,
                error_code="MODERATION_IN_PROGRESS",
                error_detail="È in corso una fase di moderazione: attendere che il moderatore termini.",
            )

        # Block turns during CONCLUSION phase
        session_phase = cls._get_session_phase(session_id)
        if session_phase == "CONCLUSION":
            return TurnResult(
                success=False,
                state=state,
                events=events,
                error_code="SESSION_IN_CONCLUSION",
                error_detail="La sessione è in fase di conclusione. Non è possibile prendere la parola.",
            )

        # Block turns during AI_INTRODUCING (intro in progress)
        if state.state == TURN_STATE_AI_INTRODUCING:
            return TurnResult(
                success=False,
                state=state,
                events=events,
                error_code="INTRO_IN_PROGRESS",
                error_detail="Il moderatore sta introducendo la sessione.",
            )

        expired_event = cls._expire_reservation_if_needed(state)
        if expired_event is not None:
            events.append(expired_event)
            cls._save_state(session_id, state)

        if state.state == TURN_STATE_AI_SPEAKING:
            return TurnResult(
                success=False,
                state=state,
                events=events,
                error_code="AI_SPEAKING",
                error_detail="Il moderatore AI sta parlando.",
            )

        if state.state == TURN_STATE_HUMAN_SPEAKING:
            return TurnResult(
                success=False,
                state=state,
                events=events,
                error_code="MIC_BUSY",
                error_detail="Il microfono è occupato da un altro partecipante.",
            )

        if state.state != TURN_STATE_IDLE:
            return TurnResult(
                success=False,
                state=state,
                events=events,
                error_code="INVALID_STATE",
                error_detail="Operazione non consentita nello stato corrente.",
            )

        if state.reservation_user_id is None:
            state.state = TURN_STATE_HUMAN_SPEAKING
            state.current_speaker_user_id = user.id
            state.version += 1

            human_started = TurnEvent(
                type="HUMAN_STARTED",
                payload={
                    "user_id": user.id,
                    "from_reservation": False,
                },
            )
            events.append(human_started)
            cls._save_state(session_id, state)
            return TurnResult(success=True, state=state, events=events)

        if state.reservation_user_id == user.id:
            state.state = TURN_STATE_HUMAN_SPEAKING
            state.current_speaker_user_id = user.id
            state.reservation_user_id = None
            state.reservation_expires_at = None
            state.version += 1

            human_started = TurnEvent(
                type="HUMAN_STARTED",
                payload={
                    "user_id": user.id,
                    "from_reservation": True,
                },
            )
            events.append(human_started)
            cls._save_state(session_id, state)
            return TurnResult(success=True, state=state, events=events)

        return TurnResult(
            success=False,
            state=state,
            events=events,
            error_code="PRIORITY_FOR_OTHER_USER",
            error_detail="Esiste una finestra di priorità per un altro partecipante.",
        )

    @classmethod
    def end_speak(cls, session_id: str, user) -> TurnResult:
        """
        Termine dell'intervento umano (toggle 'Termina').
        """
        state = cls._load_state(session_id)
        events: List[TurnEvent] = []

        if state.state != TURN_STATE_HUMAN_SPEAKING:
            return TurnResult(
                success=False,
                state=state,
                events=events,
                error_code="NO_HUMAN_SPEAKING",
                error_detail="Nessun partecipante umano sta parlando.",
            )

        if state.current_speaker_user_id != user.id:
            return TurnResult(
                success=False,
                state=state,
                events=events,
                error_code="NOT_CURRENT_SPEAKER",
                error_detail="Solo il partecipante attualmente in speaking può terminare.",
            )

        state.state = TURN_STATE_IDLE
        state.current_speaker_user_id = None
        state.version += 1

        human_ended = TurnEvent(
            type="HUMAN_ENDED",
            payload={
                "user_id": user.id,
            },
        )
        events.append(human_ended)

        # NOTA: Se c'è una prenotazione, NON apriamo subito la finestra di priorità.
        # La finestra verrà aperta SOLO da start_reservation_window() nel finally di
        # _handle_end_speak, DOPO che tutti i messaggi del moderatore sono stati
        # pronunciati. Questo evita che la finestra scada prematuramente.

        cls._save_state(session_id, state)
        return TurnResult(success=True, state=state, events=events)

    @classmethod
    def request_reserve(cls, session_id: str, user) -> TurnResult:
        """
        Richiesta di prenotazione (alzata di mano).
        """
        state = cls._load_state(session_id)
        events: List[TurnEvent] = []

        # 1) Check finestra di priorità attiva - ha precedenza su tutto
        #    Se c'è una finestra attiva, ritorna PRIORITY_FOR_OTHER_USER anche se state=IDLE
        now = timezone.now()
        if (state.reservation_user_id is not None
            and state.reservation_expires_at is not None
            and state.reservation_expires_at > now):
            return TurnResult(
                success=False,
                state=state,
                events=events,
                error_code="PRIORITY_FOR_OTHER_USER",
                error_detail="Esiste una finestra di priorità per un altro partecipante.",
            )

        # 2) Durante la moderazione non si impostano nuove prenotazioni,
        #    MA se il moderatore sta già parlando (AI_SPEAKING) allora si può prenotare.
        if state.moderation_in_progress and state.state != TURN_STATE_AI_SPEAKING:
            return TurnResult(
                success=False,
                state=state,
                events=events,
                error_code="MODERATION_IN_PROGRESS",
                error_detail="È in corso una fase di moderazione: attendere che il moderatore termini.",
            )

        # Block reservations during AI_INTRODUCING (intro in progress)
        if state.state == TURN_STATE_AI_INTRODUCING:
            return TurnResult(
                success=False,
                state=state,
                events=events,
                error_code="INTRO_IN_PROGRESS",
                error_detail="Il moderatore sta introducendo la sessione.",
            )

        # 3) Check stato - prenotazione consentita solo mentre qualcuno sta parlando
        if state.state not in (TURN_STATE_HUMAN_SPEAKING, TURN_STATE_AI_SPEAKING):
            return TurnResult(
                success=False,
                state=state,
                events=events,
                error_code="NOT_ALLOWED",
                error_detail="La prenotazione è consentita solo mentre qualcuno sta parlando.",
            )

        # 4) Check prenotazione esistente (senza finestra attiva)
        if state.reservation_user_id is not None:
            return TurnResult(
                success=False,
                state=state,
                events=events,
                error_code="ALREADY_RESERVED",
                error_detail="Esiste già un utente prenotato.",
            )

        if state.current_speaker_user_id == user.id:
            return TurnResult(
                success=False,
                state=state,
                events=events,
                error_code="CANNOT_RESERVE_WHILE_SPEAKING",
                error_detail="Lo speaker attuale non può prenotarsi.",
            )

        state.reservation_user_id = user.id
        state.reservation_expires_at = None

        events.append(
            TurnEvent(
                type="RESERVATION_SET",
                payload={"user_id": user.id},
            )
        )

        cls._save_state(session_id, state)
        return TurnResult(success=True, state=state, events=events)

    @classmethod
    def ai_start(cls, session_id: str) -> TurnResult:
        """
        Inizio intervento AI.
        """
        state = cls._load_state(session_id)
        events: List[TurnEvent] = []

        expired_event = cls._expire_reservation_if_needed(state)
        if expired_event is not None:
            events.append(expired_event)
            cls._save_state(session_id, state)

        if state.state != TURN_STATE_IDLE:
            return TurnResult(
                success=False,
                state=state,
                events=events,
                error_code="NOT_IDLE",
                error_detail="L'intervento AI è consentito solo quando nessuno sta parlando.",
            )

        # L'AI ha precedenza sulla prenotazione: la prenotazione rimane
        # salvata e la finestra di priorità si aprirà dopo che l'AI finisce.

        state.state = TURN_STATE_AI_SPEAKING
        state.current_speaker_user_id = None
        state.version += 1

        ai_started = TurnEvent(
            type="AI_STARTED",
            payload={},
        )
        events.append(ai_started)

        cls._save_state(session_id, state)
        return TurnResult(success=True, state=state, events=events)

    @classmethod
    def ai_end(cls, session_id: str) -> TurnResult:
        """
        Fine intervento AI.
        """
        state = cls._load_state(session_id)
        events: List[TurnEvent] = []

        if state.state != TURN_STATE_AI_SPEAKING:
            return TurnResult(
                success=False,
                state=state,
                events=events,
                error_code="AI_NOT_SPEAKING",
                error_detail="Non risulta alcun intervento AI in corso.",
            )

        state.state = TURN_STATE_IDLE
        state.current_speaker_user_id = None
        state.version += 1

        ai_ended = TurnEvent(
            type="AI_ENDED",
            payload={},
        )
        events.append(ai_ended)

        # NOTA: La finestra di prenotazione NON viene aperta qui.
        # Viene aperta solo da start_reservation_window() nel finally di _handle_end_speak,
        # DOPO che tutti i messaggi del moderatore sono stati pronunciati.

        cls._save_state(session_id, state)
        return TurnResult(success=True, state=state, events=events)

    # ----------------------------
    #  Metodi di supporto interni
    # ----------------------------

    @classmethod
    def _load_state(cls, session_id: str) -> TurnState:
        """
        Se non c'è nulla salvato, restituisce uno stato iniziale IDLE.
        """
        key = f"turns:{session_id}"
        stored = cache.get(key)

        if isinstance(stored, TurnState):
            return stored

        return TurnState()

    @classmethod
    def _save_state(cls, session_id: str, state: TurnState) -> None:
        """
        Salva l'oggetto TurnState.
        """
        key = f"turns:{session_id}"
        cache.set(key, state, timeout=None)

    @classmethod
    def _expire_reservation_if_needed(cls, state: TurnState) -> Optional[TurnEvent]:
        """
        Se esiste una prenotazione con finestra scaduta, la rimuove
        e ritorna un evento 'RESERVATION_EXPIRED'. Altrimenti ritorna None.
        """
        if not state.reservation_user_id:
            return None
        if not state.reservation_expires_at:
            return None

        now = timezone.now()
        if state.reservation_expires_at > now:
            return None

        expired_user_id = state.reservation_user_id
        state.reservation_user_id = None
        state.reservation_expires_at = None
        state.version += 1

        return TurnEvent(
            type="RESERVATION_EXPIRED",
            payload={
                "user_id": expired_user_id,
                "expired_at": now.isoformat(),
            },
        )

    @classmethod
    def expire_reservation_if_pending(
        cls,
        session_id: str,
        expected_user_id: int
    ) -> Optional[TurnEvent]:
        """
        Chiamato dal timer asincrono dopo 8 secondi.
        Expira la reservation SOLO se è ancora attiva per lo stesso utente.

        Restituisce l'evento RESERVATION_EXPIRED o None se già consumata.
        """
        state = cls._load_state(session_id)

        # Reservation già consumata o assegnata ad altro utente?
        if state.reservation_user_id != expected_user_id:
            return None

        # Expira la reservation
        state.reservation_user_id = None
        state.reservation_expires_at = None
        state.version += 1

        cls._save_state(session_id, state)

        return TurnEvent(
            type="RESERVATION_EXPIRED",
            payload={
                "user_id": expected_user_id,
                "expired_at": timezone.now().isoformat(),
            },
        )

    # -------------------------------------------------------------------
    #  API per la fase di moderazione
    # -------------------------------------------------------------------

    @classmethod
    def set_moderation_in_progress(cls, session_id: str, value: bool) -> TurnState:
        """
        Imposta il flag moderation_in_progress per la sessione indicata.

        Viene usato dallo strato WebSocket per:
        - impostare a True all'inizio della fase di moderazione post-turno umano;
        - riportare a False al termine della moderazione (dopo eventuale intervento AI).
        """
        state = cls._load_state(session_id)
        if state.moderation_in_progress != value:
            state.moderation_in_progress = value
            state.version += 1
            cls._save_state(session_id, state)
        return state

    @classmethod
    def set_introducing(cls, session_id: str) -> TurnState:
        """
        Set turn state to AI_INTRODUCING for session intro.

        Called when session transitions from LOBBY to ACTIVE to block
        all user interactions while the AI moderator speaks the introduction.
        """
        state = cls._load_state(session_id)
        state.state = TURN_STATE_AI_INTRODUCING
        state.version += 1
        cls._save_state(session_id, state)
        return state

    @classmethod
    def end_introducing(cls, session_id: str) -> TurnState:
        """
        End the intro phase and transition to IDLE.

        Called after the AI moderator finishes speaking the introduction.
        """
        state = cls._load_state(session_id)
        state.state = TURN_STATE_IDLE
        state.version += 1
        cls._save_state(session_id, state)
        return state

    @classmethod
    def start_reservation_window(cls, session_id: str) -> Optional[TurnEvent]:
        """
        Apre la finestra di priorità per una prenotazione esistente.

        Da chiamare DOPO la fase di moderazione, nel finally di _handle_end_speak.
        Questa è l'UNICA funzione che apre la finestra di priorità.

        Ritorna l'evento RESERVATION_WINDOW_STARTED se la finestra è stata aperta,
        None altrimenti.
        """
        state = cls._load_state(session_id)

        # Nessuna prenotazione attiva
        if state.reservation_user_id is None:
            return None

        # Finestra già aperta (non dovrebbe succedere, ma per sicurezza)
        if state.reservation_expires_at is not None:
            return None

        # Apri la finestra
        now = timezone.now()
        state.reservation_expires_at = now + timedelta(seconds=PRIORITY_WINDOW_SECONDS)
        state.version += 1
        cls._save_state(session_id, state)

        return TurnEvent(
            type="RESERVATION_WINDOW_STARTED",
            payload={
                "user_id": state.reservation_user_id,
                "expires_at": state.reservation_expires_at.isoformat(),
                "window_seconds": PRIORITY_WINDOW_SECONDS,
            },
        )

    @classmethod
    def _get_session_phase(cls, session_id: str) -> Optional[str]:
        """
        Recupera la fase corrente della sessione dal database.
        Returns None se la sessione non esiste o se l'ID non è valido.
        """
        from apps.sessions.models import Session
        from django.core.exceptions import ValidationError
        try:
            return Session.objects.values_list("state", flat=True).get(id=session_id)
        except (Session.DoesNotExist, ValidationError):
            return None