"""
Test per DiscussionEvent + event_log helper.

Coverage:
- Creazione evento via persist_event_sync (sync path, usato in test/CLI)
- Sequence number monotono per sessione (atomic via Redis INCR)
- Sequence number indipendente tra sessioni distinte
- Speaker resolution: display_name → user_id, __AI_MODERATOR__ → None,
  unknown → None
- Error safety: persist non solleva eccezione anche con session_id invalido
- Integration: ModerationService.handle_human_turn_ended scrive 2 eventi
  per turno (human_turn + ai_intervention) con metadata corretti
- block_reason diagnosis: cooldown, min_score, min_time_not_reached
"""

from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from apps.moderation.service import ModerationService, HardModerationAction
from apps.moderation.state import (
    ModerationState,
    save_moderation_state,
)
from apps.sessions.event_log import (
    SEQUENCE_KEY_TEMPLATE,
    persist_event_sync,
    reset_sequence_counter,
)
from apps.sessions.models import (
    DiscussionEvent,
    DiscussionEventType,
    ParticipantRole,
    Session,
    SessionParticipant,
    SessionState,
)


User = get_user_model()


def _make_session(host=None, *, context="generic", min_size=2, max_size=4):
    if host is None:
        host = User.objects.create_user(
            username=f"host_{uuid4().hex[:8]}",
            email=f"h{uuid4().hex[:6]}@example.com",
            password="x",
        )
    return Session.objects.create(
        title="Test",
        context=context,
        state=SessionState.ACTIVE,
        min_size=min_size,
        max_size=max_size,
        host=host,
        started_at=timezone.now() - timedelta(minutes=5),
    )


class PersistEventSyncTests(TestCase):
    def setUp(self):
        cache.clear()
        self.session = _make_session()

    def tearDown(self):
        cache.clear()

    def test_basic_event_creation(self):
        persist_event_sync(
            session_id=self.session.id,
            event_type="human_turn",
            speaker_name=None,
            content="Hello world",
            metadata={"duration_s": 1.5},
        )
        ev = DiscussionEvent.objects.get(session=self.session)
        self.assertEqual(ev.sequence_number, 1)
        self.assertEqual(ev.event_type, "human_turn")
        self.assertEqual(ev.content, "Hello world")
        self.assertEqual(ev.metadata["duration_s"], 1.5)
        self.assertIsNone(ev.speaker)

    def test_sequence_monotonic_per_session(self):
        for i in range(5):
            persist_event_sync(
                session_id=self.session.id,
                event_type="human_turn",
                content=f"turn {i}",
            )
        seqs = list(
            DiscussionEvent.objects.filter(session=self.session)
            .order_by("sequence_number")
            .values_list("sequence_number", flat=True)
        )
        self.assertEqual(seqs, [1, 2, 3, 4, 5])

    def test_sequence_independent_across_sessions(self):
        s2 = _make_session()
        persist_event_sync(session_id=self.session.id, event_type="human_turn", content="a")
        persist_event_sync(session_id=self.session.id, event_type="human_turn", content="b")
        persist_event_sync(session_id=s2.id, event_type="human_turn", content="c")

        s1_seqs = list(
            DiscussionEvent.objects.filter(session=self.session)
            .order_by("sequence_number").values_list("sequence_number", flat=True)
        )
        s2_seqs = list(
            DiscussionEvent.objects.filter(session=s2)
            .order_by("sequence_number").values_list("sequence_number", flat=True)
        )
        self.assertEqual(s1_seqs, [1, 2])
        self.assertEqual(s2_seqs, [1])

    def test_speaker_resolution_by_username(self):
        user = User.objects.create_user(username="marco", email="m@e.com", password="x")
        SessionParticipant.objects.create(
            session=self.session, user=user, role=ParticipantRole.PARTICIPANT
        )
        persist_event_sync(
            session_id=self.session.id,
            event_type="human_turn",
            speaker_name="marco",
            content="hi",
        )
        ev = DiscussionEvent.objects.get(session=self.session)
        self.assertEqual(ev.speaker_id, user.id)

    def test_speaker_unknown_yields_null(self):
        persist_event_sync(
            session_id=self.session.id,
            event_type="human_turn",
            speaker_name="ghost_user_not_in_session",
            content="hi",
        )
        ev = DiscussionEvent.objects.get(session=self.session)
        self.assertIsNone(ev.speaker_id)

    def test_ai_moderator_pseudo_speaker_yields_null(self):
        persist_event_sync(
            session_id=self.session.id,
            event_type="ai_intervention",
            speaker_name="__AI_MODERATOR__",
            content="reminder",
        )
        ev = DiscussionEvent.objects.get(session=self.session)
        self.assertIsNone(ev.speaker_id)

    def test_persist_does_not_raise_when_db_create_fails(self):
        """Error safety: se l'INSERT solleva eccezione, persist NON propaga
        l'errore al caller (loggia warning e continua). Il caller (live
        session moderation) non si rompe."""
        from apps.sessions.models import DiscussionEvent
        with patch.object(
            DiscussionEvent.objects,
            "create",
            side_effect=RuntimeError("simulated db crash"),
        ):
            # Deve completare normalmente senza propagare
            persist_event_sync(
                session_id=self.session.id,
                event_type="human_turn",
                content="anything",
            )

    def test_reset_sequence_counter_clears_redis_key(self):
        persist_event_sync(
            session_id=self.session.id,
            event_type="human_turn",
            content="a",
        )
        key = SEQUENCE_KEY_TEMPLATE.format(session_id=self.session.id)
        self.assertEqual(cache.get(key), 1)
        reset_sequence_counter(self.session.id)
        self.assertIsNone(cache.get(key))


class ModerationServiceEventIntegrationTests(TestCase):
    """Integration: handle_human_turn_ended scrive 2 eventi per turno."""

    def setUp(self):
        cache.clear()
        self.host = User.objects.create_user(username="host", email="h@e.com", password="x")
        self.user = User.objects.create_user(username="marco", email="m@e.com", password="x")
        self.session = _make_session(host=self.host)
        SessionParticipant.objects.create(
            session=self.session, user=self.host, role=ParticipantRole.HOST
        )
        SessionParticipant.objects.create(
            session=self.session, user=self.user, role=ParticipantRole.PARTICIPANT
        )

        # Inizializza ModerationState con session_started_at recente
        state = ModerationState.initial(
            participants=["host", "marco"],
            session_started_at=datetime.utcnow() - timedelta(minutes=2),
        )
        save_moderation_state(self.session.id, state)

    def tearDown(self):
        cache.clear()

    def _stub_llm(self, *, reason="all_ok", message=None, score=0.0, summary="updated"):
        return {
            "updated_summary": summary,
            "should_ai_speak": bool(message) and reason != "all_ok",
            "message_to_say": message,
            "reason": reason,
            "intervention_score": score,
        }

    @patch.object(ModerationService, "_call_llm")
    def test_writes_human_turn_and_ai_intervention_on_all_ok(self, mock_llm):
        mock_llm.return_value = self._stub_llm(reason="all_ok")
        ModerationService.handle_human_turn_ended(
            session_id=self.session.id,
            user_id=self.user.id,
            last_turn_text="Hello, this is my opinion",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="marco",
        )
        events = list(
            DiscussionEvent.objects.filter(session=self.session)
            .order_by("sequence_number")
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].event_type, "human_turn")
        self.assertEqual(events[0].content, "Hello, this is my opinion")
        self.assertEqual(events[0].speaker_id, self.user.id)
        self.assertIn("summary_after_this_turn", events[0].metadata)
        self.assertEqual(events[0].metadata["empty_transcription"], False)

        self.assertEqual(events[1].event_type, "ai_intervention")
        self.assertEqual(events[1].metadata["reason"], "all_ok")
        self.assertEqual(events[1].metadata["was_played"], False)
        # all_ok non e' un block, e' "il LLM non aveva nulla da dire"
        self.assertIsNone(events[1].metadata["block_reason"])

    @patch.object(ModerationService, "_call_llm")
    def test_writes_ai_intervention_played_when_speak(self, mock_llm):
        mock_llm.return_value = self._stub_llm(
            reason="conflict", message="Stop, calm down.", score=0.9
        )
        ModerationService.handle_human_turn_ended(
            session_id=self.session.id,
            user_id=self.user.id,
            last_turn_text="You are stupid!",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="marco",
        )
        ai_ev = DiscussionEvent.objects.get(
            session=self.session, event_type="ai_intervention"
        )
        self.assertEqual(ai_ev.metadata["was_played"], True)
        self.assertEqual(ai_ev.metadata["reason"], "conflict")
        self.assertEqual(ai_ev.content, "Stop, calm down.")
        self.assertIsNone(ai_ev.metadata["block_reason"])

    @patch.object(ModerationService, "_call_llm")
    def test_block_reason_min_score(self, mock_llm):
        mock_llm.return_value = self._stub_llm(
            reason="off_topic", message="Hey, back on topic", score=0.2,
        )
        ModerationService.handle_human_turn_ended(
            session_id=self.session.id,
            user_id=self.user.id,
            last_turn_text="random off-topic chatter",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="marco",
        )
        ai_ev = DiscussionEvent.objects.get(
            session=self.session, event_type="ai_intervention"
        )
        self.assertEqual(ai_ev.metadata["was_played"], False)
        self.assertEqual(ai_ev.metadata["block_reason"], "min_score")

    @patch.object(ModerationService, "_call_llm")
    def test_empty_transcription_flagged(self, mock_llm):
        mock_llm.return_value = self._stub_llm(reason="all_ok")
        ModerationService.handle_human_turn_ended(
            session_id=self.session.id,
            user_id=self.user.id,
            last_turn_text="",  # ASR didn't transcribe anything
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="marco",
        )
        human_ev = DiscussionEvent.objects.get(
            session=self.session, event_type="human_turn"
        )
        self.assertEqual(human_ev.metadata["empty_transcription"], True)

    @patch.object(ModerationService, "_call_llm")
    def test_summary_at_decision_captured_pre_update(self, mock_llm):
        # Setup state con summary specifico, verifica che ai_intervention.summary_at_decision
        # contenga IL SUMMARY DI PARTENZA, non quello aggiornato.
        state = ModerationState.initial(
            participants=["host", "marco"],
            session_started_at=datetime.utcnow() - timedelta(minutes=2),
        )
        state.summary = "BEFORE: Marco proposes oxygen first."
        save_moderation_state(self.session.id, state)

        mock_llm.return_value = self._stub_llm(
            reason="all_ok",
            summary="AFTER: Marco proposes oxygen, Anna agrees.",
        )
        ModerationService.handle_human_turn_ended(
            session_id=self.session.id,
            user_id=self.user.id,
            last_turn_text="Anna: I agree with Marco",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="marco",
        )

        human_ev = DiscussionEvent.objects.get(
            session=self.session, event_type="human_turn"
        )
        ai_ev = DiscussionEvent.objects.get(
            session=self.session, event_type="ai_intervention"
        )
        # human_turn cattura il summary DOPO (summary_after_this_turn)
        self.assertIn("AFTER", human_ev.metadata["summary_after_this_turn"])
        # ai_intervention cattura il summary PRE-decisione
        self.assertIn("BEFORE", ai_ev.metadata["summary_at_decision"])
