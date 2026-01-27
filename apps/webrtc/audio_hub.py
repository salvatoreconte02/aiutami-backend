# apps/webrtc/audio_hub.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional

from .audio_tracks import ForwardingAudioTrack

logger = logging.getLogger(__name__)


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
        self.current_speaker_user_id: Optional[int] = None

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

    def set_speaker(self, user_id: Optional[int]) -> None:
        if self.current_speaker_user_id == user_id:
            return  # idempotent - no change
        self.current_speaker_user_id = user_id
        logger.info("[AudioHub] set speaker=%s session=%s", user_id, self.session_id)

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