"""
Regression tests: TurnsConsumer.disconnect must NOT cancel the session-level
trigger loop. Each user has its own consumer instance (Channels creates one
per WebSocket); the FIRST disconnect was killing the loop for ALL remaining
participants.

Pilot logs showed that when one participant left mid-session, every other
participant stopped receiving moderator TTS messages because the trigger
loop was no longer running.
"""

import asyncio
from unittest.mock import patch, AsyncMock

from django.test import TestCase
from django.core.cache import cache

from apps.turns.ws_consumer import TurnsConsumer


class TurnsConsumerDisconnectTriggerTaskTests(TestCase):
    """
    The trigger task is a *session-scoped* asyncio task tracked in
    `TurnsConsumer._trigger_tasks[session_id]`. It must keep running as
    long as the session is active and there is at least one participant.
    A single user disconnecting must not stop it.
    """

    def setUp(self):
        cache.clear()
        TurnsConsumer._trigger_tasks.clear()

    def tearDown(self):
        cache.clear()
        # Cancel any leftover tasks before clearing
        for task in TurnsConsumer._trigger_tasks.values():
            task.cancel()
        TurnsConsumer._trigger_tasks.clear()

    def test_disconnect_does_not_cancel_session_trigger_task(self):
        """
        Calling consumer.disconnect() must NOT remove or cancel the
        per-session trigger task. Reproduces the bug where one user's
        disconnect silenced all remaining listeners.
        """
        async def _run():
            # Arrange: simulate an already-running session-level trigger task
            sentinel_task = asyncio.create_task(asyncio.sleep(60))
            session_id = "sess-test-1"
            TurnsConsumer._trigger_tasks[session_id] = sentinel_task

            # Build a minimal consumer instance with the attributes that
            # disconnect() touches. We avoid the full Channels/ASGI stack.
            consumer = TurnsConsumer.__new__(TurnsConsumer)
            consumer.session_id = session_id
            consumer.group_name = f"turns_{session_id}"
            # Channel layer needs group_discard; mock it.
            mock_channel_layer = AsyncMock()
            consumer.channel_layer = mock_channel_layer
            consumer.channel_name = "test-channel"

            # Act
            await consumer.disconnect(code=1000)

            # Assert: the trigger task must still be present and not cancelled
            self.assertIn(
                session_id,
                TurnsConsumer._trigger_tasks,
                "disconnect() removed the session-level trigger task — "
                "remaining participants will lose moderator audio.",
            )
            self.assertFalse(
                sentinel_task.cancelled() or sentinel_task.done(),
                "disconnect() cancelled the session-level trigger task — "
                "regression of Bug B.",
            )

            # Cleanup
            sentinel_task.cancel()
            try:
                await sentinel_task
            except asyncio.CancelledError:
                pass

        asyncio.new_event_loop().run_until_complete(_run())

    def test_disconnect_still_discards_from_group(self):
        """
        Sanity check: disconnect() must still clean up the channel group
        membership for the disconnecting user — only the *trigger task*
        cancellation was wrong.
        """
        async def _run():
            consumer = TurnsConsumer.__new__(TurnsConsumer)
            consumer.session_id = "sess-test-2"
            consumer.group_name = "turns_sess-test-2"
            consumer.channel_name = "test-channel"
            mock_channel_layer = AsyncMock()
            consumer.channel_layer = mock_channel_layer

            await consumer.disconnect(code=1000)

            mock_channel_layer.group_discard.assert_awaited_once_with(
                "turns_sess-test-2", "test-channel"
            )

        asyncio.new_event_loop().run_until_complete(_run())


class TriggerLoopExitsOnTerminalSessionStateTests(TestCase):
    """
    Even though a single disconnect must not cancel the loop, we still need
    the loop to self-exit when the session reaches a terminal state
    (CONCLUSION or CLOSED) — otherwise we'd accumulate orphan loops on dead
    sessions.
    """

    def setUp(self):
        cache.clear()
        TurnsConsumer._trigger_tasks.clear()

    def tearDown(self):
        cache.clear()
        for task in TurnsConsumer._trigger_tasks.values():
            task.cancel()
        TurnsConsumer._trigger_tasks.clear()

    def test_trigger_loop_exits_when_session_state_is_closed(self):
        """
        When the loop polls and sees the session is CLOSED, it must break
        gracefully without further work.
        """
        async def _run():
            consumer = TurnsConsumer.__new__(TurnsConsumer)
            consumer.session_id = "sess-closed"
            consumer.group_name = "turns_sess-closed"

            # Speed up the loop's sleep for the test
            real_sleep = asyncio.sleep

            async def fast_sleep(_seconds):
                # advance time without actually waiting
                await real_sleep(0)

            # Make _get_session_state return CLOSED
            with patch.object(
                TurnsConsumer,
                "_get_session_state",
                new=AsyncMock(return_value="CLOSED"),
            ), patch("apps.turns.ws_consumer.asyncio.sleep", new=fast_sleep), \
               patch("apps.turns.ws_consumer.has_intro_pending", return_value=False):
                # Run the loop; it must exit quickly (within a few iterations)
                # rather than spinning forever.
                await asyncio.wait_for(
                    consumer._trigger_loop("sess-closed"),
                    timeout=2.0,
                )

        asyncio.new_event_loop().run_until_complete(_run())

    def test_trigger_loop_exits_when_session_state_is_conclusion(self):
        """Same contract for CONCLUSION (timer expired, session winding down)."""
        async def _run():
            consumer = TurnsConsumer.__new__(TurnsConsumer)
            consumer.session_id = "sess-conclusion"
            consumer.group_name = "turns_sess-conclusion"

            real_sleep = asyncio.sleep

            async def fast_sleep(_seconds):
                await real_sleep(0)

            with patch.object(
                TurnsConsumer,
                "_get_session_state",
                new=AsyncMock(return_value="CONCLUSION"),
            ), patch("apps.turns.ws_consumer.asyncio.sleep", new=fast_sleep), \
               patch("apps.turns.ws_consumer.has_intro_pending", return_value=False):
                await asyncio.wait_for(
                    consumer._trigger_loop("sess-conclusion"),
                    timeout=2.0,
                )

        asyncio.new_event_loop().run_until_complete(_run())
