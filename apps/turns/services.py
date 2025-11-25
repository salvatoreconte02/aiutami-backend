from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

User = get_user_model()


# -------------------------------------------------------------------
#  Costanti di dominio (stati turno)
# -------------------------------------------------------------------

TURN_STATE_IDLE = "IDLE"
TURN_STATE_HUMAN_SPEAKING = "HUMAN_SPEAKING"
TURN_STATE_AI_SPEAKING = "AI_SPEAKING"

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
    def get_state(cls, session_id: str, user: User) -> TurnResult:
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
    def request_speak(cls, session_id: str, user: User) -> TurnResult:
        """
        Richiesta di iniziare a parlare (toggle 'Parla').
        """
        state = cls._load_state(session_id)
        events: List[TurnEvent] = []

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
    def end_speak(cls, session_id: str, user: User) -> TurnResult:
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

        if state.reservation_user_id is not None:
            now = timezone.now()
            state.reservation_expires_at = now + timedelta(seconds=PRIORITY_WINDOW_SECONDS)
            state.version += 1

            reservation_started = TurnEvent(
                type="RESERVATION_WINDOW_STARTED",
                payload={
                    "user_id": state.reservation_user_id,
                    "expires_at": state.reservation_expires_at.isoformat(),
                    "window_seconds": PRIORITY_WINDOW_SECONDS,
                },
            )
            events.append(reservation_started)

        cls._save_state(session_id, state)
        return TurnResult(success=True, state=state, events=events)

    @classmethod
    def request_reserve(cls, session_id: str, user: User) -> TurnResult:
        """
        Richiesta di prenotazione (alzata di mano).
        """
        state = cls._load_state(session_id)
        events: List[TurnEvent] = []

        if state.state != TURN_STATE_HUMAN_SPEAKING:
            return TurnResult(
                success=False,
                state=state,
                events=events,
                error_code="NOT_ALLOWED",
                error_detail="La prenotazione è consentita solo mentre un umano sta parlando.",
            )

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

        if state.reservation_user_id is not None:
            return TurnResult(
                success=False,
                state=state,
                events=events,
                error_code="PRIORITY_WINDOW_ACTIVE",
                error_detail="Esiste una priorità a favore di un partecipante umano.",
            )

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