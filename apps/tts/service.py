"""
TTS Service - OpenAI Text-to-Speech per il moderatore AI.

Fornisce sintesi vocale streaming per permettere al moderatore AI
di parlare agli utenti via WebRTC. Risample 24kHz→48kHz per
compatibilità con l'audio hub.
"""
from dataclasses import dataclass
from typing import Callable, Awaitable, Optional
import asyncio
import logging

import numpy as np
from django.conf import settings
from openai import OpenAI

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


class TTSService:
    """
    OpenAI TTS con streaming audio.

    Sintetizza testo in audio PCM 48kHz mono, compatibile con AudioHub.
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
        """Esegue la sintesi con OpenAI TTS."""
        client = OpenAI(api_key=self._api_key)

        # Chiamata bloccante in thread pool
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.audio.speech.create(
                model=self._model,
                voice=self._voice,
                input=text,
                response_format="pcm",
            ),
        )

        audio_data_24k = response.read()
        if not audio_data_24k:
            return TTSResult(success=False, duration_ms=None, error="empty_audio")

        # Resample 24kHz → 48kHz (upsample 2x con interpolazione lineare)
        audio_data = self._resample_24k_to_48k(audio_data_24k)

        # Durata calcolata dai bytes output
        duration_ms = int(
            len(audio_data) / (OUTPUT_SAMPLE_RATE * BYTES_PER_SAMPLE * CHANNELS) * 1000
        )

        # Invia audio in chunk con pacing per rispettare il timing reale
        chunk_size = OUTPUT_SAMPLE_RATE * BYTES_PER_SAMPLE * CHANNELS // 50  # 20ms
        chunk_duration_sec = chunk_size / (OUTPUT_SAMPLE_RATE * BYTES_PER_SAMPLE * CHANNELS)

        for i in range(0, len(audio_data), chunk_size):
            chunk = audio_data[i:i + chunk_size]
            samples = len(chunk) // BYTES_PER_SAMPLE
            await on_audio_chunk(chunk, samples, OUTPUT_SAMPLE_RATE)
            # Pacing: ~90% della durata per evitare underrun
            await asyncio.sleep(chunk_duration_sec * 0.9)

        return TTSResult(success=True, duration_ms=duration_ms, error=None)

    @staticmethod
    def _resample_24k_to_48k(pcm_bytes: bytes) -> bytes:
        """Upsample PCM 16-bit mono da 24kHz a 48kHz via interpolazione lineare."""
        if not pcm_bytes:
            return b""
        pcm_in = np.frombuffer(pcm_bytes, dtype=np.int16)
        if len(pcm_in) < 2:
            # Pochi sample: duplica semplicemente
            return np.repeat(pcm_in, 2).tobytes()
        x_old = np.arange(len(pcm_in), dtype=np.float32)
        x_new = np.linspace(0.0, float(len(pcm_in) - 1), num=len(pcm_in) * 2, dtype=np.float32)
        pcm_out = np.interp(x_new, x_old, pcm_in.astype(np.float32))
        return np.clip(pcm_out, -32768, 32767).astype(np.int16).tobytes()
