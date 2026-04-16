"""Tests for TTS service."""
import asyncio
from unittest.mock import MagicMock, patch
from django.test import TestCase, override_settings

from apps.tts.service import TTSResult, TTSService


class TestTTSResult(TestCase):
    """Test TTSResult dataclass."""

    def test_success_result(self):
        result = TTSResult(success=True, duration_ms=1500, error=None)
        self.assertTrue(result.success)
        self.assertEqual(result.duration_ms, 1500)
        self.assertIsNone(result.error)

    def test_failure_result(self):
        result = TTSResult(success=False, duration_ms=None, error="timeout")
        self.assertFalse(result.success)
        self.assertIsNone(result.duration_ms)
        self.assertEqual(result.error, "timeout")


@override_settings(
    OPENAI_API_KEY="test-key",
    OPENAI_TTS_MODEL="gpt-4o-mini-tts",
    OPENAI_TTS_VOICE="onyx",
)
class TestTTSService(TestCase):
    """Test TTSService."""

    @patch("apps.tts.service.OpenAI")
    def test_synthesize_stream_success(self, mock_openai_cls):
        """Test successful TTS synthesis con resample 24k→48k."""
        # 0.1s @ 24kHz mono 16-bit = 2400 samples = 4800 bytes
        mock_response = MagicMock()
        mock_response.read.return_value = b"\x00\x01" * 2400

        mock_client = MagicMock()
        mock_client.audio.speech.create.return_value = mock_response
        mock_openai_cls.return_value = mock_client

        async def _run():
            service = TTSService()
            chunks_received = []

            async def on_chunk(pcm, samples, sample_rate):
                chunks_received.append((pcm, samples, sample_rate))

            result = await service.synthesize_stream("Ciao mondo", on_chunk)
            self.assertTrue(result.success)
            self.assertIsNone(result.error)
            # Verifica che siano arrivati chunk a 48kHz
            self.assertTrue(len(chunks_received) > 0)
            for _, _, sample_rate in chunks_received:
                self.assertEqual(sample_rate, 48000)

            # Verifica che OpenAI sia stato chiamato correttamente
            mock_client.audio.speech.create.assert_called_once()
            call_kwargs = mock_client.audio.speech.create.call_args.kwargs
            self.assertEqual(call_kwargs["model"], "gpt-4o-mini-tts")
            self.assertEqual(call_kwargs["voice"], "onyx")
            self.assertEqual(call_kwargs["input"], "Ciao mondo")
            self.assertEqual(call_kwargs["response_format"], "pcm")

        asyncio.get_event_loop().run_until_complete(_run())

    @patch("apps.tts.service.OpenAI")
    def test_synthesize_stream_failure(self, mock_openai_cls):
        """Test TTS synthesis failure (API error)."""
        mock_client = MagicMock()
        mock_client.audio.speech.create.side_effect = Exception("Connection failed")
        mock_openai_cls.return_value = mock_client

        async def _run():
            service = TTSService()

            async def on_chunk(pcm, samples, sample_rate):
                pass

            result = await service.synthesize_stream("Test", on_chunk)
            self.assertFalse(result.success)
            self.assertIsNotNone(result.error)
            self.assertIn("exception", result.error)

        asyncio.get_event_loop().run_until_complete(_run())

    @patch("apps.tts.service.OpenAI")
    def test_synthesize_stream_empty_audio(self, mock_openai_cls):
        """Test TTS quando la risposta è audio vuoto."""
        mock_response = MagicMock()
        mock_response.read.return_value = b""

        mock_client = MagicMock()
        mock_client.audio.speech.create.return_value = mock_response
        mock_openai_cls.return_value = mock_client

        async def _run():
            service = TTSService()

            async def on_chunk(pcm, samples, sample_rate):
                pass

            result = await service.synthesize_stream("Test", on_chunk)
            self.assertFalse(result.success)
            self.assertEqual(result.error, "empty_audio")

        asyncio.get_event_loop().run_until_complete(_run())

    def test_synthesize_stream_empty_text(self):
        """Test TTS with empty text returns error."""
        async def _run():
            service = TTSService()

            async def on_chunk(pcm, samples, sample_rate):
                pass

            result = await service.synthesize_stream("", on_chunk)
            self.assertFalse(result.success)
            self.assertEqual(result.error, "empty_text")

        asyncio.get_event_loop().run_until_complete(_run())

    def test_resample_24k_to_48k_doubles_samples(self):
        """Resample 24kHz → 48kHz raddoppia il numero di sample."""
        # 100 sample int16 = 200 bytes
        pcm_24k = bytes(range(200))
        pcm_48k = TTSService._resample_24k_to_48k(pcm_24k)
        # 48kHz output deve avere il doppio dei sample (quindi il doppio dei bytes)
        self.assertEqual(len(pcm_48k), 400)

    def test_resample_24k_to_48k_empty(self):
        self.assertEqual(TTSService._resample_24k_to_48k(b""), b"")
