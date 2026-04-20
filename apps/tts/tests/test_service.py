"""Tests for TTS service."""
import asyncio
from unittest.mock import MagicMock, patch
from django.test import TestCase, override_settings

from apps.tts.service import TTSResult, TTSService


class _AsyncByteIter:
    """Async iterator over a fixed list of byte chunks (mock for response.iter_bytes())."""
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


class _AsyncStreamCM:
    """Async context manager mock for client.audio.speech.with_streaming_response.create()."""
    def __init__(self, chunks, exc=None):
        self._chunks = chunks
        self._exc = exc

    async def __aenter__(self):
        if self._exc is not None:
            raise self._exc
        response = MagicMock()
        response.iter_bytes = lambda chunk_size=None: _AsyncByteIter(self._chunks)
        return response

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _build_async_client_mock(chunks=None, exc=None):
    """Build a mock AsyncOpenAI client whose streaming TTS yields `chunks`."""
    client = MagicMock()
    client.audio.speech.with_streaming_response.create = MagicMock(
        return_value=_AsyncStreamCM(chunks or [], exc=exc)
    )
    return client


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

    @patch("apps.tts.service.AsyncOpenAI")
    def test_synthesize_stream_success(self, mock_async_openai_cls):
        """TTS streaming success: chunk arrivano a 48kHz, OpenAI chiamato con args giusti."""
        # 100ms @ 24kHz mono 16-bit = 2400 sample = 4800 byte, divisi in 2 chunk
        chunks_in = [b"\x00\x01" * 1200, b"\x00\x01" * 1200]
        mock_async_openai_cls.return_value = _build_async_client_mock(chunks=chunks_in)

        async def _run():
            service = TTSService()
            chunks_received = []

            async def on_chunk(pcm, samples, sample_rate):
                chunks_received.append((pcm, samples, sample_rate))

            result = await service.synthesize_stream("Ciao mondo", on_chunk)
            self.assertTrue(result.success, msg=f"error: {result.error}")
            self.assertIsNone(result.error)
            self.assertGreater(len(chunks_received), 0)
            for _, _, sample_rate in chunks_received:
                self.assertEqual(sample_rate, 48000)

            create_mock = mock_async_openai_cls.return_value.audio.speech.with_streaming_response.create
            create_mock.assert_called_once()
            call_kwargs = create_mock.call_args.kwargs
            self.assertEqual(call_kwargs["model"], "gpt-4o-mini-tts")
            self.assertEqual(call_kwargs["voice"], "onyx")
            self.assertEqual(call_kwargs["input"], "Ciao mondo")
            self.assertEqual(call_kwargs["response_format"], "pcm")

        asyncio.get_event_loop().run_until_complete(_run())

    @patch("apps.tts.service.AsyncOpenAI")
    def test_synthesize_stream_failure(self, mock_async_openai_cls):
        """TTS error: la connessione streaming solleva un'eccezione."""
        mock_async_openai_cls.return_value = _build_async_client_mock(
            exc=Exception("Connection failed")
        )

        async def _run():
            service = TTSService()

            async def on_chunk(pcm, samples, sample_rate):
                pass

            result = await service.synthesize_stream("Test", on_chunk)
            self.assertFalse(result.success)
            self.assertIsNotNone(result.error)
            self.assertIn("exception", result.error)

        asyncio.get_event_loop().run_until_complete(_run())

    @patch("apps.tts.service.AsyncOpenAI")
    def test_synthesize_stream_empty_audio(self, mock_async_openai_cls):
        """TTS quando lo stream non emette alcun byte: empty_audio."""
        mock_async_openai_cls.return_value = _build_async_client_mock(chunks=[])

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
        pcm_24k = bytes(range(200))
        pcm_48k = TTSService._resample_24k_to_48k(pcm_24k)
        self.assertEqual(len(pcm_48k), 400)

    def test_resample_24k_to_48k_empty(self):
        self.assertEqual(TTSService._resample_24k_to_48k(b""), b"")

    def test_resample_chunk_continuity_across_chunks(self):
        """Concatenare il resample di due chunk con prev_last produce un output
        coerente: nessun salto al bordo perché il primo sample del secondo
        output è la media tra l'ultimo input del primo chunk e il primo del secondo.
        """
        import numpy as np

        # Due chunk consecutivi con valori monotonicamente crescenti per
        # rendere visibile un eventuale salto al bordo.
        pcm_a = np.array([100, 200, 300, 400], dtype=np.int16).tobytes()
        pcm_b = np.array([500, 600, 700, 800], dtype=np.int16).tobytes()

        out_a, prev = TTSService._resample_chunk_24k_to_48k(pcm_a, None)
        out_b, _ = TTSService._resample_chunk_24k_to_48k(pcm_b, prev)

        # prev_last dopo il primo chunk = ultimo sample input del primo chunk
        self.assertEqual(prev, 400)

        # Primo sample del secondo chunk in output = media tra prev (400) e 500 = 450
        first_out_b = np.frombuffer(out_b[:2], dtype=np.int16)[0]
        self.assertEqual(first_out_b, 450)

        # Lunghezze: ogni chunk produce 2x sample (8 sample = 16 byte)
        self.assertEqual(len(out_a), 16)
        self.assertEqual(len(out_b), 16)
