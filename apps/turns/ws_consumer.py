# apps/turns/ws_consumer.py

from __future__ import annotations

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async


class TurnsConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer per la gestione dei turni vocali.
    Riceve azioni dal frontend, le valida, chiama TurnManager,
    e notifica tutti gli utenti nella sessione tramite broadcast.
    """

    async def connect(self):
        """
        - Verifica autenticazione.
        - Legge session_id dall'URL route.
        - Verifica che l'utente sia membro della sessione.
        - Aggiunge utente al gruppo WS: turns_{session_id}
        """
        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]
        self.user = self.scope["user"]

        if not self.user.is_authenticated:
            await self.close(code=4001)
            return

        # Controllo membership sessione
        is_member = await self._is_session_member(self.session_id, self.user.id)
        if not is_member:
            await self.close(code=4003)
            return

        self.group_name = f"turns_{self.session_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)

        await self.accept()

    async def disconnect(self, code):
        """
        Rimuove l'utente dal gruppo WS.
        """
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # -------------------------------------------------------------------------
    # Dispatcher principale: riceve JSON dal frontend
    # -------------------------------------------------------------------------

    async def receive_json(self, content, **kwargs):
        """
        Punto di ingresso per i messaggi WebSocket provenienti dal frontend.

        Ci si aspetta un JSON con almeno:
        - "type": stringa che identifica l'azione richiesta
        """

        message_type = content.get("type")
        if not message_type:
            await self.send_json(
                {
                    "success": False,
                    "error": "MISSING_TYPE",
                }
            )
            return

        # Dispatcher principale
        if message_type == "turns.get_state":
            await self._handle_get_state(content)
            return

        if message_type == "turns.request_speak":
            await self._handle_request_speak(content)
            return

        if message_type == "turns.end_speak":
            await self._handle_end_speak(content)
            return

        if message_type == "turns.request_reserve":
            await self._handle_request_reserve(content)
            return

        if message_type == "turns.ai_start":
            await self._handle_ai_start(content)
            return

        if message_type == "turns.ai_end":
            await self._handle_ai_end(content)
            return

        # Default: tipo non riconosciuto
        await self.send_json(
            {
                "success": False,
                "error": "UNKNOWN_TYPE",
                "type": message_type,
            }
        )

    # -------------------------------------------------------------------------
    # HANDLER DELLE AZIONI
    # -------------------------------------------------------------------------

    async def _handle_get_state(self, content):
        """
        Gestisce il messaggio: { "type": "turns.get_state" }.
        Ritorna lo stato corrente al chiamante e, se necessario,
        emette in broadcast eventuali eventi (es. RESERVATION_EXPIRED).
        """
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.send_json(
                {
                    "type": "turns.state",
                    "payload": {
                        "success": False,
                        "error_code": "UNAUTHENTICATED",
                        "error_detail": "Utente non autenticato sulla connessione WS.",
                    },
                }
            )
            return

        from apps.turns.services import TurnManager

        result = TurnManager.get_state(self.session_id, user)

        # Broadcast degli eventi (se presenti)
        await self._broadcast_events(result.events)

        # Risposta diretta al chiamante con lo stato
        await self.send_json(
            {
                "type": "turns.state",
                "payload": result.to_state_dict(),
            }
        )

    async def _handle_request_speak(self, content):
        """
        Gestisce il messaggio: { "type": "turns.request_speak" }.

        Chiede al TurnManager di aprire un turno di speaking umano
        per l'utente corrente, se le regole di dominio lo consentono.
        """
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.send_json(
                {
                    "type": "turns.state",
                    "payload": {
                        "success": False,
                        "error_code": "UNAUTHENTICATED",
                        "error_detail": "Utente non autenticato sulla connessione WS.",
                    },
                }
            )
            return

        # I turni sono gestiti solo in sessioni ACTIVE
        if not await self._ensure_session_active():
            return

        from apps.turns.services import TurnManager

        result = TurnManager.request_speak(self.session_id, user)

        # Broadcast degli eventi (HUMAN_STARTED, eventuale RESERVATION_EXPIRED, ecc.)
        await self._broadcast_events(result.events)

        # Risposta diretta al chiamante con lo stato aggiornato / errore
        await self.send_json(
            {
                "type": "turns.state",
                "payload": result.to_state_dict(),
            }
        )

    async def _handle_end_speak(self, content):
        """
        Gestisce il messaggio: { "type": "turns.end_speak" }.

        Richiede la chiusura dello speaking umano per l’utente corrente.
        """
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.send_json(
                {
                    "type": "turns.state",
                    "payload": {
                        "success": False,
                        "error_code": "UNAUTHENTICATED",
                        "error_detail": "Utente non autenticato sulla connessione WS.",
                    },
                }
            )
            return

        if not await self._ensure_session_active():
            return

        from apps.turns.services import TurnManager

        result = TurnManager.end_speak(self.session_id, user)

        # Broadcast degli eventi (HUMAN_ENDED, eventuale RESERVATION_WINDOW_STARTED)
        await self._broadcast_events(result.events)

        # Risposta diretta al chiamante
        await self.send_json(
            {
                "type": "turns.state",
                "payload": result.to_state_dict(),
            }
        )

    async def _handle_request_reserve(self, content):
        """
        Gestisce il messaggio: { "type": "turns.request_reserve" }.

        Richiede la prenotazione (alzata di mano) per l’utente corrente.
        """
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.send_json(
                {
                    "type": "turns.state",
                    "payload": {
                        "success": False,
                        "error_code": "UNAUTHENTICATED",
                        "error_detail": "Utente non autenticato sulla connessione WS.",
                    },
                }
            )
            return

        if not await self._ensure_session_active():
            return

        from apps.turns.services import TurnManager

        result = TurnManager.request_reserve(self.session_id, user)

        # Broadcast degli eventi (es. RESERVATION_SET)
        await self._broadcast_events(result.events)

        # Risposta diretta al chiamante con lo stato aggiornato / eventuale errore
        await self.send_json(
            {
                "type": "turns.state",
                "payload": result.to_state_dict(),
            }
        )

    async def _handle_ai_start(self, content):
        """
        Gestisce il messaggio: { "type": "turns.ai_start" }.

        Avvia l'intervento dell'AI se consentito dallo stato corrente.
        """
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.send_json(
                {
                    "type": "turns.state",
                    "payload": {
                        "success": False,
                        "error_code": "UNAUTHENTICATED",
                        "error_detail": "Utente non autenticato sulla connessione WS.",
                    },
                }
            )
            return

        if not await self._ensure_session_active():
            return

        from apps.turns.services import TurnManager

        result = TurnManager.ai_start(self.session_id)

        # Broadcast: AI_STARTED a tutti
        await self._broadcast_events(result.events)

        # Risposta al chiamante
        await self.send_json(
            {
                "type": "turns.state",
                "payload": result.to_state_dict(),
            }
        )

    async def _handle_ai_end(self, content):
        """
        Gestisce il messaggio: { "type": "turns.ai_end" }.

        Termina l'intervento dell'AI se in corso.
        """
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.send_json(
                {
                    "type": "turns.state",
                    "payload": {
                        "success": False,
                        "error_code": "UNAUTHENTICATED",
                        "error_detail": "Utente non autenticato sulla connessione WS.",
                    },
                }
            )
            return

        if not await self._ensure_session_active():
            return

        from apps.turns.services import TurnManager

        result = TurnManager.ai_end(self.session_id)

        # Broadcast degli eventi (AI_ENDED)
        await self._broadcast_events(result.events)

        # Risposta al chiamante
        await self.send_json(
            {
                "type": "turns.state",
                "payload": result.to_state_dict(),
            }
        )

    # -------------------------------------------------------------------------
    # UTILITIES
    # -------------------------------------------------------------------------

    async def _broadcast_events(self, events):
        """
        Invia in broadcast al gruppo WS tutti gli eventi di TurnManager
        trasformandoli in messaggi WebSocket.
        """
        if not events:
            return

        for ev in events:
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "turns.event",  # nome del metodo handler nel consumer
                    "event_type": ev.type,
                    "payload": ev.payload or {},
                },
            )

    async def turns_event(self, event):
        """
        Handler chiamato da group_send.
        Converte l'evento interno in un messaggio WS verso il client.
        """
        await self.send_json(
            {
                "type": f"turns.{event['event_type'].lower()}",
                "payload": event["payload"],
            }
        )

    # -------------------------------------------------------------------------
    # CHECKS UTILI (sync → async)
    # -------------------------------------------------------------------------

    @database_sync_to_async
    def _is_session_member(self, session_id, user_id: int) -> bool:
        from apps.sessions.models import Session

        return Session.objects.filter(
            id=session_id,
            participants__user_id=user_id,
        ).exists()

    @database_sync_to_async
    def _get_session_state(self, session_id) -> str:
        from apps.sessions.models import Session

        return Session.objects.values_list("state", flat=True).get(id=session_id)

    async def _ensure_session_active(self) -> bool:
        """
        Verifica che la sessione sia in stato ACTIVE.
        In caso contrario, risponde con errore e ritorna False.
        """
        from apps.sessions.models import SessionState

        try:
            current_state = await self._get_session_state(self.session_id)
        except Exception:
            await self.send_json(
                {
                    "type": "turns.state",
                    "payload": {
                        "success": False,
                        "error_code": "SESSION_NOT_FOUND",
                        "error_detail": "Sessione inesistente o non più disponibile.",
                    },
                }
            )
            return False

        if current_state != SessionState.ACTIVE:
            await self.send_json(
                {
                    "type": "turns.state",
                    "payload": {
                        "success": False,
                        "error_code": "SESSION_NOT_ACTIVE",
                        "error_detail": f"I turni sono disponibili solo quando la sessione è in stato ACTIVE (stato corrente: {current_state}).",
                    },
                }
            )
            return False

        return True