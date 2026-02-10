from __future__ import annotations

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer


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

    # Ricezione messaggi dal client (WS read-only)
    async def receive_json(self, content, **kwargs):
        
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

    # Handler chiamato da group_send
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

    # Helper: controlli DB (sync → async)
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

