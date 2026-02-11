"""
TTS Service - Azure Speech Synthesis per il moderatore AI.

Fornisce sintesi vocale streaming per permettere al moderatore AI
di parlare agli utenti via WebRTC.
"""
from dataclasses import dataclass
from typing import Callable, Awaitable, Optional
import asyncio
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class TTSResult:
    """Risultato della sintesi TTS."""
    success: bool
    duration_ms: Optional[int]
    error: Optional[str]


try:
    import azure.cognitiveservices.speech as speechsdk
except ImportError:
    speechsdk = None


# Formato output: 48kHz mono 16-bit PCM (compatibile con audio hub)
OUTPUT_SAMPLE_RATE = 48000
BYTES_PER_SAMPLE = 2
CHANNELS = 1


class TTSService:
    """
    Azure Speech TTS con streaming audio.

    Sintetizza testo in audio PCM, compatibile con AudioHub.
    """

    def __init__(self):
        self._speech_key = settings.AZURE_SPEECH_KEY
        self._speech_region = settings.AZURE_SPEECH_REGION
        self._voice = getattr(settings, "AZURE_TTS_VOICE", "it-IT-DiegoNeural")

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

        if speechsdk is None:
            logger.error("Azure Speech SDK not installed")
            return TTSResult(success=False, duration_ms=None, error="sdk_not_installed")

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
        """Esegue la sintesi con Azure SDK."""
        # Configurazione speech
        speech_config = speechsdk.SpeechConfig(
            subscription=self._speech_key,
            region=self._speech_region
        )
        speech_config.speech_synthesis_voice_name = self._voice

        # Output format: 48kHz mono 16-bit PCM raw
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Raw48Khz16BitMonoPcm
        )

        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config,
            audio_config=None  # Gestione manuale dell'audio
        )

        # Esegui sintesi (blocking in thread pool)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: synthesizer.speak_text_async(text).get()
        )

        # Verifica risultato
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            audio_data = result.audio_data
            duration_ms = int(result.audio_duration.total_seconds() * 1000)

            # Invia audio in chunk con pacing per rispettare il timing reale
            if audio_data:
                chunk_size = OUTPUT_SAMPLE_RATE * BYTES_PER_SAMPLE * CHANNELS // 50  # chunk da 20ms
                chunk_duration_sec = chunk_size / (OUTPUT_SAMPLE_RATE * BYTES_PER_SAMPLE * CHANNELS)

                for i in range(0, len(audio_data), chunk_size):
                    chunk = audio_data[i:i + chunk_size]
                    samples = len(chunk) // BYTES_PER_SAMPLE
                    await on_audio_chunk(chunk, samples, OUTPUT_SAMPLE_RATE)
                    # Pacing: aspetta ~90% della durata del chunk per evitare underrun
                    await asyncio.sleep(chunk_duration_sec * 0.9)

            return TTSResult(success=True, duration_ms=duration_ms, error=None)

        elif result.reason == speechsdk.ResultReason.Canceled:
            cancellation = speechsdk.CancellationDetails.from_result(result)
            if cancellation.reason == speechsdk.CancellationReason.Error:
                error_msg = f"azure_error: {cancellation.error_details}"
                logger.error(f"TTS canceled: {error_msg}")
                return TTSResult(success=False, duration_ms=None, error=error_msg)
            else:
                return TTSResult(success=False, duration_ms=None, error="canceled")

        else:
            return TTSResult(success=False, duration_ms=None, error=f"unknown_reason: {result.reason}")
