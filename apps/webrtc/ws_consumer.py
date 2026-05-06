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
from aiortc.mediastreams import MediaStreamError
from aiortc.sdp import candidate_from_sdp

from av.audio.resampler import AudioResampler

from apps.asr.service import asr_stream_manager
from apps.turns.services import (
    TurnManager,
    TURN_STATE_IDLE,
    TURN_STATE_HUMAN_SPEAKING,
    TURN_STATE_AI_SPEAKING,
)

from .audio_hub import get_hub, maybe_cleanup_hub
from .audio_tracks import ForwardingAudioTrack

logger = logging.getLogger(__name__)


class WebRTCConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket Consumer per WebRTC signaling.

    Obiettivo MVP:
    - WebRTC può restare connesso (track audio può arrivare sempre)
    - ASR parte SOLO quando l'utente è current speaker e lo stato turni è HUMAN_SPEAKING
    - Forwarding audio: lo speaker viene inoltrato dal backend a tutti gli altri peer della sessione
    """

    async def connect(self):
        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]
        self.user = self.scope["user"]

        self.pc: Optional[RTCPeerConnection] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._stats_task: Optional[asyncio.Task] = None

        # Stato turni "shadow"
        self._turn_state: str = TURN_STATE_IDLE
        self._current_speaker_user_id: Optional[int] = None

        # ASR gating
        self._asr_started: bool = False

        # Audio forwarding
        self._hub = get_hub(str(self.session_id))
        self._outbound_track: Optional[ForwardingAudioTrack] = None

        # Gruppo turns (per ricevere eventi turno)
        self._turns_group_name = f"turns_{self.session_id}"

        if not self.user.is_authenticated:
            await self.close(code=4001)
            return

        is_member = await self._is_session_member(self.session_id, self.user.id)
        if not is_member:
            await self.close(code=4003)
            return

        # Join al gruppo turns della sessione
        try:
            await self.channel_layer.group_add(self._turns_group_name, self.channel_name)
        except Exception:
            logger.exception("[WebRTC] group_add turns failed user=%s session=%s", self.user.id, self.session_id)

        # Stato turni iniziale
        await self._refresh_turn_state_from_manager()

        await self.accept()
        logger.info("[WebRTC] WS accepted user=%s session=%s", self.user.id, self.session_id)

    async def disconnect(self, code):
        await self._cleanup(reason=f"disconnect(code={code})")
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

    # TURN EVENTS

    async def turns_event(self, event):
        """
        Eventi broadcastati da TurnsConsumer:
          type="turns.event"
          event_type="HUMAN_STARTED" / "HUMAN_ENDED" / "AI_STARTED" / "AI_ENDED"
          payload={...}
        """
        try:
            ev_type = event.get("event_type")
            payload = event.get("payload") or {}
        except Exception:
            return

        if ev_type == "HUMAN_STARTED":
            speaker_id = payload.get("user_id")
            self._turn_state = TURN_STATE_HUMAN_SPEAKING
            self._current_speaker_user_id = speaker_id
            # hub speaker update
            self._hub.set_speaker(speaker_id)

        elif ev_type == "HUMAN_ENDED":
            self._turn_state = TURN_STATE_IDLE
            self._current_speaker_user_id = None
            self._hub.set_speaker(None)

        elif ev_type == "AI_STARTED":
            self._turn_state = TURN_STATE_AI_SPEAKING
            self._current_speaker_user_id = None
            # Non resettiamo lo speaker qui - viene gestito dal TurnsConsumer
            # che imposta AI_MODERATOR_ID prima di iniziare il TTS

        elif ev_type == "AI_ENDED":
            self._turn_state = TURN_STATE_IDLE
            self._current_speaker_user_id = None
            self._hub.set_speaker(None)

        else:
            return

        await self._apply_asr_gating(reason=f"turn_event:{ev_type}")

    async def _refresh_turn_state_from_manager(self):
        try:
            res = await sync_to_async(TurnManager.get_state)(self.session_id, self.user)
            st = res.state
            self._turn_state = st.state
            self._current_speaker_user_id = st.current_speaker_user_id
            # aggiorna hub speaker con lo stato corrente
            if self._turn_state == TURN_STATE_HUMAN_SPEAKING:
                self._hub.set_speaker(self._current_speaker_user_id)
            else:
                self._hub.set_speaker(None)
        except Exception:
            self._turn_state = TURN_STATE_IDLE
            self._current_speaker_user_id = None
            self._hub.set_speaker(None)

        await self._apply_asr_gating(reason="initial_state_load")

    async def _apply_asr_gating(self, reason: str):
        should_run = (
            self._turn_state == TURN_STATE_HUMAN_SPEAKING
            and self._current_speaker_user_id == self.user.id
        )

        if should_run and not self._asr_started:
            try:
                asr_stream_manager.start_stream(self.session_id, self.user.id)
                self._asr_started = True
                logger.info("[ASR] START (gated) session=%s user=%s reason=%s", self.session_id, self.user.id, reason)
            except Exception:
                logger.exception("[ASR] start_stream failed session=%s user=%s", self.session_id, self.user.id)
                self._asr_started = False

        if (not should_run) and self._asr_started:
            try:
                asr_stream_manager.stop_stream(self.session_id, self.user.id)
                logger.info("[ASR] STOP (gated) session=%s user=%s reason=%s", self.session_id, self.user.id, reason)
            except Exception:
                logger.exception("[ASR] stop_stream failed session=%s user=%s", self.session_id, self.user.id)
            finally:
                self._asr_started = False

    # OFFER / ANSWER

    async def _handle_offer(self, content: dict):
        sdp = content.get("sdp")
        sdp_type = content.get("type_sdp", "offer")

        if not sdp:
            await self.send_json({"type": "webrtc.error", "payload": {"reason": "MISSING_SDP"}})
            return

        if self.pc is not None:
            await self._cleanup(reason="new_offer")

        config = RTCConfiguration(iceServers=[RTCIceServer(urls=["stun:stun.l.google.com:19302"])])
        self.pc = RTCPeerConnection(configuration=config)

        # 1) predisporre sempre una outbound audio track (server -> client)
        #    - inizialmente è silenzio
        #    - l'hub può poi inoltrarvi l'audio dello speaker
        self._outbound_track = ForwardingAudioTrack(
            user_id=self.user.id,
            session_id=str(self.session_id),
            sample_rate_default=48000,
            frame_time_ms=20,
        )
        try:
            self.pc.addTrack(self._outbound_track)
        except Exception:
            logger.exception("[WebRTC] addTrack(outbound) failed user=%s session=%s", self.user.id, self.session_id)

        # registra il peer nell'hub
        try:
            self._hub.register_peer(self.user.id, self._outbound_track)
        except Exception:
            logger.exception("[AudioHub] register failed user=%s session=%s", self.user.id, self.session_id)

        @self.pc.on("icegatheringstatechange")
        async def on_ice_gathering_state_change():
            try:
                st = self.pc.iceGatheringState if self.pc else None
                logger.debug("[WebRTC] iceGatheringState=%s user=%s session=%s", st, self.user.id, self.session_id)
            except Exception:
                logger.exception("[WebRTC] icegatheringstatechange error user=%s session=%s", self.user.id, self.session_id)

        @self.pc.on("iceconnectionstatechange")
        async def on_ice_state_change():
            try:
                st = self.pc.iceConnectionState if self.pc else None
                logger.debug("[WebRTC] iceConnectionState=%s user=%s session=%s", st, self.user.id, self.session_id)
            except Exception:
                logger.exception("[WebRTC] iceconnectionstatechange error user=%s session=%s", self.user.id, self.session_id)

        @self.pc.on("connectionstatechange")
        async def on_connection_state_change():
            try:
                st = self.pc.connectionState if self.pc else None
                # connected/failed/closed/disconnected restano INFO (eventi finali utili in prod);
                # gli stati intermedi (connecting, new) vanno a DEBUG.
                if st in ("connected", "failed", "closed", "disconnected"):
                    logger.info("[WebRTC] connectionState=%s user=%s session=%s", st, self.user.id, self.session_id)
                else:
                    logger.debug("[WebRTC] connectionState=%s user=%s session=%s", st, self.user.id, self.session_id)
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

        # Ricezione track (browser -> server)
        @self.pc.on("track")
        async def on_track(track):
            logger.debug("[WebRTC] Track received kind=%s user=%s session=%s", track.kind, self.user.id, self.session_id)
            if track.kind != "audio":
                return

            resampler = AudioResampler(format="s16", layout="mono", rate=48000)

            async def reader():
                try:
                    while True:
                        frame = await track.recv()

                        # normalizzazione
                        try:
                            out_frames = resampler.resample(frame)
                            if out_frames:
                                frame = out_frames[0]
                        except Exception:
                            logger.exception("[WebRTC] Resample error user=%s session=%s", self.user.id, self.session_id)
                            continue

                        # 2) ASR gated (già esistente)
                        if self._asr_started:
                            asr_stream_manager.ingest_frame(self.session_id, self.user.id, frame)

                        # 3) Forwarding: se questo utente è lo speaker corrente, inoltra agli altri
                        #    (hub esclude automaticamente lo speaker, quindi no echo)
                        try:
                            pcm = bytes(frame.planes[0])[:frame.samples * 2]  # s16 mono = 2 bytes/sample
                            samples = int(frame.samples)
                            sample_rate = int(frame.sample_rate or 48000)
                            self._hub.forward_pcm_from_speaker(
                                from_user_id=self.user.id,
                                pcm=pcm,
                                samples=samples,
                                sample_rate=sample_rate,
                            )
                        except Exception:
                            # non deve far cadere la pipeline
                            logger.exception("[WebRTC] forwarding error user=%s session=%s", self.user.id, self.session_id)

                except asyncio.CancelledError:
                    logger.debug("[WebRTC] Reader cancelled user=%s session=%s", self.user.id, self.session_id)
                except MediaStreamError:
                    # Disconnect del peer remoto: il track è stato chiuso
                    # (browser tab close, network drop, ecc.). Non è un
                    # errore — la disconnessione vera e propria viene
                    # gestita da `connectionstatechange`. Logghiamo INFO
                    # e usciamo senza propagare per non contribuire al
                    # cascade di cleanup.
                    logger.info(
                        "[WebRTC] Reader: track closed (MediaStreamError) user=%s session=%s",
                        self.user.id, self.session_id,
                    )
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
        logger.debug("[WebRTC] Answer sent user=%s session=%s", self.user.id, self.session_id)

    # ICE (browser -> server)

    async def _handle_ice_candidate(self, content: dict):
        if self.pc is None:
            return

        cand = content.get("candidate", None)

        if cand is None:
            try:
                await self.pc.addIceCandidate(None)
                logger.debug("[WebRTC] addIceCandidate(None) end user=%s session=%s", self.user.id, self.session_id)
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

            logger.debug(
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

    # CLEANUP

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

        if self._stats_task is not None:
            self._stats_task.cancel()
            self._stats_task = None

        if self._asr_started:
            try:
                asr_stream_manager.stop_stream(self.session_id, self.user.id)
            except Exception:
                logger.exception("[WebRTC] stop_stream failed (cleanup) user=%s session=%s", self.user.id, self.session_id)
            self._asr_started = False

        # deregistra dall'hub
        try:
            self._hub.unregister_peer(self.user.id)
            maybe_cleanup_hub(str(self.session_id))
        except Exception:
            logger.exception("[AudioHub] unregister failed user=%s session=%s", self.user.id, self.session_id)

        if self._outbound_track is not None:
            try:
                self._outbound_track.close()
            except Exception:
                pass
            self._outbound_track = None

        if self.pc is not None:
            try:
                await self.pc.close()
            except Exception:
                pass
            self.pc = None

    # UTILITIES

    @database_sync_to_async
    def _is_session_member(self, session_id, user_id: int) -> bool:
        from apps.sessions.models import Session
        return Session.objects.filter(id=session_id, participants__user_id=user_id).exists()