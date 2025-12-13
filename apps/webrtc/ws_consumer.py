# apps/webrtc/ws_consumer.py

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCConfiguration,
    RTCIceServer,
)
from aiortc.sdp import candidate_from_sdp

from apps.asr.service import asr_stream_manager

logger = logging.getLogger(__name__)


class WebRTCConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket Consumer per WebRTC signaling.

    - Autenticazione JWT (middleware già predisposto nel progetto)
    - Verifica membership sessione
    - Gestione offer/answer
    - Trickle ICE:
        * server -> browser (invia i candidati generati dal server)
        * browser -> server (accetta i candidati del browser)
    - Riceve audio WebRTC e lo inoltra al modulo ASR
    """

    async def connect(self):
        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]
        self.user = self.scope["user"]

        self.pc: Optional[RTCPeerConnection] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._asr_started: bool = False

        if not self.user.is_authenticated:
            await self.close(code=4001)
            return

        is_member = await self._is_session_member(self.session_id, self.user.id)
        if not is_member:
            await self.close(code=4003)
            return

        await self.accept()
        logger.info("[WebRTC] WS accepted user=%s session=%s", self.user.id, self.session_id)

    async def disconnect(self, code):
        await self._cleanup(reason=f"disconnect(code={code})")

    async def receive_json(self, content, **kwargs):
        msg_type = (content or {}).get("type")

        try:
            if msg_type == "webrtc.offer":
                await self._handle_offer(content or {})
                return

            if msg_type in ("webrtc.ice_candidate", "webrtc.ice"):
                await self._handle_ice_candidate(content or {})
                return

            await self.send_json(
                {
                    "type": "webrtc.error",
                    "payload": {"reason": "UNKNOWN_TYPE", "received_type": msg_type},
                }
            )
        except Exception:
            logger.exception(
                "[WebRTC] receive_json error user=%s session=%s type=%r",
                getattr(self, "user", None),
                getattr(self, "session_id", None),
                msg_type,
            )
            try:
                await self.send_json({"type": "webrtc.error", "payload": {"reason": "INTERNAL_ERROR"}})
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # OFFER / ANSWER
    # ------------------------------------------------------------------ #

    async def _handle_offer(self, content: dict):
        sdp = content.get("sdp")
        sdp_type = content.get("type_sdp", "offer")

        if not sdp:
            await self.send_json({"type": "webrtc.error", "payload": {"reason": "MISSING_SDP"}})
            return

        # Se arriva una nuova offer, ripartire “puliti”
        if self.pc is not None:
            await self._cleanup(reason="new_offer")

        # ICE config:
        # - STUN: serve a ottenere candidate “srflx” (pubblici) dal container/VM.
        # - TURN: verrà aggiunto in futuro per robustezza (tesi / prodotto finale).
        config = RTCConfiguration(
            iceServers=[
                RTCIceServer(urls=["stun:stun.l.google.com:19302"]),
            ]
        )

        self.pc = RTCPeerConnection(configuration=config)

        # --- Eventi di stato (log utili in VM) ---
        @self.pc.on("icegatheringstatechange")
        async def on_ice_gathering_state_change():
            try:
                st = self.pc.iceGatheringState if self.pc else None
                logger.info("[WebRTC] iceGatheringState=%s user=%s session=%s", st, self.user.id, self.session_id)
            except Exception:
                logger.exception("[WebRTC] icegatheringstatechange error user=%s session=%s", self.user.id, self.session_id)

        @self.pc.on("iceconnectionstatechange")
        async def on_ice_state_change():
            try:
                st = self.pc.iceConnectionState if self.pc else None
                logger.info("[WebRTC] iceConnectionState=%s user=%s session=%s", st, self.user.id, self.session_id)
            except Exception:
                logger.exception("[WebRTC] iceconnectionstatechange error user=%s session=%s", self.user.id, self.session_id)

        @self.pc.on("connectionstatechange")
        async def on_connection_state_change():
            try:
                st = self.pc.connectionState if self.pc else None
                logger.info("[WebRTC] connectionState=%s user=%s session=%s", st, self.user.id, self.session_id)
                if st in ("failed", "closed", "disconnected"):
                    await self._cleanup(reason=f"connectionState={st}")
            except Exception:
                logger.exception("[WebRTC] connectionstatechange error user=%s session=%s", self.user.id, self.session_id)

        # --- Trickle ICE: server -> browser ---
        @self.pc.on("icecandidate")
        async def on_icecandidate(candidate):
            """
            Invia al browser i candidati generati dal server.
            """
            try:
                if candidate is None:
                    # Fine candidati (end-of-candidates)
                    await self.send_json({"type": "webrtc.ice_candidate", "candidate": None})
                    return

                await self.send_json(
                    {
                        "type": "webrtc.ice_candidate",
                        "candidate": {
                            "candidate": candidate.to_sdp(),
                            "sdpMid": candidate.sdpMid,
                            "sdpMLineIndex": candidate.sdpMLineIndex,
                        },
                    }
                )
            except Exception:
                logger.exception("[WebRTC] send ICE to browser failed user=%s session=%s", self.user.id, self.session_id)

        # --- Ricezione track ---
        @self.pc.on("track")
        async def on_track(track):
            logger.info("[WebRTC] Track received kind=%s user=%s session=%s", track.kind, self.user.id, self.session_id)

            if track.kind != "audio":
                return

            # Avvio ASR (una sola volta)
            if not self._asr_started:
                self._asr_started = True
                asr_stream_manager.start_stream(self.session_id, self.user.id)

            async def reader():
                try:
                    while True:
                        frame = await track.recv()
                        asr_stream_manager.ingest_frame(self.session_id, self.user.id, frame)
                except asyncio.CancelledError:
                    logger.info("[WebRTC] Reader cancelled user=%s session=%s", self.user.id, self.session_id)
                except Exception:
                    logger.exception("[WebRTC] Reader error user=%s session=%s", self.user.id, self.session_id)
                finally:
                    if self._asr_started:
                        try:
                            asr_stream_manager.stop_stream(self.session_id, self.user.id)
                        except Exception:
                            logger.exception("[WebRTC] stop_stream failed (finally) user=%s session=%s", self.user.id, self.session_id)
                        self._asr_started = False

            self._reader_task = asyncio.create_task(reader())

        # --- Applico offer e creo answer ---
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

        logger.info("[WebRTC] Answer sent user=%s session=%s", self.user.id, self.session_id)

    # ------------------------------------------------------------------ #
    # ICE (browser -> server)
    # ------------------------------------------------------------------ #

    async def _handle_ice_candidate(self, content: dict):
        """
        Accetta ICE candidate dal browser in due formati:

        A) {"type": "...", "candidate": {"candidate": "...", "sdpMid": "...", "sdpMLineIndex": 0}}
        B) {"type": "...", "candidate": "candidate:...", "sdpMid": "...", "sdpMLineIndex": 0}

        Supporta candidate=None (end-of-candidates).
        """
        if self.pc is None:
            return

        cand = content.get("candidate", None)

        # end-of-candidates
        if cand is None:
            try:
                await self.pc.addIceCandidate(None)
                logger.info("[WebRTC] addIceCandidate(None) end user=%s session=%s", self.user.id, self.session_id)
            except Exception:
                logger.exception("[WebRTC] addIceCandidate(None) failed user=%s session=%s", self.user.id, self.session_id)
            return

        # Normalizzazione
        if isinstance(cand, str):
            candidate_sdp = cand
            sdp_mid = content.get("sdpMid")
            sdp_mline = content.get("sdpMLineIndex")
        elif isinstance(cand, dict):
            candidate_sdp = cand.get("candidate")
            sdp_mid = cand.get("sdpMid")
            sdp_mline = cand.get("sdpMLineIndex")
        else:
            await self.send_json({"type": "webrtc.error", "payload": {"reason": "BAD_ICE_CANDIDATE_FORMAT"}})
            return

        if not candidate_sdp:
            return

        try:
            ice = candidate_from_sdp(candidate_sdp)
            ice.sdpMid = sdp_mid
            ice.sdpMLineIndex = int(sdp_mline) if sdp_mline is not None else None

            await self.pc.addIceCandidate(ice)

            logger.info(
                "[WebRTC] ICE added user=%s session=%s mid=%s mline=%s",
                self.user.id,
                self.session_id,
                ice.sdpMid,
                ice.sdpMLineIndex,
            )
        except Exception:
            logger.exception(
                "[WebRTC] addIceCandidate failed user=%s session=%s candidate=%r",
                self.user.id,
                self.session_id,
                candidate_sdp,
            )
            await self.send_json({"type": "webrtc.error", "payload": {"reason": "ADD_ICE_FAILED"}})

    # ------------------------------------------------------------------ #
    # CLEANUP
    # ------------------------------------------------------------------ #

    async def _cleanup(self, reason: str):
        """
        Cleanup robusto e idempotente:
        - cancella reader task
        - stop ASR (se attivo)
        - chiude PeerConnection
        """
        try:
            logger.info(
                "[WebRTC] Cleanup reason=%s user=%s session=%s",
                reason,
                getattr(self, "user", None).id if getattr(self, "user", None) else None,
                getattr(self, "session_id", None),
            )
        except Exception:
            pass

        if self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None

        if self._asr_started:
            try:
                asr_stream_manager.stop_stream(self.session_id, self.user.id)
            except Exception:
                logger.exception("[WebRTC] stop_stream failed (cleanup) user=%s session=%s", self.user.id, self.session_id)
            self._asr_started = False

        if self.pc is not None:
            try:
                await self.pc.close()
            except Exception:
                pass
            self.pc = None

    # ------------------------------------------------------------------ #
    # UTILITIES
    # ------------------------------------------------------------------ #

    @database_sync_to_async
    def _is_session_member(self, session_id, user_id: int) -> bool:
        from apps.sessions.models import Session

        return Session.objects.filter(id=session_id, participants__user_id=user_id).exists()