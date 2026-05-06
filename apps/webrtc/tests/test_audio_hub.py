"""Tests for AudioHub AI integration."""
import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

from apps.webrtc.audio_hub import (
    SessionAudioHub,
    AI_MODERATOR_ID,
    get_hub,
)


class TestAudioHubAI(unittest.TestCase):
    """Test AI moderator integration in AudioHub."""

    def test_ai_moderator_id_constant(self):
        """AI_MODERATOR_ID should be a reserved identifier."""
        self.assertEqual(AI_MODERATOR_ID, "__AI_MODERATOR__")

    def test_init_ai_track_creates_track(self):
        """init_ai_track should create a ForwardingAudioTrack."""
        hub = SessionAudioHub("test-session")

        with patch("apps.webrtc.audio_hub.ForwardingAudioTrack") as MockTrack:
            mock_track = MagicMock()
            MockTrack.return_value = mock_track

            track = hub.init_ai_track()

            self.assertEqual(track, mock_track)
            MockTrack.assert_called_once()

    def test_init_ai_track_idempotent(self):
        """init_ai_track should return same track on subsequent calls."""
        hub = SessionAudioHub("test-session")

        with patch("apps.webrtc.audio_hub.ForwardingAudioTrack") as MockTrack:
            mock_track = MagicMock()
            MockTrack.return_value = mock_track

            track1 = hub.init_ai_track()
            track2 = hub.init_ai_track()

            self.assertIs(track1, track2)
            MockTrack.assert_called_once()  # Only one creation

    def test_set_speaker_accepts_ai_moderator(self):
        """set_speaker should accept AI_MODERATOR_ID."""
        hub = SessionAudioHub("test-session")

        hub.set_speaker(AI_MODERATOR_ID)

        self.assertEqual(hub.current_speaker_user_id, AI_MODERATOR_ID)

    def test_inject_ai_audio_when_ai_speaking(self):
        """inject_ai_audio should enqueue on all peer outbound tracks when AI is speaker."""
        hub = SessionAudioHub("test-session")

        # inject_ai_audio forwards to peer outbound_tracks, not the AI track
        mock_peer_track = MagicMock()
        hub.register_peer(123, mock_peer_track)

        hub.init_ai_track()
        hub.set_speaker(AI_MODERATOR_ID)

        pcm_chunk = b"\x00" * 1920
        hub.inject_ai_audio(pcm_chunk, 960, 48000)

        mock_peer_track.enqueue.assert_called_once_with(pcm=pcm_chunk, samples=960, sample_rate=48000)

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


class TestAudioHubForwarding(unittest.TestCase):
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

            self.assertEqual(track, mock_ai_track)

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
        self.assertEqual(track, mock_speaker_track)


class TestAudioHubDrain(unittest.TestCase):
    """Test AI playout drain functionality."""

    def test_mark_ai_stream_end_signals_all_peers(self):
        """mark_ai_stream_end should call mark_end_of_stream on all peer tracks."""
        hub = SessionAudioHub("test-session")

        mock_track_1 = MagicMock()
        mock_track_2 = MagicMock()
        hub.register_peer(1, mock_track_1)
        hub.register_peer(2, mock_track_2)

        hub.mark_ai_stream_end()

        mock_track_1.mark_end_of_stream.assert_called_once()
        mock_track_2.mark_end_of_stream.assert_called_once()

    def test_wait_ai_playout_no_peers(self):
        """wait_ai_playout should return immediately with no peers."""
        async def _run():
            hub = SessionAudioHub("test-session")
            # Should not hang
            await asyncio.wait_for(hub.wait_ai_playout(), timeout=2.0)

        asyncio.get_event_loop().run_until_complete(_run())

    def test_wait_ai_playout_waits_all_peers(self):
        """wait_ai_playout should await drain on all peer tracks."""
        async def _run():
            hub = SessionAudioHub("test-session")

            mock_track_1 = MagicMock()
            mock_track_1.wait_until_drained = AsyncMock()
            mock_track_2 = MagicMock()
            mock_track_2.wait_until_drained = AsyncMock()
            hub.register_peer(1, mock_track_1)
            hub.register_peer(2, mock_track_2)

            await hub.wait_ai_playout(timeout=5.0)

            mock_track_1.wait_until_drained.assert_awaited_once_with(timeout=5.0)
            mock_track_2.wait_until_drained.assert_awaited_once_with(timeout=5.0)

        asyncio.get_event_loop().run_until_complete(_run())


class AudioHubDictMutationTests(unittest.TestCase):
    """
    Regression: a peer disconnect (which removes its entry from hub.peers)
    must not break ongoing iteration over self.peers in the broadcast methods.
    Pilot logs showed that during a moderator TTS, when one participant
    disconnected mid-broadcast the loop raised
    `RuntimeError: dictionary changed size during iteration` and the
    remaining listeners stopped hearing the moderator.
    """

    def test_inject_ai_audio_resilient_to_unregister_during_iteration(self) -> None:
        hub = SessionAudioHub(session_id="test-session")
        peer1_track = MagicMock()
        peer2_track = MagicMock()
        peer3_track = MagicMock()

        hub.register_peer(1, peer1_track)
        hub.register_peer(2, peer2_track)
        hub.register_peer(3, peer3_track)
        hub.current_speaker_user_id = AI_MODERATOR_ID

        # Peer 1's enqueue triggers peer 2 unregister mid-loop
        peer1_track.enqueue.side_effect = lambda **_: hub.unregister_peer(2)

        hub.inject_ai_audio(b"\x00" * 320, samples=160, sample_rate=24000)

        # Peer 1 received (it was first in iteration), peer 3 should still receive
        # (snapshot ensures iteration completes even with concurrent mutation).
        peer1_track.enqueue.assert_called_once()
        peer3_track.enqueue.assert_called_once()

    def test_inject_ai_audio_one_peer_exception_does_not_affect_others(self) -> None:
        hub = SessionAudioHub(session_id="test-session")
        peer1_track = MagicMock()
        peer1_track.enqueue.side_effect = RuntimeError("simulated peer 1 failure")
        peer2_track = MagicMock()
        peer3_track = MagicMock()

        hub.register_peer(1, peer1_track)
        hub.register_peer(2, peer2_track)
        hub.register_peer(3, peer3_track)
        hub.current_speaker_user_id = AI_MODERATOR_ID

        hub.inject_ai_audio(b"\x00" * 320, samples=160, sample_rate=24000)

        peer1_track.enqueue.assert_called_once()
        peer2_track.enqueue.assert_called_once()
        peer3_track.enqueue.assert_called_once()

    def test_forward_pcm_from_speaker_resilient_to_unregister(self) -> None:
        hub = SessionAudioHub(session_id="test-session")
        speaker_track = MagicMock()
        listener1_track = MagicMock()
        listener2_track = MagicMock()

        hub.register_peer(10, speaker_track)
        hub.register_peer(11, listener1_track)
        hub.register_peer(12, listener2_track)
        hub.set_speaker(10)

        # Listener1 enqueue removes listener2 mid-loop
        listener1_track.enqueue.side_effect = lambda **_: hub.unregister_peer(12)

        hub.forward_pcm_from_speaker(
            from_user_id=10, pcm=b"\x00" * 320, samples=160, sample_rate=24000,
        )

        # Speaker is excluded (no echo)
        speaker_track.enqueue.assert_not_called()
        listener1_track.enqueue.assert_called_once()
        # Iteration must complete without RuntimeError

    def test_forward_pcm_from_speaker_one_listener_exception_isolated(self) -> None:
        hub = SessionAudioHub(session_id="test-session")
        speaker_track = MagicMock()
        listener1_track = MagicMock()
        listener1_track.enqueue.side_effect = RuntimeError("listener 1 boom")
        listener2_track = MagicMock()

        hub.register_peer(10, speaker_track)
        hub.register_peer(11, listener1_track)
        hub.register_peer(12, listener2_track)
        hub.set_speaker(10)

        hub.forward_pcm_from_speaker(
            from_user_id=10, pcm=b"\x00" * 320, samples=160, sample_rate=24000,
        )

        listener1_track.enqueue.assert_called_once()
        listener2_track.enqueue.assert_called_once()

    def test_mark_ai_stream_end_resilient_to_unregister(self) -> None:
        hub = SessionAudioHub(session_id="test-session")
        peer1_track = MagicMock()
        peer2_track = MagicMock()
        peer3_track = MagicMock()

        hub.register_peer(1, peer1_track)
        hub.register_peer(2, peer2_track)
        hub.register_peer(3, peer3_track)

        peer1_track.mark_end_of_stream.side_effect = lambda: hub.unregister_peer(2)

        hub.mark_ai_stream_end()

        peer1_track.mark_end_of_stream.assert_called_once()
        peer3_track.mark_end_of_stream.assert_called_once()

    def test_mark_ai_stream_end_one_peer_exception_isolated(self) -> None:
        hub = SessionAudioHub(session_id="test-session")
        peer1_track = MagicMock()
        peer1_track.mark_end_of_stream.side_effect = RuntimeError("peer 1 boom")
        peer2_track = MagicMock()

        hub.register_peer(1, peer1_track)
        hub.register_peer(2, peer2_track)

        hub.mark_ai_stream_end()

        peer1_track.mark_end_of_stream.assert_called_once()
        peer2_track.mark_end_of_stream.assert_called_once()
