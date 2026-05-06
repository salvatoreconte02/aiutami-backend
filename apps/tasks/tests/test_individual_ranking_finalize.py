"""Test della funzione _finalize_individual_ranking_phase (idempotente,
crea righe di default per partecipanti senza ranking, transita ad ACTIVE).
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.sessions.models import Session, SessionParticipant, SessionState, ParticipantRole

User = get_user_model()


def _make_session_in_individual_ranking() -> tuple[Session, list[SessionParticipant]]:
    host = User.objects.create_user(username="h_fin", password="x")
    session = Session.objects.create(
        title="T", context="nasa_moon_survival", min_size=3, max_size=6,
        host=host, state=SessionState.INDIVIDUAL_RANKING,
        individual_ranking_started_at=timezone.now() - timedelta(seconds=10),
    )
    p_host = SessionParticipant.objects.create(
        session=session, user=host, role=ParticipantRole.HOST,
    )
    others = []
    for i in range(2):
        u = User.objects.create_user(username=f"u_fin_{i}", password="x")
        others.append(SessionParticipant.objects.create(
            session=session, user=u, role=ParticipantRole.PARTICIPANT,
        ))
    return session, [p_host, *others]


class FinalizeIndividualRankingPhaseTests(TestCase):
    def test_transitions_to_active_and_sets_started_at(self) -> None:
        from apps.tasks.individual_ranking import _finalize_individual_ranking_phase
        session, _ = _make_session_in_individual_ranking()
        result = _finalize_individual_ranking_phase(session)
        session.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(session.state, SessionState.ACTIVE)
        self.assertIsNotNone(session.started_at)

    def test_creates_default_ranking_for_participants_without_row(self) -> None:
        from apps.tasks.nasa_moon.models import NasaIndividualRanking
        from apps.tasks.nasa_moon.config import NASA_ITEMS
        from apps.tasks.individual_ranking import _finalize_individual_ranking_phase
        session, participants = _make_session_in_individual_ranking()
        _finalize_individual_ranking_phase(session)
        rankings = NasaIndividualRanking.objects.filter(session=session)
        self.assertEqual(rankings.count(), 3)
        for r in rankings:
            self.assertTrue(r.is_submitted)
            self.assertEqual(r.ranked_items, list(NASA_ITEMS))

    def test_marks_existing_unsubmitted_as_submitted(self) -> None:
        from apps.tasks.nasa_moon.models import NasaIndividualRanking
        from apps.tasks.individual_ranking import _finalize_individual_ranking_phase
        session, participants = _make_session_in_individual_ranking()
        from apps.tasks.nasa_moon.config import NASA_ITEMS
        custom = list(reversed(NASA_ITEMS))
        NasaIndividualRanking.objects.create(
            session=session, participant=participants[0],
            ranked_items=custom, is_submitted=False,
        )
        _finalize_individual_ranking_phase(session)
        r = NasaIndividualRanking.objects.get(session=session, participant=participants[0])
        self.assertTrue(r.is_submitted)
        # I dati custom sono preservati: la finalize non li sovrascrive
        self.assertEqual(r.ranked_items, custom)

    def test_idempotent_returns_false_on_second_call(self) -> None:
        from apps.tasks.individual_ranking import _finalize_individual_ranking_phase
        session, _ = _make_session_in_individual_ranking()
        first = _finalize_individual_ranking_phase(session)
        second = _finalize_individual_ranking_phase(session)
        self.assertTrue(first)
        self.assertFalse(second)

    def test_returns_false_if_state_not_individual_ranking(self) -> None:
        from apps.tasks.individual_ranking import _finalize_individual_ranking_phase
        host = User.objects.create_user(username="h_no", password="x")
        session = Session.objects.create(
            title="T", context="nasa_moon_survival", min_size=3, max_size=6,
            host=host, state=SessionState.LOBBY,
        )
        result = _finalize_individual_ranking_phase(session)
        self.assertFalse(result)
        session.refresh_from_db()
        self.assertEqual(session.state, SessionState.LOBBY)

    def test_invokes_active_side_effects_and_ws_broadcast(self) -> None:
        """Verifica che TurnManager / intro pending / mark_started / WS
        broadcast siano effettivamente chiamati dopo la transizione ad ACTIVE.
        Protezione contro refactor che droppa silenziosamente uno dei 4 hook.
        """
        from unittest.mock import patch
        from apps.tasks import individual_ranking as ir_module
        session, _ = _make_session_in_individual_ranking()

        with patch.object(ir_module.TurnManager, "set_introducing") as m_turn, \
             patch.object(ir_module, "set_intro_pending") as m_intro, \
             patch.object(ir_module, "mark_session_started") as m_mark, \
             patch.object(ir_module, "_broadcast_session_event") as m_ws:
            ir_module._finalize_individual_ranking_phase(session)

        sid_str = str(session.id)
        m_turn.assert_called_once_with(session_id=sid_str)
        m_intro.assert_called_once_with(session_id=sid_str)
        m_mark.assert_called_once_with(session_id=session.id)
        m_ws.assert_called_once()
        ws_kwargs = m_ws.call_args.kwargs
        self.assertEqual(ws_kwargs["session_id"], sid_str)
        self.assertEqual(ws_kwargs["event_type"], "STATE_CHANGED")
        self.assertIn("state", ws_kwargs["payload"])

    def test_no_side_effects_when_state_wrong(self) -> None:
        """Difesa: chiamate idempotenti / wrong-state non scatenano side-effects."""
        from unittest.mock import patch
        from apps.tasks import individual_ranking as ir_module
        host = User.objects.create_user(username="h_noss", password="x")
        session = Session.objects.create(
            title="T", context="nasa_moon_survival", min_size=3, max_size=6,
            host=host, state=SessionState.LOBBY,
        )
        with patch.object(ir_module.TurnManager, "set_introducing") as m_turn, \
             patch.object(ir_module, "set_intro_pending") as m_intro, \
             patch.object(ir_module, "mark_session_started") as m_mark, \
             patch.object(ir_module, "_broadcast_session_event") as m_ws:
            ir_module._finalize_individual_ranking_phase(session)
        m_turn.assert_not_called()
        m_intro.assert_not_called()
        m_mark.assert_not_called()
        m_ws.assert_not_called()
