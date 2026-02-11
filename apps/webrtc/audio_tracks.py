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
    - Produce SEMPRE frame di durata fissa (frame_time_ms) riframando i chunk in arrivo
    - Se non arrivano chunk a sufficienza, pad con silenzio
    - Output stabile: s16 / mono / sample_rate_default (tipicamente 48k)
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

        self._sample_rate_default = int(sample_rate_default)
        self._frame_time_ms = int(frame_time_ms)

        # Output framing fisso (s16 mono)
        self._out_sample_rate = self._sample_rate_default
        self._samples_per_frame = int(self._out_sample_rate * (self._frame_time_ms / 1000.0))
        if self._samples_per_frame <= 0:
            self._samples_per_frame = 960  # fallback per 48k/20ms

        self._bytes_per_sample = 2  # s16
        self._channels = 1          # mono
        self._bytes_per_frame = self._samples_per_frame * self._channels * self._bytes_per_sample

        # Buffer per riframare chunk variabili in frame fissi
        self._bytebuf = bytearray()

        # tracking PTS
        self._pts: int = 0

        # supporto drain fine-stream
        self._eos = False
        self._drained_event = asyncio.Event()

    def close(self) -> None:
        self._closed = True
        try:
            while not self._queue.empty():
                self._queue.get_nowait()
        except Exception:
            pass
        try:
            self._bytebuf.clear()
        except Exception:
            pass

    def mark_end_of_stream(self) -> None:
        """Signal that no more audio chunks will arrive."""
        self._eos = True

    async def wait_until_drained(self, timeout: float = 10.0) -> None:
        """Wait for buffer to empty after end-of-stream."""
        if not self._eos:
            return
        try:
            await asyncio.wait_for(self._drained_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "[AudioTrack] drain timeout user=%s session=%s",
                self.user_id, self.session_id,
            )

    def _reset_eos(self) -> None:
        """Reset EOS state when new audio arrives."""
        self._eos = False
        self._drained_event.clear()

    def enqueue(self, pcm: bytes, samples: int, sample_rate: int) -> None:
        self._reset_eos()
        if self._closed:
            return
        if not pcm:
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
            # se chiusa, manteniamo un minimo di pacing
            await asyncio.sleep(self._frame_time_ms / 1000.0)

        # 1) tenta di prendere almeno un chunk entro il frame_time
        try:
            chunk = await asyncio.wait_for(self._queue.get(), timeout=self._frame_time_ms / 1000.0)
            if chunk and chunk.pcm:
                self._bytebuf.extend(chunk.pcm)
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass

        # 2) drena velocemente eventuali chunk già disponibili (best effort)
        try:
            while len(self._bytebuf) < self._bytes_per_frame:
                chunk2 = self._queue.get_nowait()
                if chunk2 and chunk2.pcm:
                    self._bytebuf.extend(chunk2.pcm)
        except asyncio.QueueEmpty:
            pass
        except Exception:
            pass

        # 3) evita accumulo eccessivo (riduce latenza se qualcosa va storto)
        #    tieni al massimo ~1s di audio bufferizzato
        max_buf = self._bytes_per_frame * int(1000 / self._frame_time_ms)
        if len(self._bytebuf) > max_buf:
            # drop dell'audio più vecchio
            drop = len(self._bytebuf) - max_buf
            del self._bytebuf[:drop]

        # 4) estrai esattamente un frame; se manca, pad con silenzio
        if len(self._bytebuf) >= self._bytes_per_frame:
            pcm_out = bytes(self._bytebuf[:self._bytes_per_frame])
            del self._bytebuf[:self._bytes_per_frame]
        else:
            had = len(self._bytebuf)
            missing = self._bytes_per_frame - had
            pcm_out = bytes(self._bytebuf) + (b"\x00" * missing)
            self._bytebuf.clear()
            logger.debug(
                "[AudioTrack] Buffer underrun: had=%d needed=%d missing=%d user=%s",
                had, self._bytes_per_frame, missing, self.user_id,
            )

        # 5) segnala drain se EOS e buffer esaurito
        if self._eos and self._queue.empty() and len(self._bytebuf) < self._bytes_per_frame:
            self._drained_event.set()

        frame = av.AudioFrame(format="s16", layout="mono", samples=self._samples_per_frame)
        frame.sample_rate = self._out_sample_rate
        frame.planes[0].update(pcm_out)

        frame.pts = self._pts
        frame.time_base = Fraction(1, self._out_sample_rate)
        self._pts += self._samples_per_frame

        return frame