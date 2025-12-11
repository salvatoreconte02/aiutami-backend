# apps/webrtc/ws_consumer.py

from __future__ import annotations

import asyncio
import logging

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async

from aiortc import RTCPeerConnection, RTCSessionDescription

# Manager astratto che abbiamo definito: start_stream, ingest_frame, stop_stream
from apps.asr.service import asr_stream_manager

logger = logging.getLogger(__name__)


class WebRTCConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket Consumer per WebRTC signalling.
    - Autenticazione JWT (JwtAuthMiddlewareStack)
    - Verifica che l’utente appartenga alla sessione
    - Gestisce offer/answer/ICE
    - Riceve audio WebRTC e lo inoltra al modulo ASR
    """

    async def connect(self):
        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]
        self.user = self.scope["user"]
        self.pc: RTCPeerConnection | None = None

        # Stato ASR locale
        self._reader_task: asyncio.Task | None = None

        if not self.user.is_authenticated:
            await self.close(code=4001)
            return

        is_member = await self._is_session_member(self.session_id, self.user.id)
        if not is_member:
            await self.close(code=4003)
            return

        await self.accept()
        logger.info(
            "WebRTC WS accepted for user %s in session %s",
            self.user.id,
            self.session_id,
        )

    async def disconnect(self, code):
        # Chiude PeerConnection
        if self.pc is not None:
            try:
                await self.pc.close()
            except Exception:
                pass
            logger.info(
                "WebRTC PC closed for user %s in session %s",
                self.user.id,
                self.session_id,
            )
            self.pc = None

        # Stop task lettura audio
        if self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None

        # Chiude stream ASR
        try:
            asr_stream_manager.stop_stream(self.session_id, self.user.id)
        except Exception:
            logger.exception(
                "Errore durante stop_stream ASR session=%s user=%s",
                self.session_id,
                self.user.id,
            )

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")

        if msg_type == "webrtc.offer":
            await self._handle_offer(content)
            return

        if msg_type == "webrtc.ice_candidate":
            await self._handle_ice_candidate(content)
            return

        await self.send_json(
            {
                "type": "webrtc.error",
                "payload": {
                    "reason": "UNKNOWN_TYPE",
                    "received_type": msg_type,
                },
            }
        )

    # ------------------------------------------------------------------ #
    # OFFER / ANSWER
    # ------------------------------------------------------------------ #

    async def _handle_offer(self, content: dict):
        if self.pc is not None:
            try:
                await self.pc.close()
            except Exception:
                pass

        self.pc = RTCPeerConnection()

        @self.pc.on("track")
        async def on_track(track):
            logger.info(
                "Ricevuta track %s da user %s (sessione %s)",
                track.kind,
                self.user.id,
                self.session_id,
            )

            if track.kind != "audio":
                return

            # Avvio dello stream ASR
            asr_stream_manager.start_stream(self.session_id, self.user.id)

            async def reader():
                """
                Legge i frame audio (WebRTC → aiortc) e li inoltra all’ASR.
                """
                try:
                    while True:
                        frame = await track.recv()
                        # Invia il frame al manager ASR (che si occupa del PCM)
                        asr_stream_manager.ingest_frame(
                            self.session_id,
                            self.user.id,
                            frame,
                        )
                except asyncio.CancelledError:
                    logger.info(
                        "Track audio chiusa (task cancellato) user=%s session=%s",
                        self.user.id,
                        self.session_id,
                    )
                except Exception:
                    logger.exception(
                        "Errore durante lettura track audio user=%s session=%s",
                        self.user.id,
                        self.session_id,
                    )
                finally:
                    try:
                        asr_stream_manager.stop_stream(self.session_id, self.user.id)
                    except Exception:
                        logger.exception(
                            "Errore stop_stream finale user=%s session=%s",
                            self.user.id,
                            self.session_id,
                        )

            # Avvia task di lettura audio
            self._reader_task = asyncio.create_task(reader())

        sdp = content.get("sdp")
        sdp_type = content.get("type_sdp", "offer")

        if not sdp:
            await self.send_json(
                {
                    "type": "webrtc.error",
                    "payload": {"reason": "MISSING_SDP"},
                }
            )
            return

        offer = RTCSessionDescription(type=sdp_type, sdp=sdp)

        await self.pc.setRemoteDescription(offer)
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)

        await self.send_json(
            {
                "type": "webrtc.answer",
                "sdp": self.pc.localDescription.sdp,
                "type_sdp": self.pc.localDescription.type,
            }
        )

    # ------------------------------------------------------------------ #
    # ICE
    # ------------------------------------------------------------------ #

    async def _handle_ice_candidate(self, content: dict):
        """
        Per ora gli ICE candidate si ignorano (solo log).
        """
        if self.pc is None:
            return

        cand = content.get("candidate")
        if not cand:
            return

        logger.info(
            "ICE candidate ricevuto dal browser (ignorato): %s",
            cand.get("candidate"),
        )

    # ------------------------------------------------------------------ #
    # UTILITIES
    # ------------------------------------------------------------------ #

    @database_sync_to_async
    def _is_session_member(self, session_id, user_id: int) -> bool:
        from apps.sessions.models import Session

        return Session.objects.filter(
            id=session_id,
            participants__user_id=user_id,
        ).exists()