from __future__ import annotations

import asyncio
import logging
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
from apps.turns.services import (
    TurnManager,
    TURN_STATE_IDLE,
    TURN_STATE_HUMAN_SPEAKING,
    TURN_STATE_AI_SPEAKING,
)

logger = logging.getLogger(__name__)


class WebRTCConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket Consumer per WebRTC signaling.

    Obiettivo MVP:
    - WebRTC può restare connesso (track audio può arrivare sempre)
    - ASR deve partire SOLO quando l'utente è current speaker e lo stato turni è HUMAN_SPEAKING
    - ASR deve fermarsi appena non è più speaker / stato non compatibile
    """

    async def connect(self):
        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]
        self.user = self.scope["user"]

        self.pc: Optional[RTCPeerConnection] = None
        self._reader_task: Optional[asyncio.Task] = None

        # Stato turni "shadow" in questo consumer (aggiornato via eventi del gruppo turns)
        self._turn_state: str = TURN_STATE_IDLE
        self._current_speaker_user_id: Optional[int] = None

        # ASR gating
        self._asr_started: bool = False

        # Gruppo turns (per ricevere HUMAN_STARTED/HUMAN_ENDED/AI_STARTED/AI_ENDED)
        self._turns_group_name = f"turns_{self.session_id}"

        if not self.user.is_authenticated:
            await self.close(code=4001)
            return

        is_member = await self._is_session_member(self.session_id, self.user.id)
        if not is_member:
            await self.close(code=4003)
            return

        # Join al gruppo turns della sessione per ricevere eventi turno
        try:
            await self.channel_layer.group_add(self._turns_group_name, self.channel_name)
        except Exception:
            logger.exception("[WebRTC] group_add turns failed user=%s session=%s", self.user.id, self.session_id)

        # Carico stato turni iniziale (1 volta sola) dal TurnManager
        await self._refresh_turn_state_from_manager()

        await self.accept()
        logger.info("[WebRTC] WS accepted user=%s session=%s", self.user.id, self.session_id)

    async def disconnect(self, code):
        await self._cleanup(reason=f"disconnect(code={code})")
        # Leave gruppo turns
        try:
            await self.channel_layer.group_discard(self._turns_group_name, self.channel_name)
        except Exception:
            pass

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
    # TURN EVENTS (dal gruppo turns_{session_id})
    # ------------------------------------------------------------------ #

    async def turns_event(self, event):
        """
        Riceve eventi broadcastati da TurnsConsumer:
          type="turns.event"
          event_type="HUMAN_STARTED" / "HUMAN_ENDED" / "AI_STARTED" / "AI_ENDED" / ...
          payload={...}
        """
        try:
            ev_type = event.get("event_type")
            payload = event.get("payload") or {}
        except Exception:
            return

        # Aggiorna shadow state in base agli eventi noti
        if ev_type == "HUMAN_STARTED":
            self._turn_state = TURN_STATE_HUMAN_SPEAKING
            self._current_speaker_user_id = payload.get("user_id")
        elif ev_type == "HUMAN_ENDED":
            self._turn_state = TURN_STATE_IDLE
            self._current_speaker_user_id = None
        elif ev_type == "AI_STARTED":
            self._turn_state = TURN_STATE_AI_SPEAKING
            self._current_speaker_user_id = None
        elif ev_type == "AI_ENDED":
            self._turn_state = TURN_STATE_IDLE
            self._current_speaker_user_id = None
        else:
            # Eventi non rilevanti per il gating (RESERVATION_*, ecc.)
            return

        # Applica gating ASR (start/stop)
        await self._apply_asr_gating(reason=f"turn_event:{ev_type}")

    async def _refresh_turn_state_from_manager(self):
        """
        Lettura iniziale (o di recovery) dello stato turni dalla cache (TurnManager).
        Evita di fare query per ogni frame.
        """
        try:
            res = await sync_to_async(TurnManager.get_state)(self.session_id, self.user)
            st = res.state
            self._turn_state = st.state
            self._current_speaker_user_id = st.current_speaker_user_id
        except Exception:
            # Se fallisce, restiamo conservativi: ASR spento
            self._turn_state = TURN_STATE_IDLE
            self._current_speaker_user_id = None

        await self._apply_asr_gating(reason="initial_state_load")

    async def _apply_asr_gating(self, reason: str):
        """
        Decide se ASR deve essere attivo per questo utente.
        Regola:
          ASR ON  <=>  turn_state == HUMAN_SPEAKING AND current_speaker_user_id == self.user.id
        """
        should_run = (
            self._turn_state == TURN_STATE_HUMAN_SPEAKING
            and self._current_speaker_user_id == self.user.id
        )

        if should_run and not self._asr_started:
            try:
                asr_stream_manager.start_stream(self.session_id, self.user.id)
                self._asr_started = True
                logger.info(
                    "[ASR] START (gated) session=%s user=%s reason=%s",
                    self.session_id,
                    self.user.id,
                    reason,
                )
            except Exception:
                logger.exception("[ASR] start_stream failed session=%s user=%s", self.session_id, self.user.id)
                self._asr_started = False

        if (not should_run) and self._asr_started:
            try:
                asr_stream_manager.stop_stream(self.session_id, self.user.id)
                logger.info(
                    "[ASR] STOP (gated) session=%s user=%s reason=%s",
                    self.session_id,
                    self.user.id,
                    reason,
                )
            except Exception:
                logger.exception("[ASR] stop_stream failed session=%s user=%s", self.session_id, self.user.id)
            finally:
                self._asr_started = False

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
            iceServers=[RTCIceServer(urls=["stun:stun.l.google.com:19302"])]
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

        # Trickle ICE: server -> browser
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

        # Ricezione track
        @self.pc.on("track")
        async def on_track(track):
            logger.info("[WebRTC] Track received kind=%s user=%s session=%s", track.kind, self.user.id, self.session_id)
            if track.kind != "audio":
                return

            async def reader():
                try:
                    while True:
                        frame = await track.recv()

                        # Ingest ASR SOLO se gated ON (speaker corrente)
                        if self._asr_started:
                            asr_stream_manager.ingest_frame(self.session_id, self.user.id, frame)

                except asyncio.CancelledError:
                    logger.info("[WebRTC] Reader cancelled user=%s session=%s", self.user.id, self.session_id)
                except Exception:
                    logger.exception("[WebRTC] Reader error user=%s session=%s", self.user.id, self.session_id)
                finally:
                    # Stop ASR se era attivo
                    if self._asr_started:
                        try:
                            asr_stream_manager.stop_stream(self.session_id, self.user.id)
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