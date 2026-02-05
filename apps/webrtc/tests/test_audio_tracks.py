"""Tests for ForwardingAudioTrack EOS/drain functionality."""
import asyncio
import unittest

from apps.webrtc.audio_tracks import ForwardingAudioTrack

SAMPLE_RATE = 48000
BYTES_PER_SAMPLE = 2
# One 20ms frame = 960 samples = 1920 bytes
FRAME_BYTES = 960 * BYTES_PER_SAMPLE


class TestForwardingAudioTrackDrain(unittest.TestCase):
    """Test EOS and drain signaling."""

    def test_mark_eos_and_drain_after_recv(self):
        """After EOS, draining should complete once recv() empties the buffer."""
        async def _run():
            track = ForwardingAudioTrack(user_id=1, session_id="s1")

            # Enqueue exactly one frame of audio
            pcm = b"\x01\x00" * 960  # 960 samples s16 mono = 1920 bytes
            track.enqueue(pcm, 960, SAMPLE_RATE)

            # Mark end of stream
            track.mark_end_of_stream()

            # Consume the frame via recv
            await track.recv()

            # Now the buffer should be empty -> drained event should be set
            await asyncio.wait_for(track.wait_until_drained(timeout=1.0), timeout=2.0)

        asyncio.get_event_loop().run_until_complete(_run())

    def test_drain_not_set_before_eos(self):
        """wait_until_drained returns immediately if EOS not signaled."""
        async def _run():
            track = ForwardingAudioTrack(user_id=1, session_id="s1")

            # No EOS -> should return immediately (no hang)
            await asyncio.wait_for(track.wait_until_drained(timeout=1.0), timeout=2.0)

        asyncio.get_event_loop().run_until_complete(_run())

    def test_drain_timeout_does_not_hang(self):
        """Drain timeout should not block forever when buffer has data."""
        async def _run():
            track = ForwardingAudioTrack(user_id=1, session_id="s1")

            # Enqueue audio but don't recv
            pcm = b"\x01\x00" * 960
            track.enqueue(pcm, 960, SAMPLE_RATE)
            track.mark_end_of_stream()

            # Should timeout gracefully (not hang)
            await asyncio.wait_for(track.wait_until_drained(timeout=0.1), timeout=2.0)

        asyncio.get_event_loop().run_until_complete(_run())

    def test_eos_reset_on_enqueue(self):
        """Enqueueing new audio after EOS should reset the drain state."""
        track = ForwardingAudioTrack(user_id=1, session_id="s1")

        # Mark EOS
        track.mark_end_of_stream()
        self.assertTrue(track._eos)

        # Enqueue resets EOS
        pcm = b"\x01\x00" * 960
        track.enqueue(pcm, 960, SAMPLE_RATE)
        self.assertFalse(track._eos)
        self.assertFalse(track._drained_event.is_set())
