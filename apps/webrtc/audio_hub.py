# apps/webrtc/audio_hub.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Union

from .audio_tracks import ForwardingAudioTrack

logger = logging.getLogger(__name__)

# Reserved ID for AI Moderator virtual peer
AI_MODERATOR_ID = "__AI_MODERATOR__"


@dataclass
class PeerAudioState:
    user_id: int
    outbound_track: ForwardingAudioTrack


class SessionAudioHub:
    """
    Hub in memoria per una sessione.
    - mantiene i peer connessi (user_id -> outbound_track)
    - mantiene lo speaker corrente (user_id oppure None)
    - inoltra i frame dello speaker a tutti gli altri (forward, non mix)
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.peers: Dict[int, PeerAudioState] = {}
        self.current_speaker_user_id: Optional[Union[int, str]] = None  # int for humans, str for AI
        self._ai_track: Optional[ForwardingAudioTrack] = None

    def register_peer(self, user_id: int, outbound_track: ForwardingAudioTrack) -> None:
        self.peers[user_id] = PeerAudioState(user_id=user_id, outbound_track=outbound_track)
        logger.info("[AudioHub] register peer user=%s session=%s peers=%s", user_id, self.session_id, len(self.peers))

    def unregister_peer(self, user_id: int) -> None:
        st = self.peers.pop(user_id, None)
        if st:
            try:
                st.outbound_track.close()
            except Exception:
                pass
        logger.info("[AudioHub] unregister peer user=%s session=%s peers=%s", user_id, self.session_id, len(self.peers))

        if self.current_speaker_user_id == user_id:
            self.current_speaker_user_id = None

    def set_speaker(self, user_id: Optional[Union[int, str]]) -> None:
        if self.current_speaker_user_id == user_id:
            return  # idempotent - no change
        self.current_speaker_user_id = user_id
        logger.info("[AudioHub] set speaker=%s session=%s", user_id, self.session_id)

    def init_ai_track(self) -> ForwardingAudioTrack:
        """Crea il track virtuale per il moderatore AI."""
        if self._ai_track is None:
            self._ai_track = ForwardingAudioTrack(
                user_id=0,  # Virtual user
                session_id=self.session_id
            )
            logger.info("[AudioHub] AI track initialized session=%s", self.session_id)
        return self._ai_track

    def inject_ai_audio(self, pcm_chunk: bytes, samples: int, sample_rate: int) -> None:
        """Inietta audio TTS direttamente nei track di tutti i peer."""
        if self.current_speaker_user_id != AI_MODERATOR_ID:
            return

        # Forward diretto a tutti i peer (come forward_pcm_from_speaker)
        for uid, peer in self.peers.items():
            peer.outbound_track.enqueue(pcm=pcm_chunk, samples=samples, sample_rate=sample_rate)

    def get_outbound_track_for_peer(self, user_id: int) -> Optional[ForwardingAudioTrack]:
        """
        Ritorna il track da cui il peer user_id dovrebbe ricevere audio.

        - Se AI sta parlando: ritorna _ai_track
        - Se un umano sta parlando: ritorna il track di quell'umano (se diverso da user_id)
        - Altrimenti: None
        """
        if self.current_speaker_user_id == AI_MODERATOR_ID:
            return self._ai_track
        elif self.current_speaker_user_id is not None and self.current_speaker_user_id != user_id:
            speaker_state = self.peers.get(self.current_speaker_user_id)
            if speaker_state:
                return speaker_state.outbound_track
        return None

    def forward_pcm_from_speaker(self, from_user_id: int, pcm: bytes, samples: int, sample_rate: int) -> None:
        """
        Inoltra PCM (s16 mono) a tutti tranne lo speaker.
        Viene chiamato dal consumer che riceve i frame.
        """
        if self.current_speaker_user_id != from_user_id:
            return

        for uid, peer in self.peers.items():
            if uid == from_user_id:
                continue  # no echo
            peer.outbound_track.enqueue(pcm=pcm, samples=samples, sample_rate=sample_rate)


# Registry globale (MVP)
_HUBS: Dict[str, SessionAudioHub] = {}


def get_hub(session_id: str) -> SessionAudioHub:
    sid = str(session_id)
    hub = _HUBS.get(sid)
    if hub is None:
        hub = SessionAudioHub(session_id=sid)
        _HUBS[sid] = hub
    return hub


def maybe_cleanup_hub(session_id: str) -> None:
    sid = str(session_id)
    hub = _HUBS.get(sid)
    if not hub:
        return
    if len(hub.peers) == 0:
        _HUBS.pop(sid, None)
        logger.info("[AudioHub] cleanup hub session=%s", sid)