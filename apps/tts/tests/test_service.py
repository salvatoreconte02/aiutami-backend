"""Tests for TTS service."""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
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
    AZURE_SPEECH_KEY="test-key",
    AZURE_SPEECH_REGION="test-region",
)
class TestTTSService(TestCase):
    """Test TTSService."""

    @patch("apps.tts.service.speechsdk")
    def test_synthesize_stream_success(self, mock_sdk):
        """Test successful TTS synthesis."""
        mock_synthesizer = MagicMock()
        mock_sdk.SpeechSynthesizer.return_value = mock_synthesizer

        mock_result = MagicMock()
        mock_result.reason = mock_sdk.ResultReason.SynthesizingAudioCompleted
        mock_result.audio_data = b"\x00" * 9600
        mock_result.audio_duration.total_seconds.return_value = 0.1
        mock_synthesizer.speak_text_async.return_value.get.return_value = mock_result

        mock_sdk.audio.AudioOutputConfig.return_value = MagicMock()

        async def _run():
            service = TTSService()
            chunks_received = []

            async def on_chunk(pcm, samples, sample_rate):
                chunks_received.append((pcm, samples, sample_rate))

            result = await service.synthesize_stream("Ciao mondo", on_chunk)
            self.assertTrue(result.success)
            self.assertIsNone(result.error)

        asyncio.get_event_loop().run_until_complete(_run())

    @patch("apps.tts.service.speechsdk")
    def test_synthesize_stream_failure(self, mock_sdk):
        """Test TTS synthesis failure."""
        mock_synthesizer = MagicMock()
        mock_sdk.SpeechSynthesizer.return_value = mock_synthesizer

        mock_result = MagicMock()
        mock_result.reason = mock_sdk.ResultReason.Canceled
        mock_cancellation = MagicMock()
        mock_cancellation.reason = mock_sdk.CancellationReason.Error
        mock_cancellation.error_details = "Connection failed"
        mock_sdk.CancellationDetails.from_result.return_value = mock_cancellation
        mock_synthesizer.speak_text_async.return_value.get.return_value = mock_result

        async def _run():
            service = TTSService()

            async def on_chunk(pcm, samples, sample_rate):
                pass

            result = await service.synthesize_stream("Test", on_chunk)
            self.assertFalse(result.success)
            self.assertIsNotNone(result.error)

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
