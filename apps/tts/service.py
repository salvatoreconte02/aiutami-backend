"""
TTS Service - OpenAI Text-to-Speech per il moderatore AI.

Fornisce sintesi vocale streaming per permettere al moderatore AI
di parlare agli utenti via WebRTC. Risample 24kHz→48kHz per
compatibilità con l'audio hub.
"""
from dataclasses import dataclass
from typing import Callable, Awaitable, Optional, Tuple
import asyncio
import logging

import numpy as np
from django.conf import settings
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


@dataclass
class TTSResult:
    """Risultato della sintesi TTS."""
    success: bool
    duration_ms: Optional[int]
    error: Optional[str]


# OpenAI TTS restituisce PCM 24kHz 16-bit mono quando response_format="pcm"
INPUT_SAMPLE_RATE = 24000
# Audio hub del backend lavora a 48kHz
OUTPUT_SAMPLE_RATE = 48000
BYTES_PER_SAMPLE = 2
CHANNELS = 1

# Buffer di lettura dallo stream HTTP. Più piccolo = primo chunk audio più rapido,
# meno chunk = meno overhead. 2048 bytes = 1024 sample 24k = ~42ms input.
STREAM_READ_CHUNK_SIZE = 2048

# Granularità di emissione verso AudioHub: 20ms = packet WebRTC standard.
OUTPUT_FRAME_SIZE = OUTPUT_SAMPLE_RATE * BYTES_PER_SAMPLE * CHANNELS // 50
OUTPUT_FRAME_DURATION_SEC = OUTPUT_FRAME_SIZE / (OUTPUT_SAMPLE_RATE * BYTES_PER_SAMPLE * CHANNELS)


class TTSService:
    """
    OpenAI TTS con streaming end-to-end.

    Apre una connessione streaming a OpenAI, riceve PCM 24kHz mentre
    viene generato, lo upsampla a 48kHz e lo invia all'AudioHub in frame
    da 20ms con pacing realtime. Riduce il time-to-first-audio rispetto
    al batch (che attendeva l'intero file prima di iniziare il playback).
    """

    def __init__(self):
        self._api_key = settings.OPENAI_API_KEY
        self._model = settings.OPENAI_TTS_MODEL
        self._voice = settings.OPENAI_TTS_VOICE

    async def synthesize_stream(
        self,
        text: str,
        on_audio_chunk: Callable[[bytes, int, int], Awaitable[None]]
    ) -> TTSResult:
        """
        Sintetizza testo in audio, streaming chunk per chunk.

        Args:
            text: Testo da sintetizzare
            on_audio_chunk: Callback(pcm_data, samples, sample_rate) per ogni chunk

        Returns:
            TTSResult con success, duration_ms, error
        """
        if not text or not text.strip():
            return TTSResult(success=False, duration_ms=None, error="empty_text")

        try:
            return await self._do_synthesis(text, on_audio_chunk)
        except Exception as e:
            logger.exception(f"TTS synthesis error: {e}")
            return TTSResult(success=False, duration_ms=None, error=f"exception: {e}")

    async def _do_synthesis(
        self,
        text: str,
        on_audio_chunk: Callable[[bytes, int, int], Awaitable[None]]
    ) -> TTSResult:
        """Esegue la sintesi con OpenAI TTS in streaming."""
        client = AsyncOpenAI(api_key=self._api_key)

        prev_last_sample: Optional[int] = None
        residual_48k = bytearray()
        total_output_bytes = 0

        async with client.audio.speech.with_streaming_response.create(
            model=self._model,
            voice=self._voice,
            input=text,
            response_format="pcm",
        ) as response:
            async for chunk_24k in response.iter_bytes(chunk_size=STREAM_READ_CHUNK_SIZE):
                if not chunk_24k:
                    continue

                chunk_48k, prev_last_sample = self._resample_chunk_24k_to_48k(
                    chunk_24k, prev_last_sample
                )
                if not chunk_48k:
                    continue

                residual_48k.extend(chunk_48k)

                # Emette frame da 20ms con pacing realtime (~90% per evitare underrun).
                while len(residual_48k) >= OUTPUT_FRAME_SIZE:
                    frame = bytes(residual_48k[:OUTPUT_FRAME_SIZE])
                    del residual_48k[:OUTPUT_FRAME_SIZE]
                    await on_audio_chunk(
                        frame, OUTPUT_FRAME_SIZE // BYTES_PER_SAMPLE, OUTPUT_SAMPLE_RATE
                    )
                    total_output_bytes += OUTPUT_FRAME_SIZE
                    await asyncio.sleep(OUTPUT_FRAME_DURATION_SEC * 0.9)

        # Emette eventuale frame residuo finale (< 20ms)
        if residual_48k:
            frame = bytes(residual_48k)
            await on_audio_chunk(
                frame, len(frame) // BYTES_PER_SAMPLE, OUTPUT_SAMPLE_RATE
            )
            total_output_bytes += len(frame)

        if total_output_bytes == 0:
            return TTSResult(success=False, duration_ms=None, error="empty_audio")

        duration_ms = int(
            total_output_bytes / (OUTPUT_SAMPLE_RATE * BYTES_PER_SAMPLE * CHANNELS) * 1000
        )
        return TTSResult(success=True, duration_ms=duration_ms, error=None)

    @staticmethod
    def _resample_chunk_24k_to_48k(
        pcm_bytes: bytes, prev_last_sample: Optional[int]
    ) -> Tuple[bytes, Optional[int]]:
        """
        Upsample 2x con interpolazione lineare per uno stream chunked.

        Mantiene continuità ai bordi usando l'ultimo sample del chunk
        precedente: il primo sample di output di ogni chunk è la media
        tra prev_last_sample e il primo sample del chunk corrente.

        Per il primo chunk (prev_last_sample=None) duplica il primo sample
        come "predecessore virtuale" — equivalente a non interpolare il primo
        bordo, dato che non c'è discontinuità da nascondere.

        Returns:
            (output_pcm_48k_bytes, last_input_sample) — passare il secondo
            come prev_last_sample alla chiamata successiva.
        """
        if not pcm_bytes:
            return b"", prev_last_sample

        pcm_in = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        n = len(pcm_in)
        if n == 0:
            return b"", prev_last_sample

        prev = float(prev_last_sample) if prev_last_sample is not None else float(pcm_in[0])

        # Estensione: [prev, x0, x1, ..., x(n-1)] su posizioni [0, 1, ..., n].
        # Output: 2n sample alle posizioni [0.5, 1.0, 1.5, ..., n].
        # Risultato: [(prev+x0)/2, x0, (x0+x1)/2, x1, ..., (x(n-2)+x(n-1))/2, x(n-1)].
        extended = np.empty(n + 1, dtype=np.float32)
        extended[0] = prev
        extended[1:] = pcm_in

        x_old = np.arange(n + 1, dtype=np.float32)
        x_new = np.linspace(0.5, float(n), num=2 * n, dtype=np.float32)
        pcm_out = np.interp(x_new, x_old, extended)

        new_prev = int(pcm_in[-1])
        pcm_out_int = np.clip(pcm_out, -32768, 32767).astype(np.int16)
        return pcm_out_int.tobytes(), new_prev

    @staticmethod
    def _resample_24k_to_48k(pcm_bytes: bytes) -> bytes:
        """Upsample PCM 16-bit mono da 24kHz a 48kHz, buffer singolo (no streaming)."""
        out, _ = TTSService._resample_chunk_24k_to_48k(pcm_bytes, None)
        return out
