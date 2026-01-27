"""Tests for AudioHub AI integration."""
import pytest
from unittest.mock import MagicMock, patch
from apps.webrtc.audio_hub import (
    SessionAudioHub,
    AI_MODERATOR_ID,
    get_hub,
)


class TestAudioHubAI:
    """Test AI moderator integration in AudioHub."""

    def test_ai_moderator_id_constant(self):
        """AI_MODERATOR_ID should be a reserved identifier."""
        assert AI_MODERATOR_ID == "__AI_MODERATOR__"

    def test_init_ai_track_creates_track(self):
        """init_ai_track should create a ForwardingAudioTrack."""
        hub = SessionAudioHub("test-session")

        with patch("apps.webrtc.audio_hub.ForwardingAudioTrack") as MockTrack:
            mock_track = MagicMock()
            MockTrack.return_value = mock_track

            track = hub.init_ai_track()

            assert track == mock_track
            MockTrack.assert_called_once()

    def test_init_ai_track_idempotent(self):
        """init_ai_track should return same track on subsequent calls."""
        hub = SessionAudioHub("test-session")

        with patch("apps.webrtc.audio_hub.ForwardingAudioTrack") as MockTrack:
            mock_track = MagicMock()
            MockTrack.return_value = mock_track

            track1 = hub.init_ai_track()
            track2 = hub.init_ai_track()

            assert track1 is track2
            MockTrack.assert_called_once()  # Only one creation

    def test_set_speaker_accepts_ai_moderator(self):
        """set_speaker should accept AI_MODERATOR_ID."""
        hub = SessionAudioHub("test-session")

        hub.set_speaker(AI_MODERATOR_ID)

        assert hub.current_speaker_user_id == AI_MODERATOR_ID

    def test_inject_ai_audio_when_ai_speaking(self):
        """inject_ai_audio should enqueue when AI is speaker."""
        hub = SessionAudioHub("test-session")

        with patch("apps.webrtc.audio_hub.ForwardingAudioTrack") as MockTrack:
            mock_track = MagicMock()
            MockTrack.return_value = mock_track

            hub.init_ai_track()
            hub.set_speaker(AI_MODERATOR_ID)

            pcm_chunk = b"\x00" * 1920
            hub.inject_ai_audio(pcm_chunk, 960, 48000)

            mock_track.enqueue.assert_called_once_with(pcm_chunk, 960, 48000)

    def test_inject_ai_audio_ignored_when_not_speaking(self):
        """inject_ai_audio should be ignored when AI is not speaker."""
        hub = SessionAudioHub("test-session")

        with patch("apps.webrtc.audio_hub.ForwardingAudioTrack") as MockTrack:
            mock_track = MagicMock()
            MockTrack.return_value = mock_track

            hub.init_ai_track()
            hub.set_speaker(123)  # Human speaker

            pcm_chunk = b"\x00" * 1920
            hub.inject_ai_audio(pcm_chunk, 960, 48000)

            mock_track.enqueue.assert_not_called()

    def test_inject_ai_audio_ignored_without_track(self):
        """inject_ai_audio should be ignored if track not initialized."""
        hub = SessionAudioHub("test-session")
        hub.set_speaker(AI_MODERATOR_ID)

        # Should not raise
        hub.inject_ai_audio(b"\x00" * 1920, 960, 48000)


class TestAudioHubForwarding:
    """Test audio forwarding with AI moderator."""

    def test_get_ai_track_for_peer_when_ai_speaking(self):
        """When AI is speaking, peers should receive AI track."""
        hub = SessionAudioHub("test-session")

        # Register a human peer
        mock_human_track = MagicMock()
        hub.register_peer(123, mock_human_track)

        with patch("apps.webrtc.audio_hub.ForwardingAudioTrack") as MockTrack:
            mock_ai_track = MagicMock()
            MockTrack.return_value = mock_ai_track

            hub.init_ai_track()
            hub.set_speaker(AI_MODERATOR_ID)

            # Get outbound track for peer 123 should be AI track
            track = hub.get_outbound_track_for_peer(123)

            assert track == mock_ai_track

    def test_get_human_track_for_peer_when_human_speaking(self):
        """When human is speaking, other peers should receive human's track."""
        hub = SessionAudioHub("test-session")

        # Register two human peers
        mock_speaker_track = MagicMock()
        mock_listener_track = MagicMock()
        hub.register_peer(100, mock_speaker_track)
        hub.register_peer(200, mock_listener_track)

        hub.set_speaker(100)

        # Peer 200 should receive speaker 100's track
        track = hub.get_outbound_track_for_peer(200)

        # Track comes from speaker (100), not listener
        assert track == mock_speaker_track
