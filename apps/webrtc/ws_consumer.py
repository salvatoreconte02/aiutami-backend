# apps/webrtc/ws_consumer.py

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from asgiref.sync import sync_to_async
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

    Correzione principale:
    - NON avviare ASR appena arriva la track.
    - Avviare/ingestire ASR solo quando lo stato turni indica che l'utente corrente
      è lo speaker (HUMAN_SPEAKING e current_speaker_user_id == self.user.id).
    """

    # per evitare query ad ogni frame (50fps), si rivaluta la “gate condition”
    # al massimo ogni 250ms.
    GATE_CHECK_INTERVAL_SEC = 0.25

    async def connect(self):
        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]
        self.user = self.scope["user"]

        self.pc: Optional[RTCPeerConnection] = None
        self._reader_task: Optional[asyncio.Task] = None

        # gate ASR
        self._asr_started: bool = False
        self._gate_open: bool = False
        self._last_gate_check_ts: float = 0.0

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

        config = RTCConfiguration(
            iceServers=[
                RTCIceServer(urls=["stun:stun.l.google.com:19302"]),
            ]
        )

        self.pc = RTCPeerConnection(configuration=config)

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

        @self.pc.on("icecandidate")
        async def on_icecandidate(candidate):
            try:
                if candidate is None:
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

        @self.pc.on("track")
        async def on_track(track):
            logger.info("[WebRTC] Track received kind=%s user=%s session=%s", track.kind, self.user.id, self.session_id)

            if track.kind != "audio":
                return

            async def reader():
                try:
                    while True:
                        frame = await track.recv()

                        # Gate: ingestire solo se l'utente è speaker secondo TurnManager
                        gate_open = await self._is_current_speaker_gate()

                        if gate_open:
                            if not self._asr_started:
                                self._asr_started = True
                                try:
                                    asr_stream_manager.start_stream(self.session_id, self.user.id)
                                    logger.info("[ASR] START worker session=%s user=%s", self.session_id, self.user.id)
                                except Exception:
                                    logger.exception("[ASR] start_stream failed session=%s user=%s", self.session_id, self.user.id)
                                    self._asr_started = False

                            if self._asr_started:
                                try:
                                    asr_stream_manager.ingest_frame(self.session_id, self.user.id, frame)
                                except Exception:
                                    logger.exception("[ASR] ingest_frame failed session=%s user=%s", self.session_id, self.user.id)
                        else:
                            # Se la gate si chiude mentre lo stream è aperto, si stoppa.
                            if self._asr_started:
                                try:
                                    asr_stream_manager.stop_stream(self.session_id, self.user.id)
                                    logger.info("[ASR] STOP worker session=%s user=%s reason=gate_closed", self.session_id, self.user.id)
                                except Exception:
                                    logger.exception("[ASR] stop_stream failed session=%s user=%s", self.session_id, self.user.id)
                                finally:
                                    self._asr_started = False

                except asyncio.CancelledError:
                    logger.info("[WebRTC] Reader cancelled user=%s session=%s", self.user.id, self.session_id)
                except Exception:
                    logger.exception("[WebRTC] Reader error user=%s session=%s", self.user.id, self.session_id)
                finally:
                    if self._asr_started:
                        try:
                            asr_stream_manager.stop_stream(self.session_id, self.user.id)
                            logger.info("[ASR] STOP worker session=%s user=%s reason=reader_finally", self.session_id, self.user.id)
                        except Exception:
                            logger.exception("[WebRTC] stop_stream failed (finally) user=%s session=%s", self.user.id, self.session_id)
                        self._asr_started = False

            self._reader_task = asyncio.create_task(reader())

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
    # Gate speaker (TurnManager)
    # ------------------------------------------------------------------ #

    async def _is_current_speaker_gate(self) -> bool:
        """
        True solo quando:
        - state == HUMAN_SPEAKING
        - current_speaker_user_id == self.user.id
        - moderation_in_progress == False

        Per ridurre carico, ricalcola al massimo ogni GATE_CHECK_INTERVAL_SEC.
        """
        now = time.time()
        if (now - self._last_gate_check_ts) < self.GATE_CHECK_INTERVAL_SEC:
            return self._gate_open

        self._last_gate_check_ts = now

        try:
            from apps.turns.services import TurnManager, TURN_STATE_HUMAN_SPEAKING

            # TurnManager è sync; lo si esegue in threadpool
            result = await sync_to_async(TurnManager.get_state, thread_sensitive=True)(self.session_id, self.user)
            state = result.state

            gate_open = (
                state.state == TURN_STATE_HUMAN_SPEAKING
                and state.current_speaker_user_id == self.user.id
                and not state.moderation_in_progress
            )

            # log solo quando cambia (per non spam)
            if gate_open != self._gate_open:
                logger.info(
                    "[WebRTC] ASR gate change user=%s session=%s open=%s state=%s current_speaker=%s moderation=%s",
                    self.user.id,
                    self.session_id,
                    gate_open,
                    state.state,
                    state.current_speaker_user_id,
                    state.moderation_in_progress,
                )

            self._gate_open = gate_open
            return gate_open

        except Exception:
            logger.exception("[WebRTC] Gate check failed user=%s session=%s", self.user.id, self.session_id)
            self._gate_open = False
            return False

    # ------------------------------------------------------------------ #
    # ICE (browser -> server)
    # ------------------------------------------------------------------ #

    async def _handle_ice_candidate(self, content: dict):
        if self.pc is None:
            return

        cand = content.get("candidate", None)

        if cand is None:
            try:
                await self.pc.addIceCandidate(None)
                logger.info("[WebRTC] addIceCandidate(None) end user=%s session=%s", self.user.id, self.session_id)
            except Exception:
                logger.exception("[WebRTC] addIceCandidate(None) failed user=%s session=%s", self.user.id, self.session_id)
            return

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
                logger.info("[ASR] STOP worker session=%s user=%s reason=cleanup", self.session_id, self.user.id)
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