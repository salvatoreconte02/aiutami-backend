# apps/sessions/ws_consumer.py

from __future__ import annotations

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.layers import get_channel_layer


class SessionsConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer per le sessioni.

    Scopo:
    - accetta connessioni solo da utenti autenticati
      che sono membri della sessione;
    - iscrive il canale nel gruppo "sessions_<session_id>";
    - inoltra ai client gli eventi broadcast sulle sessioni
      (es. cambio stato, chiusura, ecc.).
    """

    async def connect(self):
        """
        - Legge session_id dall'URL.
        - Verifica autenticazione (JwtAuthMiddlewareStack).
        - Verifica che l'utente sia membro della sessione.
        - Aggiunge il canale al gruppo sessions_<session_id>.
        """
        # session_id arriva come UUID; lo si normalizza a stringa
        self.session_id = str(self.scope["url_route"]["kwargs"]["session_id"])
        self.user = self.scope.get("user")

        # Utente non autenticato -> chiusura
        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        # Controllo membership: l'utente deve appartenere alla sessione
        is_member = await self._is_session_member(self.session_id, self.user.id)
        if not is_member:
            await self.close(code=4003)
            return

        # Nome del gruppo per questa sessione
        self.group_name = f"sessions_{self.session_id}"

        # Iscrizione al gruppo Channels
        await self.channel_layer.group_add(self.group_name, self.channel_name)

        # Accetta la connessione WS
        await self.accept()

    async def disconnect(self, code):
        """
        Rimozione dal gruppo WS.
        """
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # -------------------------------------------------------------------------
    # Ricezione messaggi dal client (in pratica: WS read-only)
    # -------------------------------------------------------------------------

    async def receive_json(self, content, **kwargs):
        """
        Per ora il canale è *solo notifiche server→client*.
        Se il client invia qualcosa, si risponde con un errore standard.
        """
        await self.send_json(
            {
                "type": "sessions.error",
                "payload": {
                    "success": False,
                    "error_code": "READ_ONLY",
                    "error_detail": "Questo WebSocket è solo per notifiche server → client.",
                },
            }
        )

    # -------------------------------------------------------------------------
    # Handler chiamato da group_send
    # -------------------------------------------------------------------------

    async def sessions_event(self, event):
        """
        Handler usato da Channels quando qualcuno fa:
            group_send("sessions_<id>", {"type": "sessions.event", ...})
        """
        await self.send_json(
            {
                # es. "sessions.state_changed", "sessions.closed"
                "type": f"sessions.{event['event_type'].lower()}",
                "payload": event.get("payload") or {},
            }
        )

    # -------------------------------------------------------------------------
    # Helper: controlli DB (sync → async)
    # -------------------------------------------------------------------------

    @database_sync_to_async
    def _is_session_member(self, session_id: str, user_id: int) -> bool:
        """
        Verifica che l'utente sia membro della sessione (host o participant).
        """
        from apps.sessions.models import Session

        return Session.objects.filter(
            id=session_id,
            participants__user_id=user_id,
        ).exists()

    @database_sync_to_async
    def _get_session_state(self, session_id: str) -> str:
        """
        PER ADESSO NON USATA, NEL CHILLING :)
        
        Eventuale utility futura per leggere lo stato (ACTIVE, LOBBY, ecc.).
        Non usata subito, ma utile se si vorrà filtrare per stato.
        """
        from apps.sessions.models import Session

        return Session.objects.values_list("state", flat=True).get(id=session_id)


# -------------------------------------------------------------------------
# Funzione di broadcast da usare nelle view HTTP
# -------------------------------------------------------------------------

def broadcast_session_event(session_id: str, event_type: str, payload: dict | None = None) -> None:
    """
    Funzione di utilità da richiamare dalle view (o da altri servizi)
    per inviare eventi a tutti i client collegati alla sessione.

    Esempi:
        broadcast_session_event(
            session_id,
            "STATE_CHANGED",
            {"state": "ACTIVE"}
        )

        broadcast_session_event(
            session_id,
            "CLOSED",
            {"state": "CLOSED"}
        )
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        # In teoria non dovrebbe succedere in ambiente corretto,
        # ma meglio essere difensivi.
        return

    async_to_sync(channel_layer.group_send)(
        f"sessions_{session_id}",
        {
            "type": "sessions.event",   # instrada verso SessionsConsumer.sessions_event
            "event_type": event_type,
            "payload": payload or {},
        },
    )