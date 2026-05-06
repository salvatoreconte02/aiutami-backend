"""
Regression tests: WebRTC reader loop must handle MediaStreamError gracefully.

When a peer disconnects ungracefully (network drop, browser tab close), the
remote audio track raises `aiortc.mediastreams.MediaStreamError` from
`track.recv()`. We must:
  - log it as INFO/WARNING (not ERROR — it's an expected disconnect signal)
  - exit the reader loop cleanly without propagating

This is one of three contributing causes for the pilot bug where one
participant disconnect silenced moderator audio for everyone else.
"""
import asyncio
import logging
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aiortc.mediastreams import MediaStreamError


class WebRTCReaderMediaStreamErrorTests(unittest.TestCase):
    """
    The reader is defined as an inline closure inside `on_track` of
    `WebRTCConsumer._handle_offer`. We can't call it directly without
    spinning up the full peer connection. Instead we exercise the
    relevant logic by:
      1. Building a stand-alone reader with the same shape (track.recv loop
         + try/except block), and verifying MediaStreamError is caught at
         INFO/WARNING level rather than escaping or being logged as ERROR.
      2. A static check on the source code to ensure the explicit
         MediaStreamError handler is present in ws_consumer.py.
    """

    def test_mediastreamerror_does_not_propagate_from_recv_loop(self):
        """
        Replicates the reader's outer structure. A track that raises
        MediaStreamError on recv() must not let the exception escape.
        """
        async def _run():
            track = MagicMock()
            track.recv = AsyncMock(side_effect=MediaStreamError("track closed"))

            # Replica della struttura reader (semplificata):
            async def reader():
                try:
                    while True:
                        await track.recv()
                except MediaStreamError:
                    # expected on peer disconnect
                    return
                except asyncio.CancelledError:
                    raise
                except Exception:
                    raise

            # Should not raise
            await asyncio.wait_for(reader(), timeout=2.0)

        asyncio.new_event_loop().run_until_complete(_run())

    def test_ws_consumer_source_handles_mediastreamerror_explicitly(self):
        """
        Static guard: the reader in ws_consumer.py must have an explicit
        `except MediaStreamError` clause logging at INFO/WARNING level.
        Without this clause, the broad `except Exception` would still
        catch it but log at ERROR — noisy and misleading for a normal
        disconnect.
        """
        from pathlib import Path
        src = Path(__file__).resolve().parent.parent / "ws_consumer.py"
        content = src.read_text(encoding="utf-8")

        # Import is required
        self.assertIn(
            "MediaStreamError",
            content,
            "ws_consumer.py must reference MediaStreamError to catch it",
        )

        # Explicit except clause must exist
        self.assertIn(
            "except MediaStreamError",
            content,
            "ws_consumer.py reader must have an explicit `except MediaStreamError` "
            "clause so peer disconnects are logged as INFO/WARNING, not ERROR",
        )

    def test_mediastreamerror_logged_as_info_or_warning(self):
        """
        The handler must call logger.info or logger.warning, NOT
        logger.error / logger.exception.
        """
        from pathlib import Path
        src = Path(__file__).resolve().parent.parent / "ws_consumer.py"
        content = src.read_text(encoding="utf-8")

        # Find the except MediaStreamError block and check the next few lines
        idx = content.find("except MediaStreamError")
        self.assertNotEqual(idx, -1, "no except MediaStreamError block found")
        # Look ahead a bit (the block body)
        block = content[idx:idx + 600]
        self.assertTrue(
            "logger.info" in block or "logger.warning" in block,
            "MediaStreamError handler should log at info/warning level: "
            f"got block={block!r}",
        )
