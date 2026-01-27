"""Tests for TTS service."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from apps.tts.service import TTSResult, TTSService


class TestTTSResult:
    """Test TTSResult dataclass."""

    def test_success_result(self):
        result = TTSResult(success=True, duration_ms=1500, error=None)
        assert result.success is True
        assert result.duration_ms == 1500
        assert result.error is None

    def test_failure_result(self):
        result = TTSResult(success=False, duration_ms=None, error="timeout")
        assert result.success is False
        assert result.duration_ms is None
        assert result.error == "timeout"


class TestTTSService:
    """Test TTSService."""

    @pytest.fixture
    def mock_speech_config(self):
        with patch("apps.tts.service.speechsdk") as mock_sdk:
            yield mock_sdk

    @pytest.mark.asyncio
    async def test_synthesize_stream_success(self, mock_speech_config):
        """Test successful TTS synthesis."""
        mock_sdk = mock_speech_config

        # Setup mock synthesizer
        mock_synthesizer = MagicMock()
        mock_sdk.SpeechSynthesizer.return_value = mock_synthesizer

        # Mock audio data result
        mock_result = MagicMock()
        mock_result.reason = mock_sdk.ResultReason.SynthesizingAudioCompleted
        mock_result.audio_data = b"\x00" * 9600  # 100ms at 48kHz mono 16-bit
        mock_result.audio_duration.total_seconds.return_value = 0.1
        mock_synthesizer.speak_text_async.return_value.get.return_value = mock_result

        # Mock audio config
        mock_sdk.audio.AudioOutputConfig.return_value = MagicMock()

        service = TTSService()
        chunks_received = []

        async def on_chunk(pcm: bytes, samples: int, sample_rate: int):
            chunks_received.append((pcm, samples, sample_rate))

        result = await service.synthesize_stream("Ciao mondo", on_chunk)

        assert result.success is True
        assert result.error is None

    @pytest.mark.asyncio
    async def test_synthesize_stream_failure(self, mock_speech_config):
        """Test TTS synthesis failure."""
        mock_sdk = mock_speech_config

        # Setup mock synthesizer
        mock_synthesizer = MagicMock()
        mock_sdk.SpeechSynthesizer.return_value = mock_synthesizer

        # Mock canceled result
        mock_result = MagicMock()
        mock_result.reason = mock_sdk.ResultReason.Canceled
        mock_cancellation = MagicMock()
        mock_cancellation.reason = mock_sdk.CancellationReason.Error
        mock_cancellation.error_details = "Connection failed"
        mock_sdk.CancellationDetails.from_result.return_value = mock_cancellation
        mock_synthesizer.speak_text_async.return_value.get.return_value = mock_result

        service = TTSService()

        async def on_chunk(pcm: bytes, samples: int, sample_rate: int):
            pass

        result = await service.synthesize_stream("Test", on_chunk)

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_synthesize_stream_empty_text(self, mock_speech_config):
        """Test TTS with empty text returns error."""
        service = TTSService()

        async def on_chunk(pcm: bytes, samples: int, sample_rate: int):
            pass

        result = await service.synthesize_stream("", on_chunk)

        assert result.success is False
        assert result.error == "empty_text"
