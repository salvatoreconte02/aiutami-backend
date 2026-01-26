# apps/webrtc/audio_tracks.py
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional

import av
from aiortc.mediastreams import AudioStreamTrack

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PcmChunk:
    pcm: bytes
    samples: int
    sample_rate: int


class ForwardingAudioTrack(AudioStreamTrack):
    """
    Traccia audio server->client.

    - Riceve chunk PCM (s16 mono) tramite enqueue()
    - Se non arrivano chunk, produce "silenzio" per tenere stabile la pipeline
    - Il formato usato è coerente con il resto della vostra pipeline: s16 / mono / 48k
      (ma sample_rate è preso dal chunk, quindi è robusto).

    Nota: questa è una traccia "forwarder" (non mixer). L'hub decide cosa inoltrare e a chi.
    """

    kind = "audio"

    def __init__(
        self,
        *,
        user_id: int,
        session_id: str,
        sample_rate_default: int = 48000,
        frame_time_ms: int = 20,
        queue_maxsize: int = 200,
    ) -> None:
        super().__init__()
        self.user_id = user_id
        self.session_id = session_id

        self._queue: asyncio.Queue[PcmChunk] = asyncio.Queue(maxsize=queue_maxsize)
        self._closed = False

        self._sample_rate_default = sample_rate_default
        self._frame_time_ms = frame_time_ms

        # PTS tracking
        self._pts: int = 0

    def close(self) -> None:
        self._closed = True
        try:
            # svuota la coda (best effort)
            while not self._queue.empty():
                self._queue.get_nowait()
        except Exception:
            pass

    def enqueue(self, pcm: bytes, samples: int, sample_rate: int) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait(PcmChunk(pcm=pcm, samples=samples, sample_rate=sample_rate))
        except asyncio.QueueFull:
            # Drop controllato: in real-time è preferibile scartare piuttosto che accumulare latenza
            logger.warning(
                "[AudioTrack] queue full -> drop chunk user=%s session=%s",
                self.user_id,
                self.session_id,
            )

    async def recv(self) -> av.AudioFrame:
        if self._closed:
            # se chiusa, restituiamo comunque silenzio per un breve periodo
            await asyncio.sleep(0.02)

        # prova a leggere un chunk, altrimenti genera silenzio
        chunk: Optional[PcmChunk] = None
        try:
            chunk = await asyncio.wait_for(self._queue.get(), timeout=self._frame_time_ms / 1000)
        except asyncio.TimeoutError:
            chunk = None
        except Exception:
            chunk = None

        if chunk is None:
            # genera silenzio 20ms (o frame_time_ms)
            sample_rate = self._sample_rate_default
            samples = int(sample_rate * (self._frame_time_ms / 1000.0))
            pcm = b"\x00\x00" * samples  # s16 mono
        else:
            sample_rate = chunk.sample_rate or self._sample_rate_default
            samples = chunk.samples
            pcm = chunk.pcm

        frame = av.AudioFrame(format="s16", layout="mono", samples=samples)
        frame.sample_rate = sample_rate
        frame.planes[0].update(pcm)

        frame.pts = self._pts
        frame.time_base = Fraction(1, sample_rate)
        self._pts += samples

        return frame