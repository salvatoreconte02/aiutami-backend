"""Tests della modalità 'no moderator' (Session.moderator_enabled=False).

Copertura:
- helper _get_moderator_enabled
- 3 guard nel coordinator: _handle_end_speak, _trigger_loop,
  _flush_pending_tts_messages
- regression mod ON: i percorsi originali continuano a girare quando
  moderator_enabled=True

Convenzione invocazione asincrona: stesso pattern di
apps/turns/tests_disconnect.py — costruiamo una TurnsConsumer via
__new__ + asyncio.new_event_loop().run_until_complete().

Vedi docs/plans/2026-05-07-no-moderator-mode-design.md.
"""

import asyncio
from unittest.mock import patch, AsyncMock, MagicMock

from django.test import TestCase, TransactionTestCase
from django.core.cache import cache
from django.contrib.auth import get_user_model

from apps.sessions.models import Session, SessionParticipant, SessionState, ParticipantRole
from apps.turns.ws_consumer import TurnsConsumer

User = get_user_model()


class GetModeratorEnabledHelperTests(TransactionTestCase):
    """_get_moderator_enabled deve restituire il valore corrente del flag
    leggendo da DB con un singolo SELECT. Pattern speculare a
    _get_session_state.

    Usa TransactionTestCase perché il helper è decorato con
    database_sync_to_async — runa in thread pool con connection separata
    che non vede i dati creati in una transaction test wrapper."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="host", email="h@e.com", password="p"
        )

    def tearDown(self):
        cache.clear()

    def _make_session(self, *, moderator_enabled: bool) -> Session:
        s = Session.objects.create(
            title="S",
            context="murder_mystery",
            min_size=3,
            max_size=3,
            host=self.user,
            moderator_enabled=moderator_enabled,
        )
        SessionParticipant.objects.create(
            session=s, user=self.user, role=ParticipantRole.HOST
        )
        return s

    def test_helper_returns_true_when_enabled(self):
        session = self._make_session(moderator_enabled=True)

        async def _run():
            consumer = TurnsConsumer.__new__(TurnsConsumer)
            consumer.session_id = str(session.id)
            return await consumer._get_moderator_enabled(consumer.session_id)

        result = asyncio.new_event_loop().run_until_complete(_run())
        self.assertTrue(result)

    def test_helper_returns_false_when_disabled(self):
        session = self._make_session(moderator_enabled=False)

        async def _run():
            consumer = TurnsConsumer.__new__(TurnsConsumer)
            consumer.session_id = str(session.id)
            return await consumer._get_moderator_enabled(consumer.session_id)

        result = asyncio.new_event_loop().run_until_complete(_run())
        self.assertFalse(result)


class EndSpeakModeratorDisabledTests(TestCase):
    """Quando moderator_enabled=False, _handle_end_speak chiude il turno
    umano e ritorna senza chiamare l'orchestrator né alcun TTS.

    I test mockano completamente _get_moderator_enabled (return False),
    quindi non serve TransactionTestCase."""

    def setUp(self):
        cache.clear()
        TurnsConsumer._trigger_tasks.clear()
        self.user = User.objects.create_user(
            username="speaker", email="sp@e.com", password="p"
        )

    def tearDown(self):
        cache.clear()
        for task in TurnsConsumer._trigger_tasks.values():
            task.cancel()
        TurnsConsumer._trigger_tasks.clear()

    def _make_consumer(self):
        consumer = TurnsConsumer.__new__(TurnsConsumer)
        consumer.session_id = "sess-mod-off"
        consumer.group_name = "turns_sess-mod-off"
        consumer.channel_name = "test-channel"
        consumer.scope = {"user": self.user}
        consumer.channel_layer = AsyncMock()
        consumer.send_json = AsyncMock()
        return consumer

    def test_end_speak_skips_orchestrator_when_moderator_disabled(self):
        """Mod OFF: _run_moderation_orchestrator NON chiamato.
        Verifica anche che _set_moderation_in_progress NON sia chiamato
        (entrata fase moderazione saltata)."""

        async def _run():
            consumer = self._make_consumer()

            mock_end_result = MagicMock()
            mock_end_result.success = True
            mock_end_result.events = []
            mock_end_result.to_state_dict = MagicMock(return_value={})

            with patch(
                "apps.turns.services.TurnManager.end_speak",
                return_value=mock_end_result,
            ), patch.object(
                TurnsConsumer, "_ensure_session_active",
                new=AsyncMock(return_value=True),
            ), patch.object(
                TurnsConsumer, "_mark_any_activity",
                new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_broadcast_events",
                new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_get_moderator_enabled",
                new=AsyncMock(return_value=False),
            ), patch.object(
                TurnsConsumer, "_run_moderation_orchestrator",
                new=AsyncMock(),
            ) as mock_orchestrator, patch.object(
                TurnsConsumer, "_set_moderation_in_progress",
                new=AsyncMock(),
            ) as mock_set_mod_progress:
                await consumer._handle_end_speak({"transcript": "hello"})

                mock_orchestrator.assert_not_awaited()
                mock_set_mod_progress.assert_not_awaited()

        asyncio.new_event_loop().run_until_complete(_run())

    def test_end_speak_skips_static_messages_and_tts_when_disabled(self):
        """Mod OFF: nessun side-effect TTS / static messages dopo end_speak."""

        async def _run():
            consumer = self._make_consumer()

            mock_end_result = MagicMock()
            mock_end_result.success = True
            mock_end_result.events = []
            mock_end_result.to_state_dict = MagicMock(return_value={})

            with patch(
                "apps.turns.services.TurnManager.end_speak",
                return_value=mock_end_result,
            ), patch.object(
                TurnsConsumer, "_ensure_session_active",
                new=AsyncMock(return_value=True),
            ), patch.object(
                TurnsConsumer, "_mark_any_activity",
                new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_broadcast_events",
                new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_get_moderator_enabled",
                new=AsyncMock(return_value=False),
            ), patch.object(
                TurnsConsumer, "_execute_tts_message",
                new=AsyncMock(),
            ) as mock_tts:
                await consumer._handle_end_speak({"transcript": "hi"})

                mock_tts.assert_not_awaited()

        asyncio.new_event_loop().run_until_complete(_run())

    def test_end_speak_records_speaking_time_even_when_moderator_disabled(self):
        """Bug fix critico: in mod OFF il guard saltava la pipeline LLM,
        quindi handle_human_turn_ended NON veniva mai chiamato e
        speaking_time_per_participant restava sempre vuoto. Risultato:
        Gini index calcolato a 0 in modalità control → metrica di
        participation balance comparativa INUTILIZZABILE.

        Fix: record_human_turn_end DEVE essere chiamata in _handle_end_speak
        PRIMA del guard mod-OFF, indipendentemente da moderator_enabled.
        """

        async def _run():
            consumer = self._make_consumer()

            mock_end_result = MagicMock()
            mock_end_result.success = True
            mock_end_result.events = []
            mock_end_result.to_state_dict = MagicMock(return_value={})

            with patch(
                "apps.turns.services.TurnManager.end_speak",
                return_value=mock_end_result,
            ), patch.object(
                TurnsConsumer, "_ensure_session_active",
                new=AsyncMock(return_value=True),
            ), patch.object(
                TurnsConsumer, "_mark_any_activity",
                new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_broadcast_events",
                new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_get_moderator_enabled",
                new=AsyncMock(return_value=False),
            ), patch(
                "apps.moderation.service.ModerationService.record_human_turn_end"
            ) as mock_record_end:
                await consumer._handle_end_speak({"transcript": "hello"})

                # CHIAVE: anche in mod OFF, record_human_turn_end DEVE
                # essere stato chiamato (così speaking_time si accumula).
                mock_record_end.assert_called_once()
                # Verifica kwargs
                call = mock_record_end.call_args
                self.assertEqual(call.kwargs["session_id"], "sess-mod-off")
                self.assertEqual(call.kwargs["speaker_name"], "speaker")

        asyncio.new_event_loop().run_until_complete(_run())


class EndSpeakModeratorEnabledRegressionTests(TestCase):
    """Regression: mod ON deve continuare a chiamare l'orchestrator."""

    def setUp(self):
        cache.clear()
        TurnsConsumer._trigger_tasks.clear()
        self.user = User.objects.create_user(
            username="speaker", email="sp@e.com", password="p"
        )

    def tearDown(self):
        cache.clear()
        for task in TurnsConsumer._trigger_tasks.values():
            task.cancel()
        TurnsConsumer._trigger_tasks.clear()

    def test_end_speak_runs_orchestrator_when_moderator_enabled(self):
        """Mod ON: l'orchestrator DEVE essere chiamato (regression)."""

        async def _run():
            consumer = TurnsConsumer.__new__(TurnsConsumer)
            consumer.session_id = "sess-mod-on"
            consumer.group_name = "turns_sess-mod-on"
            consumer.channel_name = "test-channel"
            consumer.scope = {"user": self.user}
            consumer.channel_layer = AsyncMock()
            consumer.send_json = AsyncMock()

            mock_end_result = MagicMock()
            mock_end_result.success = True
            mock_end_result.events = []
            mock_end_result.to_state_dict = MagicMock(return_value={})

            mock_decision = MagicMock()
            mock_decision.hard_action = None
            mock_decision.ai_should_speak = False
            mock_decision.ai_message = ""
            mock_decision.static_messages_to_speak = []
            mock_decision.should_transition_to_conclusion = False

            with patch(
                "apps.turns.services.TurnManager.end_speak",
                return_value=mock_end_result,
            ), patch.object(
                TurnsConsumer, "_ensure_session_active",
                new=AsyncMock(return_value=True),
            ), patch.object(
                TurnsConsumer, "_mark_any_activity",
                new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_broadcast_events",
                new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_get_moderator_enabled",
                new=AsyncMock(return_value=True),
            ), patch.object(
                TurnsConsumer, "_set_moderation_in_progress",
                new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_collect_asr_transcript_with_wait",
                new=AsyncMock(return_value=""),
            ), patch.object(
                TurnsConsumer, "_get_session_state",
                new=AsyncMock(return_value="ACTIVE"),
            ), patch.object(
                TurnsConsumer, "_run_moderation_orchestrator",
                new=AsyncMock(return_value=mock_decision),
            ) as mock_orchestrator, patch.object(
                TurnsConsumer, "_flush_pending_tts_messages",
                new=AsyncMock(),
            ), patch(
                "apps.turns.services.TurnManager.start_reservation_window",
                return_value=None,
            ), patch(
                "apps.turns.services.TurnManager.get_state",
                return_value=MagicMock(to_state_dict=lambda: {}),
            ):
                await consumer._handle_end_speak({"transcript": "hi"})

                mock_orchestrator.assert_awaited_once()

        asyncio.new_event_loop().run_until_complete(_run())


class TriggerLoopModeratorDisabledTests(TestCase):
    """In mod OFF il trigger loop:
    - NON chiama _execute_static_messages
    - NON chiama _execute_forced_conclusion
    - chiama comunque la transizione di stato ACTIVE → CONCLUSION
      (timer 30 min deve chiudere la sessione anche senza recap)
    """

    def setUp(self):
        cache.clear()
        TurnsConsumer._trigger_tasks.clear()

    def tearDown(self):
        cache.clear()
        for task in TurnsConsumer._trigger_tasks.values():
            task.cancel()
        TurnsConsumer._trigger_tasks.clear()

    def _make_consumer(self):
        consumer = TurnsConsumer.__new__(TurnsConsumer)
        consumer.session_id = "sess-mod-off"
        consumer.group_name = "turns_sess-mod-off"
        consumer.channel_layer = AsyncMock()
        return consumer

    def test_trigger_loop_skips_static_messages_when_disabled(self):
        """Mod OFF: _execute_static_messages NON deve essere chiamato anche
        se il trigger result contiene static_messages_to_speak."""

        async def _run():
            consumer = self._make_consumer()

            real_sleep = asyncio.sleep

            async def fast_sleep(_seconds):
                await real_sleep(0)

            mock_trig = MagicMock()
            mock_trig.static_messages_to_speak = [MagicMock(use_tts=True, text="hi")]
            mock_trig.should_transition_to_conclusion = False

            # Dopo la prima iterazione, simuliamo passaggio a CONCLUSION
            # per uscire dal loop.
            state_iter = iter(["ACTIVE", "CONCLUSION"])

            with patch.object(
                TurnsConsumer, "_get_session_state",
                new=AsyncMock(side_effect=lambda sid: next(state_iter, "CONCLUSION")),
            ), patch.object(
                TurnsConsumer, "_get_moderator_enabled",
                new=AsyncMock(return_value=False),
            ), patch(
                "apps.turns.ws_consumer.asyncio.sleep", new=fast_sleep,
            ), patch(
                "apps.turns.ws_consumer.has_intro_pending", return_value=False,
            ), patch(
                "apps.turns.ws_consumer.evaluate_time_based_triggers",
                return_value=mock_trig,
            ), patch.object(
                TurnsConsumer, "_execute_static_messages",
                new=AsyncMock(return_value=False),
            ) as mock_exec_static, patch.object(
                TurnsConsumer, "_flush_pending_tts_messages",
                new=AsyncMock(),
            ):
                await asyncio.wait_for(
                    consumer._trigger_loop(consumer.session_id),
                    timeout=2.0,
                )
                mock_exec_static.assert_not_awaited()

        asyncio.new_event_loop().run_until_complete(_run())

    def test_trigger_loop_skips_forced_conclusion_when_disabled(self):
        """Mod OFF: timer 30 scaduto → transizione a CONCLUSION SI,
        _execute_forced_conclusion NO."""

        async def _run():
            consumer = self._make_consumer()

            real_sleep = asyncio.sleep

            async def fast_sleep(_seconds):
                await real_sleep(0)

            mock_trig = MagicMock()
            mock_trig.static_messages_to_speak = []
            mock_trig.should_transition_to_conclusion = True

            state_iter = iter(["ACTIVE", "CONCLUSION"])

            with patch.object(
                TurnsConsumer, "_get_session_state",
                new=AsyncMock(side_effect=lambda sid: next(state_iter, "CONCLUSION")),
            ), patch.object(
                TurnsConsumer, "_get_moderator_enabled",
                new=AsyncMock(return_value=False),
            ), patch(
                "apps.turns.ws_consumer.asyncio.sleep", new=fast_sleep,
            ), patch(
                "apps.turns.ws_consumer.has_intro_pending", return_value=False,
            ), patch(
                "apps.turns.ws_consumer.evaluate_time_based_triggers",
                return_value=mock_trig,
            ), patch.object(
                TurnsConsumer, "_set_conclusion_reason", new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_transition_session_to_conclusion",
                new=AsyncMock(return_value=True),
            ) as mock_transition, patch.object(
                TurnsConsumer, "_get_session_detail_payload",
                new=AsyncMock(return_value={"id": "x", "state": "CONCLUSION"}),
            ), patch.object(
                TurnsConsumer, "_execute_forced_conclusion",
                new=AsyncMock(),
            ) as mock_forced, patch.object(
                TurnsConsumer, "_flush_pending_tts_messages",
                new=AsyncMock(),
            ):
                await asyncio.wait_for(
                    consumer._trigger_loop(consumer.session_id),
                    timeout=2.0,
                )
                mock_transition.assert_awaited()  # state change SI
                mock_forced.assert_not_awaited()  # recap LLM NO

        asyncio.new_event_loop().run_until_complete(_run())


class TriggerLoopModeratorEnabledRegressionTests(TestCase):
    """Regression: mod ON deve continuare a chiamare _execute_forced_conclusion
    e _execute_static_messages quando il trigger result lo richiede."""

    def setUp(self):
        cache.clear()
        TurnsConsumer._trigger_tasks.clear()

    def tearDown(self):
        cache.clear()
        for task in TurnsConsumer._trigger_tasks.values():
            task.cancel()
        TurnsConsumer._trigger_tasks.clear()

    def test_trigger_loop_executes_forced_conclusion_when_enabled(self):
        """Mod ON: timer 30 scaduto → forced_conclusion DEVE essere chiamato."""

        async def _run():
            consumer = TurnsConsumer.__new__(TurnsConsumer)
            consumer.session_id = "sess-mod-on"
            consumer.group_name = "turns_sess-mod-on"
            consumer.channel_layer = AsyncMock()

            real_sleep = asyncio.sleep

            async def fast_sleep(_seconds):
                await real_sleep(0)

            mock_trig = MagicMock()
            mock_trig.static_messages_to_speak = []
            mock_trig.should_transition_to_conclusion = True

            state_iter = iter(["ACTIVE", "CONCLUSION"])

            with patch.object(
                TurnsConsumer, "_get_session_state",
                new=AsyncMock(side_effect=lambda sid: next(state_iter, "CONCLUSION")),
            ), patch.object(
                TurnsConsumer, "_get_moderator_enabled",
                new=AsyncMock(return_value=True),
            ), patch(
                "apps.turns.ws_consumer.asyncio.sleep", new=fast_sleep,
            ), patch(
                "apps.turns.ws_consumer.has_intro_pending", return_value=False,
            ), patch(
                "apps.turns.ws_consumer.evaluate_time_based_triggers",
                return_value=mock_trig,
            ), patch.object(
                TurnsConsumer, "_set_conclusion_reason", new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_transition_session_to_conclusion",
                new=AsyncMock(return_value=True),
            ), patch.object(
                TurnsConsumer, "_get_session_detail_payload",
                new=AsyncMock(return_value={"id": "x"}),
            ), patch.object(
                TurnsConsumer, "_execute_forced_conclusion",
                new=AsyncMock(),
            ) as mock_forced, patch.object(
                TurnsConsumer, "_flush_pending_tts_messages",
                new=AsyncMock(),
            ):
                await asyncio.wait_for(
                    consumer._trigger_loop(consumer.session_id),
                    timeout=2.0,
                )
                mock_forced.assert_awaited()

        asyncio.new_event_loop().run_until_complete(_run())


class FlushPendingMessagesModeratorDisabledTests(TestCase):
    """In mod OFF, _flush_pending_tts_messages NON deve chiamare
    _execute_forced_conclusion anche se per qualche motivo c'è un
    messaggio in coda con trigger_conclusion=True (defensive guard)."""

    def setUp(self):
        cache.clear()
        TurnsConsumer._trigger_tasks.clear()

    def tearDown(self):
        cache.clear()
        for task in TurnsConsumer._trigger_tasks.values():
            task.cancel()
        TurnsConsumer._trigger_tasks.clear()

    def test_flush_skips_forced_conclusion_when_disabled(self):
        """Mod OFF: anche con un PendingMessage(trigger_conclusion=True)
        in coda e stato IDLE, _execute_forced_conclusion NON viene chiamato.
        La transizione di stato avviene comunque (timer)."""

        async def _run():
            consumer = TurnsConsumer.__new__(TurnsConsumer)
            consumer.session_id = "sess-flush-off"
            consumer.group_name = "turns_sess-flush-off"
            consumer.channel_layer = AsyncMock()

            mock_state = MagicMock()
            mock_state.state = "IDLE"

            mock_pending_msg = MagicMock()
            mock_pending_msg.text = "queued recap"
            mock_pending_msg.trigger_conclusion = True

            with patch(
                "apps.turns.services.TurnManager.get_state_only",
                return_value=mock_state,
            ), patch(
                "apps.moderation.pending_messages.has_pending_messages",
                return_value=True,
            ), patch(
                "apps.moderation.pending_messages.dequeue_all_messages",
                return_value=[mock_pending_msg],
            ), patch.object(
                TurnsConsumer, "_get_moderator_enabled",
                new=AsyncMock(return_value=False),
            ), patch.object(
                TurnsConsumer, "_execute_tts_message",
                new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_set_conclusion_reason", new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_transition_session_to_conclusion",
                new=AsyncMock(return_value=True),
            ) as mock_transition, patch.object(
                TurnsConsumer, "_get_session_detail_payload",
                new=AsyncMock(return_value={"id": "x"}),
            ), patch.object(
                TurnsConsumer, "_execute_forced_conclusion",
                new=AsyncMock(),
            ) as mock_forced:
                await consumer._flush_pending_tts_messages()
                mock_forced.assert_not_awaited()

        asyncio.new_event_loop().run_until_complete(_run())

    def test_flush_runs_forced_conclusion_when_enabled(self):
        """Regression mod ON: forced_conclusion VIENE chiamato se la coda
        contiene un messaggio con trigger_conclusion=True."""

        async def _run():
            consumer = TurnsConsumer.__new__(TurnsConsumer)
            consumer.session_id = "sess-flush-on"
            consumer.group_name = "turns_sess-flush-on"
            consumer.channel_layer = AsyncMock()

            mock_state = MagicMock()
            mock_state.state = "IDLE"

            mock_pending_msg = MagicMock()
            mock_pending_msg.text = "queued recap"
            mock_pending_msg.trigger_conclusion = True

            with patch(
                "apps.turns.services.TurnManager.get_state_only",
                return_value=mock_state,
            ), patch(
                "apps.moderation.pending_messages.has_pending_messages",
                return_value=True,
            ), patch(
                "apps.moderation.pending_messages.dequeue_all_messages",
                return_value=[mock_pending_msg],
            ), patch.object(
                TurnsConsumer, "_get_moderator_enabled",
                new=AsyncMock(return_value=True),
            ), patch.object(
                TurnsConsumer, "_execute_tts_message",
                new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_set_conclusion_reason", new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_transition_session_to_conclusion",
                new=AsyncMock(return_value=True),
            ), patch.object(
                TurnsConsumer, "_get_session_detail_payload",
                new=AsyncMock(return_value={"id": "x"}),
            ), patch.object(
                TurnsConsumer, "_execute_forced_conclusion",
                new=AsyncMock(),
            ) as mock_forced:
                await consumer._flush_pending_tts_messages()
                mock_forced.assert_awaited()

        asyncio.new_event_loop().run_until_complete(_run())


class IntroRunsInBothModesTests(TestCase):
    """L'intro del moderatore (testo statico via TTS) è base comune fra
    le due condizioni sperimentali e DEVE girare anche in mod OFF.
    Vedi docs/plans/2026-05-07-no-moderator-mode-design.md §5."""

    def setUp(self):
        cache.clear()
        TurnsConsumer._trigger_tasks.clear()

    def tearDown(self):
        cache.clear()
        for task in TurnsConsumer._trigger_tasks.values():
            task.cancel()
        TurnsConsumer._trigger_tasks.clear()

    def _run_intro_branch(self, *, moderator_enabled: bool) -> bool:
        """Esegue il trigger_loop simulando intro pendente con il flag dato.
        Ritorna True se _execute_intro_message è stato chiamato."""

        intro_called = {"v": False}

        async def fake_intro(self, session_id):
            intro_called["v"] = True

        async def _run():
            consumer = TurnsConsumer.__new__(TurnsConsumer)
            consumer.session_id = "sess-intro"
            consumer.group_name = "turns_sess-intro"
            consumer.channel_layer = AsyncMock()

            real_sleep = asyncio.sleep

            async def fast_sleep(_seconds):
                await real_sleep(0)

            # has_intro_pending=True una volta, poi False; phases ACTIVE poi
            # CLOSED per uscire dal loop dopo l'intro.
            phases = iter(["ACTIVE", "CLOSED"])
            intros = iter([True, False])

            mock_turn_state = MagicMock()
            mock_turn_state.state = "AI_INTRODUCING"

            with patch.object(
                TurnsConsumer, "_get_session_state",
                new=AsyncMock(side_effect=lambda sid: next(phases, "CLOSED")),
            ), patch.object(
                TurnsConsumer, "_get_moderator_enabled",
                new=AsyncMock(return_value=moderator_enabled),
            ), patch(
                "apps.turns.ws_consumer.asyncio.sleep", new=fast_sleep,
            ), patch(
                "apps.turns.ws_consumer.has_intro_pending",
                side_effect=lambda sid: next(intros, False),
            ), patch(
                "apps.turns.services.TurnManager.get_state_only",
                return_value=mock_turn_state,
            ), patch.object(
                TurnsConsumer, "_execute_intro_message",
                new=fake_intro,
            ):
                await asyncio.wait_for(
                    consumer._trigger_loop(consumer.session_id),
                    timeout=2.0,
                )

        asyncio.new_event_loop().run_until_complete(_run())
        return intro_called["v"]

    def test_intro_runs_when_moderator_enabled(self):
        """Mod ON: intro chiamata (baseline)."""
        self.assertTrue(self._run_intro_branch(moderator_enabled=True))

    def test_intro_runs_when_moderator_disabled(self):
        """Mod OFF: intro DEVE comunque girare (base comune fra le 2
        condizioni sperimentali)."""
        self.assertTrue(self._run_intro_branch(moderator_enabled=False))
